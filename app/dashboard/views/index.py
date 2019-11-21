from dataclasses import dataclass

from flask import render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app import email_utils
from app.config import HIGHLIGHT_GEN_EMAIL_ID
from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, ClientUser, ForwardEmail, ForwardEmailLog, DeletedAlias


@dataclass
class AliasInfo:
    gen_email: GenEmail
    nb_forward: int
    nb_blocked: int
    nb_reply: int

    show_intro_test_send_email: bool = False
    highlight: bool = False


@dashboard_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    # after creating a gen email, it's helpful to highlight it
    highlight_gen_email_id = session.get(HIGHLIGHT_GEN_EMAIL_ID)

    # reset as it should not persist
    if highlight_gen_email_id:
        del session[HIGHLIGHT_GEN_EMAIL_ID]

    # User generates a new email
    if request.method == "POST":
        if request.form.get("form-name") == "trigger-email":
            gen_email_id = request.form.get("gen-email-id")
            gen_email = GenEmail.get(gen_email_id)

            LOG.d("trigger an email to %s", gen_email)
            email_utils.send_test_email_alias(gen_email.email, gen_email.user.name)

            flash(
                f"An email sent to {gen_email.email} is on its way, please check your inbox/spam folder",
                "success",
            )

        elif request.form.get("form-name") == "create-random-email":
            can_create_new_email = current_user.can_create_new_email()

            if can_create_new_email:
                gen_email = GenEmail.create_new_gen_email(user_id=current_user.id)
                db.session.commit()

                LOG.d("generate new email %s for user %s", gen_email, current_user)
                flash(f"Email {gen_email.email} has been created", "success")
                session[HIGHLIGHT_GEN_EMAIL_ID] = gen_email.id
            else:
                flash(
                    f"You need to upgrade your plan to create new random alias.",
                    "warning",
                )

        elif request.form.get("form-name") == "create-custom-email":
            if current_user.can_create_custom_email():
                return redirect(url_for("dashboard.custom_alias"))
            else:
                flash(
                    f"You need to upgrade your plan to create new custom alias.",
                    "warning",
                )

        elif request.form.get("form-name") == "switch-email-forwarding":
            gen_email_id = request.form.get("gen-email-id")
            gen_email: GenEmail = GenEmail.get(gen_email_id)

            LOG.d("switch email forwarding for %s", gen_email)

            gen_email.enabled = not gen_email.enabled
            if gen_email.enabled:
                flash(f"Alias {gen_email.email} is enabled", "success")
            else:
                flash(f"Alias {gen_email.email} is disabled", "warning")
            db.session.commit()

        elif request.form.get("form-name") == "delete-email":
            gen_email_id = request.form.get("gen-email-id")
            gen_email: GenEmail = GenEmail.get(gen_email_id)

            LOG.d("delete gen email %s", gen_email)
            email = gen_email.email
            GenEmail.delete(gen_email.id)

            # save deleted alias
            DeletedAlias.create(user_id=current_user.id, email=gen_email.email)

            db.session.commit()
            flash(f"Email alias {email} has been deleted", "success")

        return redirect(url_for("dashboard.index"))

    client_users = (
        ClientUser.filter_by(user_id=current_user.id)
        .options(joinedload(ClientUser.client))
        .options(joinedload(ClientUser.gen_email))
        .all()
    )

    sorted(client_users, key=lambda cu: cu.client.name)

    return render_template(
        "dashboard/index.html",
        client_users=client_users,
        aliases=get_alias_info(current_user.id, highlight_gen_email_id),
        highlight_gen_email_id=highlight_gen_email_id,
    )


def get_alias_info(user_id, highlight_gen_email_id=None) -> [AliasInfo]:
    aliases = {}  # dict of alias and AliasInfo
    q = db.session.query(GenEmail, ForwardEmail, ForwardEmailLog).filter(
        GenEmail.user_id == user_id,
        GenEmail.id == ForwardEmail.gen_email_id,
        ForwardEmail.id == ForwardEmailLog.forward_id,
    )

    for ge, fe, fel in q:
        if ge.email not in aliases:
            aliases[ge.email] = AliasInfo(
                gen_email=ge,
                nb_blocked=0,
                nb_forward=0,
                nb_reply=0,
                highlight=ge.id == highlight_gen_email_id,
            )

        alias_info = aliases[ge.email]
        if fel.is_reply:
            alias_info.nb_reply += 1
        elif fel.blocked:
            alias_info.nb_blocked += 1
        else:
            alias_info.nb_forward += 1

    # also add alias that has no forward email or log
    q = (
        db.session.query(GenEmail)
        .filter(GenEmail.email.notin_(aliases.keys()))
        .filter(GenEmail.user_id == user_id)
    )
    for ge in q:
        aliases[ge.email] = AliasInfo(
            gen_email=ge,
            nb_blocked=0,
            nb_forward=0,
            nb_reply=0,
            highlight=ge.id == highlight_gen_email_id,
        )

    ret = list(aliases.values())

    # make sure the highlighted alias is the first element
    highlight_index = None
    for ix, alias in enumerate(ret):
        if alias.highlight:
            highlight_index = ix
            break

    if highlight_index:
        ret.insert(0, ret.pop(highlight_index))

    # only show intro on the first enabled alias
    for alias in ret:
        if alias.gen_email.enabled:
            alias.show_intro_test_send_email = True
            break

    return ret

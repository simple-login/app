from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app import email_utils
from app.config import PAGE_LIMIT
from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.log import LOG
from app.models import (
    GenEmail,
    ClientUser,
    ForwardEmail,
    ForwardEmailLog,
    DeletedAlias,
    AliasGeneratorEnum,
)


class AliasInfo:
    id: int
    gen_email: GenEmail
    nb_forward: int
    nb_blocked: int
    nb_reply: int

    show_intro_test_send_email: bool = False
    highlight: bool = False

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@dashboard_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    query = request.args.get("query") or ""
    highlight_gen_email_id = None
    if request.args.get("highlight_gen_email_id"):
        highlight_gen_email_id = int(request.args.get("highlight_gen_email_id"))

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

        elif request.form.get("form-name") == "create-custom-email":
            if current_user.can_create_new_alias():
                return redirect(url_for("dashboard.custom_alias"))
            else:
                flash(f"You need to upgrade your plan to create new alias.", "warning")

        elif request.form.get("form-name") == "create-random-email":
            if current_user.can_create_new_alias():
                scheme = int(
                    request.form.get("generator_scheme") or current_user.alias_generator
                )
                if not scheme or not AliasGeneratorEnum.has_value(scheme):
                    scheme = current_user.alias_generator
                gen_email = GenEmail.create_new_random(
                    user_id=current_user.id, scheme=scheme
                )
                db.session.commit()

                LOG.d("generate new email %s for user %s", gen_email, current_user)
                flash(f"Alias {gen_email.email} has been created", "success")

                return redirect(
                    url_for(
                        "dashboard.index",
                        highlight_gen_email_id=gen_email.id,
                        query=query,
                    )
                )
            else:
                flash(f"You need to upgrade your plan to create new alias.", "warning")

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
            return redirect(
                url_for(
                    "dashboard.index", highlight_gen_email_id=gen_email.id, query=query
                )
            )

        elif request.form.get("form-name") == "delete-email":
            gen_email_id = request.form.get("gen-email-id")
            gen_email: GenEmail = GenEmail.get(gen_email_id)

            LOG.d("delete gen email %s", gen_email)
            email = gen_email.email
            GenEmail.delete(gen_email.id)
            db.session.commit()
            flash(f"Alias {email} has been deleted", "success")

            # try to save deleted alias
            try:
                DeletedAlias.create(user_id=current_user.id, email=email)
                db.session.commit()
            # this can happen when a previously deleted alias is re-created via catch-all or directory feature
            except IntegrityError:
                LOG.error("alias %s has been added before to DeletedAlias", email)
                db.session.rollback()

        elif request.form.get("form-name") == "set-note":
            gen_email_id = request.form.get("gen-email-id")
            gen_email: GenEmail = GenEmail.get(gen_email_id)
            note = request.form.get("note")

            gen_email.note = note
            db.session.commit()

            flash(f"Update note for alias {gen_email.email}", "success")
            return redirect(
                url_for(
                    "dashboard.index", highlight_gen_email_id=gen_email.id, query=query
                )
            )

        return redirect(url_for("dashboard.index", query=query))

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
        aliases=get_alias_info(current_user.id, query, highlight_gen_email_id),
        highlight_gen_email_id=highlight_gen_email_id,
        query=query,
        AliasGeneratorEnum=AliasGeneratorEnum,
    )


def get_alias_info(
    user_id, query=None, highlight_gen_email_id=None, page_id=None
) -> [AliasInfo]:
    if query:
        query = query.strip().lower()

    aliases = {}  # dict of alias and AliasInfo

    q = (
        db.session.query(GenEmail, ForwardEmail, ForwardEmailLog)
        .join(ForwardEmail, GenEmail.id == ForwardEmail.gen_email_id, isouter=True)
        .join(
            ForwardEmailLog, ForwardEmail.id == ForwardEmailLog.forward_id, isouter=True
        )
        .filter(GenEmail.user_id == user_id)
        .order_by(GenEmail.created_at.desc())
    )

    if query:
        q = q.filter(or_(GenEmail.email.contains(query), GenEmail.note.contains(query)))

    # pagination activated
    if page_id is not None:
        q = q.limit(PAGE_LIMIT).offset(page_id * PAGE_LIMIT)

    for ge, fe, fel in q:
        if ge.email not in aliases:
            aliases[ge.email] = AliasInfo(
                id=ge.id,
                gen_email=ge,
                nb_blocked=0,
                nb_forward=0,
                nb_reply=0,
                highlight=ge.id == highlight_gen_email_id,
            )

        alias_info = aliases[ge.email]
        if not fel:
            continue

        if fel.is_reply:
            alias_info.nb_reply += 1
        elif fel.blocked:
            alias_info.nb_blocked += 1
        else:
            alias_info.nb_forward += 1

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

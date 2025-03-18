from io import BytesIO
from typing import Optional, Tuple

import arrow
from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
)
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, validators

from app import s3, user_settings
from app.config import (
    FIRST_ALIAS_DOMAIN,
    ALIAS_RANDOM_SUFFIX_LENGTH,
    CONNECT_WITH_PROTON,
)
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.errors import ProtonPartnerNotSetUp
from app.extensions import limiter
from app.image_validation import detect_image_format, ImageFormat
from app.log import LOG
from app.models import (
    BlockBehaviourEnum,
    PlanEnum,
    File,
    EmailChange,
    AliasGeneratorEnum,
    AliasSuffixEnum,
    ManualSubscription,
    SenderFormatEnum,
    CoinbaseSubscription,
    AppleSubscription,
    PartnerUser,
    PartnerSubscription,
    UnsubscribeBehaviourEnum,
    UserAliasDeleteAction,
)
from app.proton.proton_partner import get_proton_partner
from app.proton.proton_unlink import can_unlink_proton_account
from app.utils import (
    random_string,
    CSRFValidationForm,
)


class SettingForm(FlaskForm):
    name = StringField("Name")
    profile_picture = FileField("Profile Picture")


class PromoCodeForm(FlaskForm):
    code = StringField("Name", validators=[validators.DataRequired()])


def get_proton_linked_account() -> Optional[str]:
    # Check if the current user has a partner_id
    try:
        proton_partner_id = get_proton_partner().id
    except ProtonPartnerNotSetUp:
        return None

    # It has. Retrieve the information for the PartnerUser
    proton_linked_account = PartnerUser.get_by(
        user_id=current_user.id, partner_id=proton_partner_id
    )
    if proton_linked_account is None:
        return None
    return proton_linked_account.partner_email


def get_partner_subscription_and_name(
    user_id: int,
) -> Optional[Tuple[PartnerSubscription, str]]:
    partner_sub = PartnerSubscription.find_by_user_id(user_id)
    if not partner_sub or not partner_sub.is_active():
        return None

    partner = partner_sub.partner_user.partner
    return (partner_sub, partner.name)


@dashboard_bp.route("/setting", methods=["GET", "POST"])
@login_required
@limiter.limit("5/minute", methods=["POST"])
def setting():
    form = SettingForm()
    promo_form = PromoCodeForm()
    csrf_form = CSRFValidationForm()

    email_change = EmailChange.get_by(user_id=current_user.id)
    if email_change:
        pending_email = email_change.new_email
    else:
        pending_email = None

    if request.method == "POST":
        if not csrf_form.validate():
            flash("Invalid request", "warning")
            return redirect(url_for("dashboard.setting"))

        if request.form.get("form-name") == "update-profile":
            if form.validate():
                profile_updated = False
                # update user info
                if form.name.data != current_user.name:
                    current_user.name = form.name.data
                    Session.commit()
                    profile_updated = True

                if form.profile_picture.data:
                    image_contents = form.profile_picture.data.read()
                    if detect_image_format(image_contents) == ImageFormat.Unknown:
                        flash(
                            "This image format is not supported",
                            "error",
                        )
                        return redirect(url_for("dashboard.setting"))

                    if current_user.profile_picture_id is not None:
                        current_profile_file = File.get_by(
                            id=current_user.profile_picture_id
                        )
                        if (
                            current_profile_file is not None
                            and current_profile_file.user_id == current_user.id
                        ):
                            s3.delete(current_profile_file.path)

                    file_path = random_string(30)
                    file = File.create(user_id=current_user.id, path=file_path)

                    s3.upload_from_bytesio(file_path, BytesIO(image_contents))

                    Session.flush()
                    LOG.d("upload file %s to s3", file)

                    current_user.profile_picture_id = file.id
                    Session.commit()
                    profile_updated = True

                if profile_updated:
                    flash("Your profile has been updated", "success")
                    return redirect(url_for("dashboard.setting"))
        elif request.form.get("form-name") == "notification-preference":
            choose = request.form.get("notification")
            if choose == "on":
                current_user.notification = True
            else:
                current_user.notification = False
            Session.commit()
            flash("Your notification preference has been updated", "success")
            return redirect(url_for("dashboard.setting"))
        elif request.form.get("form-name") == "change-alias-generator":
            scheme = int(request.form.get("alias-generator-scheme"))
            if AliasGeneratorEnum.has_value(scheme):
                current_user.alias_generator = scheme
                Session.commit()
            flash("Your preference has been updated", "success")
            return redirect(url_for("dashboard.setting"))
        elif request.form.get("form-name") == "change-random-alias-default-domain":
            default_domain = request.form.get("random-alias-default-domain")
            try:
                user_settings.set_default_alias_domain(current_user, default_domain)
            except user_settings.CannotSetAlias as e:
                flash(e.msg, "error")
                return redirect(url_for("dashboard.setting"))

            Session.commit()
            flash("Your preference has been updated", "success")
            return redirect(url_for("dashboard.setting"))
        elif request.form.get("form-name") == "random-alias-suffix":
            try:
                scheme = int(request.form.get("random-alias-suffix-generator"))
            except ValueError:
                flash("Invalid value", "error")
                return redirect(url_for("dashboard.setting"))

            if AliasSuffixEnum.has_value(scheme):
                current_user.random_alias_suffix = scheme
                Session.commit()
            flash("Your preference has been updated", "success")
            return redirect(url_for("dashboard.setting"))
        elif request.form.get("form-name") == "change-sender-format":
            sender_format = int(request.form.get("sender-format"))
            if SenderFormatEnum.has_value(sender_format):
                current_user.sender_format = sender_format
                current_user.sender_format_updated_at = arrow.now()
                Session.commit()
                flash("Your sender format preference has been updated", "success")
            Session.commit()
            return redirect(url_for("dashboard.setting"))
        elif request.form.get("form-name") == "replace-ra":
            choose = request.form.get("replace-ra")
            if choose == "on":
                current_user.replace_reverse_alias = True
            else:
                current_user.replace_reverse_alias = False
            Session.commit()
            flash("Your preference has been updated", "success")
            return redirect(url_for("dashboard.setting"))
        elif request.form.get("form-name") == "enable_data_breach_check":
            if not current_user.is_premium():
                flash("Only premium plan can enable data breach monitoring", "warning")
                return redirect(url_for("dashboard.setting"))
            choose = request.form.get("enable_data_breach_check")
            if choose == "on":
                LOG.i("User {current_user} has enabled data breach monitoring")
                current_user.enable_data_breach_check = True
                flash("Data breach monitoring is enabled", "success")
            else:
                LOG.i("User {current_user} has disabled data breach monitoring")
                current_user.enable_data_breach_check = False
                flash("Data breach monitoring is disabled", "info")
            Session.commit()
            return redirect(url_for("dashboard.setting"))
        elif request.form.get("form-name") == "sender-in-ra":
            choose = request.form.get("enable")
            if choose == "on":
                current_user.include_sender_in_reverse_alias = True
            else:
                current_user.include_sender_in_reverse_alias = False
            Session.commit()
            flash("Your preference has been updated", "success")
            return redirect(url_for("dashboard.setting"))
        elif request.form.get("form-name") == "expand-alias-info":
            choose = request.form.get("enable")
            if choose == "on":
                current_user.expand_alias_info = True
            else:
                current_user.expand_alias_info = False
            Session.commit()
            flash("Your preference has been updated", "success")
            return redirect(url_for("dashboard.setting"))
        elif request.form.get("form-name") == "ignore-loop-email":
            choose = request.form.get("enable")
            if choose == "on":
                current_user.ignore_loop_email = True
            else:
                current_user.ignore_loop_email = False
            Session.commit()
            flash("Your preference has been updated", "success")
            return redirect(url_for("dashboard.setting"))
        elif request.form.get("form-name") == "one-click-unsubscribe":
            choose = request.form.get("unsubscribe-behaviour")
            if choose == UnsubscribeBehaviourEnum.PreserveOriginal.name:
                current_user.unsub_behaviour = UnsubscribeBehaviourEnum.PreserveOriginal
            elif choose == UnsubscribeBehaviourEnum.DisableAlias.name:
                current_user.unsub_behaviour = UnsubscribeBehaviourEnum.DisableAlias
            elif choose == UnsubscribeBehaviourEnum.BlockContact.name:
                current_user.unsub_behaviour = UnsubscribeBehaviourEnum.BlockContact
            else:
                flash("There was an error. Please try again", "warning")
                return redirect(url_for("dashboard.setting"))
            Session.commit()
            flash("Your preference has been updated", "success")
            return redirect(url_for("dashboard.setting"))
        elif request.form.get("form-name") == "include_website_in_one_click_alias":
            choose = request.form.get("enable")
            if choose == "on":
                current_user.include_website_in_one_click_alias = True
            else:
                current_user.include_website_in_one_click_alias = False
            Session.commit()
            flash("Your preference has been updated", "success")
            return redirect(url_for("dashboard.setting"))
        elif request.form.get("form-name") == "change-blocked-behaviour":
            choose = request.form.get("blocked-behaviour")
            if choose == str(BlockBehaviourEnum.return_2xx.value):
                current_user.block_behaviour = BlockBehaviourEnum.return_2xx.name
            elif choose == str(BlockBehaviourEnum.return_5xx.value):
                current_user.block_behaviour = BlockBehaviourEnum.return_5xx.name
            else:
                flash("There was an error. Please try again", "warning")
                return redirect(url_for("dashboard.setting"))
            Session.commit()
            flash("Your preference has been updated", "success")
        elif request.form.get("form-name") == "sender-header":
            choose = request.form.get("enable")
            if choose == "on":
                current_user.include_header_email_header = True
            else:
                current_user.include_header_email_header = False
            Session.commit()
            flash("Your preference has been updated", "success")
            return redirect(url_for("dashboard.setting"))
        elif request.form.get("form-name") == "alias-delete-action":
            action = request.form.get("alias-delete-action")
            if action == str(UserAliasDeleteAction.MoveToTrash.value):
                current_user.alias_delete_action = UserAliasDeleteAction.MoveToTrash
            elif action == str(UserAliasDeleteAction.DeleteImmediately.value):
                current_user.alias_delete_action = (
                    UserAliasDeleteAction.DeleteImmediately
                )
            else:
                flash("There was an error. Please try again", "warning")
                return redirect(url_for("dashboard.setting"))
            Session.commit()
            flash("Your preference has been updated", "success")

    manual_sub = ManualSubscription.get_by(user_id=current_user.id)
    apple_sub = AppleSubscription.get_by(user_id=current_user.id)
    coinbase_sub = CoinbaseSubscription.get_by(user_id=current_user.id)
    paddle_sub = current_user.get_paddle_subscription()
    partner_sub = None
    partner_name = None

    partner_sub_name = get_partner_subscription_and_name(current_user.id)
    if partner_sub_name:
        partner_sub, partner_name = partner_sub_name

    proton_linked_account = get_proton_linked_account()

    return render_template(
        "dashboard/setting.html",
        csrf_form=csrf_form,
        form=form,
        PlanEnum=PlanEnum,
        SenderFormatEnum=SenderFormatEnum,
        BlockBehaviourEnum=BlockBehaviourEnum,
        promo_form=promo_form,
        pending_email=pending_email,
        AliasGeneratorEnum=AliasGeneratorEnum,
        UnsubscribeBehaviourEnum=UnsubscribeBehaviourEnum,
        UserAliasDeleteAction=UserAliasDeleteAction,
        manual_sub=manual_sub,
        partner_sub=partner_sub,
        partner_name=partner_name,
        apple_sub=apple_sub,
        paddle_sub=paddle_sub,
        coinbase_sub=coinbase_sub,
        FIRST_ALIAS_DOMAIN=FIRST_ALIAS_DOMAIN,
        ALIAS_RAND_SUFFIX_LENGTH=ALIAS_RANDOM_SUFFIX_LENGTH,
        connect_with_proton=CONNECT_WITH_PROTON,
        proton_linked_account=proton_linked_account,
        can_unlink_proton_account=can_unlink_proton_account(current_user),
    )

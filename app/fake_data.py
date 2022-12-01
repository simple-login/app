import os

import arrow

from app import s3
from app.config import ROOT_DIR, get_abs_path, FIRST_ALIAS_DOMAIN
from app.db import Session
from app.log import LOG
from app.models import (
    User,
    File,
    Alias,
    RefusedEmail,
    Contact,
    EmailLog,
    LifetimeCoupon,
    Coupon,
    Subscription,
    PlanEnum,
    CoinbaseSubscription,
    ApiKey,
    Mailbox,
    AliasMailbox,
    CustomDomain,
    Directory,
    Client,
    RedirectUri,
    ClientUser,
    Referral,
    Payout,
    Notification,
    ManualSubscription,
    SLDomain,
    Hibp,
    AliasHibp,
)
from app.pgp_utils import load_public_key


def fake_data():
    LOG.d("create fake data")

    # Create a user
    user = User.create(
        email="john@wick.com",
        name="John Wick",
        password="password",
        activated=True,
        is_admin=True,
        # enable_otp=True,
        otp_secret="base32secret3232",
        intro_shown=True,
        fido_uuid=None,
    )
    user.trial_end = None
    Session.commit()

    # add a profile picture
    file_path = "profile_pic.svg"
    s3.upload_from_bytesio(
        file_path,
        open(os.path.join(ROOT_DIR, "static", "default-icon.svg"), "rb"),
        content_type="image/svg",
    )
    file = File.create(user_id=user.id, path=file_path, commit=True)
    user.profile_picture_id = file.id
    Session.commit()

    # create a bounced email
    alias = Alias.create_new_random(user)
    Session.commit()

    bounce_email_file_path = "bounce.eml"
    s3.upload_email_from_bytesio(
        bounce_email_file_path,
        open(os.path.join(ROOT_DIR, "local_data", "email_tests", "2.eml"), "rb"),
        "download.eml",
    )
    refused_email = RefusedEmail.create(
        path=bounce_email_file_path,
        full_report_path=bounce_email_file_path,
        user_id=user.id,
        commit=True,
    )

    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="hey@google.com",
        reply_email="rep@sl.local",
        commit=True,
    )
    EmailLog.create(
        user_id=user.id,
        contact_id=contact.id,
        alias_id=contact.alias_id,
        refused_email_id=refused_email.id,
        bounced=True,
        commit=True,
    )

    LifetimeCoupon.create(code="lifetime-coupon", nb_used=10, commit=True)
    Coupon.create(code="coupon", commit=True)

    # Create a subscription for user
    Subscription.create(
        user_id=user.id,
        cancel_url="https://checkout.paddle.com/subscription/cancel?user=1234",
        update_url="https://checkout.paddle.com/subscription/update?user=1234",
        subscription_id="123",
        event_time=arrow.now(),
        next_bill_date=arrow.now().shift(days=10).date(),
        plan=PlanEnum.monthly,
        commit=True,
    )

    CoinbaseSubscription.create(
        user_id=user.id, end_at=arrow.now().shift(days=10), commit=True
    )

    api_key = ApiKey.create(user_id=user.id, name="Chrome")
    api_key.code = "code"

    api_key = ApiKey.create(user_id=user.id, name="Firefox")
    api_key.code = "codeFF"

    pgp_public_key = open(get_abs_path("local_data/public-pgp.asc")).read()
    m1 = Mailbox.create(
        user_id=user.id,
        email="pgp@example.org",
        verified=True,
        pgp_public_key=pgp_public_key,
    )
    m1.pgp_finger_print = load_public_key(pgp_public_key)
    Session.commit()

    # example@example.com is in a LOT of data breaches
    Alias.create(email="example@example.com", user_id=user.id, mailbox_id=m1.id)

    for i in range(3):
        if i % 2 == 0:
            a = Alias.create(
                email=f"e{i}@{FIRST_ALIAS_DOMAIN}", user_id=user.id, mailbox_id=m1.id
            )
        else:
            a = Alias.create(
                email=f"e{i}@{FIRST_ALIAS_DOMAIN}",
                user_id=user.id,
                mailbox_id=user.default_mailbox_id,
            )
        Session.commit()

        if i % 5 == 0:
            if i % 2 == 0:
                AliasMailbox.create(alias_id=a.id, mailbox_id=user.default_mailbox_id)
            else:
                AliasMailbox.create(alias_id=a.id, mailbox_id=m1.id)
        Session.commit()

        # some aliases don't have any activity
        # if i % 3 != 0:
        #     contact = Contact.create(
        #         user_id=user.id,
        #         alias_id=a.id,
        #         website_email=f"contact{i}@example.com",
        #         reply_email=f"rep{i}@sl.local",
        #     )
        #     Session.commit()
        #     for _ in range(3):
        #         EmailLog.create(user_id=user.id, contact_id=contact.id, alias_id=contact.alias_id)
        #         Session.commit()

        # have some disabled alias
        if i % 5 == 0:
            a.enabled = False
            Session.commit()

    custom_domain1 = CustomDomain.create(user_id=user.id, domain="ab.cd", verified=True)
    Session.commit()

    Alias.create(
        user_id=user.id,
        email="first@ab.cd",
        mailbox_id=user.default_mailbox_id,
        custom_domain_id=custom_domain1.id,
        commit=True,
    )

    Alias.create(
        user_id=user.id,
        email="second@ab.cd",
        mailbox_id=user.default_mailbox_id,
        custom_domain_id=custom_domain1.id,
        commit=True,
    )

    Directory.create(user_id=user.id, name="abcd")
    Directory.create(user_id=user.id, name="xyzt")
    Session.commit()

    # Create a client
    client1 = Client.create_new(name="Demo", user_id=user.id)
    client1.oauth_client_id = "client-id"
    client1.oauth_client_secret = "client-secret"
    Session.commit()

    RedirectUri.create(
        client_id=client1.id, uri="https://your-website.com/oauth-callback"
    )

    client2 = Client.create_new(name="Demo 2", user_id=user.id)
    client2.oauth_client_id = "client-id2"
    client2.oauth_client_secret = "client-secret2"
    Session.commit()

    ClientUser.create(user_id=user.id, client_id=client1.id, name="Fake Name")

    referral = Referral.create(user_id=user.id, code="Website", name="First referral")
    Referral.create(user_id=user.id, code="Podcast", name="First referral")
    Payout.create(
        user_id=user.id, amount=1000, number_upgraded_account=100, payment_method="BTC"
    )
    Payout.create(
        user_id=user.id,
        amount=5000,
        number_upgraded_account=200,
        payment_method="PayPal",
    )
    Session.commit()

    for i in range(6):
        Notification.create(user_id=user.id, message=f"""Hey hey <b>{i}</b> """ * 10)
    Session.commit()

    user2 = User.create(
        email="winston@continental.com",
        password="password",
        activated=True,
        referral_id=referral.id,
    )
    Mailbox.create(user_id=user2.id, email="winston2@high.table", verified=True)
    Session.commit()

    ManualSubscription.create(
        user_id=user2.id,
        end_at=arrow.now().shift(years=1, days=1),
        comment="Local manual",
        commit=True,
    )

    SLDomain.create(domain="premium.com", premium_only=True, commit=True)

    hibp1 = Hibp.create(
        name="first breach", description="breach description", commit=True
    )
    hibp2 = Hibp.create(
        name="second breach", description="breach description", commit=True
    )
    breached_alias1 = Alias.create(
        email="john@example.com", user_id=user.id, mailbox_id=m1.id, commit=True
    )
    breached_alias2 = Alias.create(
        email="wick@example.com", user_id=user.id, mailbox_id=m1.id, commit=True
    )
    AliasHibp.create(hibp_id=hibp1.id, alias_id=breached_alias1.id)
    AliasHibp.create(hibp_id=hibp2.id, alias_id=breached_alias2.id)

    # old domain will have ownership_verified=True
    CustomDomain.create(
        user_id=user.id, domain="old.com", verified=True, ownership_verified=True
    )

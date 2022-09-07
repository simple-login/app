import email
import os
from email.message import EmailMessage
from email.utils import formataddr

import arrow
import pytest

from app.config import MAX_ALERT_24H, EMAIL_DOMAIN, ROOT_DIR
from app.db import Session
from app.email_utils import (
    get_email_domain_part,
    can_create_directory_for_address,
    email_can_be_used_as_mailbox,
    delete_header,
    add_or_replace_header,
    send_email_with_rate_control,
    copy,
    get_spam_from_header,
    get_header_from_bounce,
    is_valid_email,
    add_header,
    generate_reply_email,
    normalize_reply_email,
    get_encoding,
    encode_text,
    EmailEncoding,
    replace,
    should_disable,
    decode_text,
    parse_id_from_bounce,
    get_queue_id,
    should_ignore_bounce,
    get_header_unicode,
    parse_full_address,
    get_orig_message_from_bounce,
    get_mailbox_bounce_info,
    is_invalid_mailbox_domain,
    generate_verp_email,
    get_verp_info_from_email,
    sl_formataddr,
)
from app.models import (
    CustomDomain,
    Alias,
    Contact,
    EmailLog,
    IgnoreBounceSender,
    InvalidMailboxDomain,
    VerpType,
)

# flake8: noqa: E101, W191
from tests.utils import login, load_eml_file, create_new_user, random_domain


def test_get_email_domain_part():
    assert get_email_domain_part("ab@cd.com") == "cd.com"


def test_email_belongs_to_alias_domains():
    # default alias domain
    assert can_create_directory_for_address("ab@sl.local")
    assert not can_create_directory_for_address("ab@not-exist.local")

    assert can_create_directory_for_address("hey@d1.test")
    assert not can_create_directory_for_address("hey@d3.test")


@pytest.mark.skipif(
    "GITHUB_ACTIONS_TEST" in os.environ,
    reason="this test requires DNS lookup that does not work on Github CI",
)
def test_can_be_used_as_personal_email(flask_client):
    # default alias domain
    assert not email_can_be_used_as_mailbox("ab@sl.local")
    assert not email_can_be_used_as_mailbox("hey@d1.test")

    # custom domain
    domain = random_domain()
    user = create_new_user()
    CustomDomain.create(user_id=user.id, domain=domain, verified=True, commit=True)
    assert not email_can_be_used_as_mailbox(f"hey@{domain}")

    # disposable domain
    assert not email_can_be_used_as_mailbox("abcd@10minutesmail.fr")
    assert not email_can_be_used_as_mailbox("abcd@temp-mail.com")
    # subdomain will not work
    assert not email_can_be_used_as_mailbox("abcd@sub.temp-mail.com")
    # valid domains should not be affected
    assert email_can_be_used_as_mailbox("abcd@protonmail.com")
    assert email_can_be_used_as_mailbox("abcd@gmail.com")


def test_delete_header():
    msg = EmailMessage()
    assert msg._headers == []

    msg["H"] = "abcd"
    msg["H"] = "xyzt"

    assert msg._headers == [("H", "abcd"), ("H", "xyzt")]

    delete_header(msg, "H")
    assert msg._headers == []


def test_add_or_replace_header():
    msg = EmailMessage()
    msg["H"] = "abcd"
    msg["H"] = "xyzt"
    assert msg._headers == [("H", "abcd"), ("H", "xyzt")]

    add_or_replace_header(msg, "H", "new")
    assert msg._headers == [("H", "new")]


def test_parse_full_address():
    # only email
    assert parse_full_address("abcd@gmail.com") == (
        "",
        "abcd@gmail.com",
    )

    # ascii address
    assert parse_full_address("First Last <abcd@gmail.com>") == (
        "First Last",
        "abcd@gmail.com",
    )

    # Handle quote
    assert parse_full_address('"First Last" <abcd@gmail.com>') == (
        "First Last",
        "abcd@gmail.com",
    )

    # UTF-8 charset
    assert parse_full_address("=?UTF-8?B?TmjGoW4gTmd1eeG7hW4=?= <abcd@gmail.com>") == (
        "Nhơn Nguyễn",
        "abcd@gmail.com",
    )

    # iso-8859-1 charset
    assert parse_full_address("=?iso-8859-1?q?p=F6stal?= <abcd@gmail.com>") == (
        "pöstal",
        "abcd@gmail.com",
    )

    with pytest.raises(ValueError):
        parse_full_address("https://ab.cd")


def test_send_email_with_rate_control(flask_client):
    user = create_new_user()

    for _ in range(MAX_ALERT_24H):
        assert send_email_with_rate_control(
            user, "test alert type", "abcd@gmail.com", "subject", "plaintext"
        )
    assert not send_email_with_rate_control(
        user, "test alert type", "abcd@gmail.com", "subject", "plaintext"
    )


def test_get_spam_from_header():
    is_spam, _ = get_spam_from_header(
        """No, score=-0.1 required=5.0 tests=DKIM_SIGNED,DKIM_VALID,
  DKIM_VALID_AU,RCVD_IN_DNSWL_BLOCKED,RCVD_IN_MSPIKE_H2,SPF_PASS,
  URIBL_BLOCKED autolearn=unavailable autolearn_force=no version=3.4.2"""
    )
    assert not is_spam

    is_spam, _ = get_spam_from_header(
        """Yes, score=-0.1 required=5.0 tests=DKIM_SIGNED,DKIM_VALID,
  DKIM_VALID_AU,RCVD_IN_DNSWL_BLOCKED,RCVD_IN_MSPIKE_H2,SPF_PASS,
  URIBL_BLOCKED autolearn=unavailable autolearn_force=no version=3.4.2"""
    )
    assert is_spam

    # the case where max_score is less than the default used by SpamAssassin
    is_spam, _ = get_spam_from_header(
        """No, score=6 required=10.0 tests=DKIM_SIGNED,DKIM_VALID,
  DKIM_VALID_AU,RCVD_IN_DNSWL_BLOCKED,RCVD_IN_MSPIKE_H2,SPF_PASS,
  URIBL_BLOCKED autolearn=unavailable autolearn_force=no version=3.4.2""",
        max_score=5,
    )
    assert is_spam


def test_get_header_from_bounce():
    # this is an actual bounce report from iCloud anonymized
    msg_str = """Received: by mx1.simplelogin.co (Postfix)
	id 9988776655; Mon, 24 Aug 2020 06:20:07 +0000 (UTC)
Date: Mon, 24 Aug 2020 06:20:07 +0000 (UTC)
From: MAILER-DAEMON@bounce.simplelogin.io (Mail Delivery System)
Subject: Undelivered Mail Returned to Sender
To: reply+longstring@simplelogin.co
Auto-Submitted: auto-replied
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status;
	boundary="XXYYZZTT.1598250007/mx1.simplelogin.co"
Content-Transfer-Encoding: 8bit
Message-Id: <20200824062007.9988776655@mx1.simplelogin.co>

This is a MIME-encapsulated message.

--XXYYZZTT.1598250007/mx1.simplelogin.co
Content-Description: Notification
Content-Type: text/plain; charset=utf-8
Content-Transfer-Encoding: 8bit

This is the mail system at host mx1.simplelogin.co.

I'm sorry to have to inform you that your message could not
be delivered to one or more recipients. It's attached below.

For further assistance, please send mail to <postmaster@simplelogin.io>

If you do so, please include this problem report. You can
delete your own text from the attached returned message.

                   The mail system

<something@icloud.com>: host mx01.mail.icloud.com[17.57.154.6] said:
    554 5.7.1 [CS01] Message rejected due to local policy. Please visit
    https://support.apple.com/en-us/HT204137 (in reply to end of DATA command)

--XXYYZZTT.1598250007/mx1.simplelogin.co
Content-Description: Delivery report
Content-Type: message/delivery-status

Reporting-MTA: dns; mx1.simplelogin.co
X-Postfix-Queue-ID: XXYYZZTT
X-Postfix-Sender: rfc822; reply+longstring@simplelogin.co
Arrival-Date: Mon, 24 Aug 2020 06:20:04 +0000 (UTC)

Final-Recipient: rfc822; something@icloud.com
Original-Recipient: rfc822;something@icloud.com
Action: failed
Status: 5.7.1
Remote-MTA: dns; mx01.mail.icloud.com
Diagnostic-Code: smtp; 554 5.7.1 [CS01] Message rejected due to local policy.
    Please visit https://support.apple.com/en-us/HT204137

--XXYYZZTT.1598250007/mx1.simplelogin.co
Content-Description: Undelivered Message Headers
Content-Type: text/rfc822-headers
Content-Transfer-Encoding: 8bit

Return-Path: <reply+longstring@simplelogin.co>
X-SimpleLogin-Client-IP: 172.17.0.4
Received: from [172.17.0.4] (unknown [172.17.0.4])
	by mx1.simplelogin.co (Postfix) with ESMTP id XXYYZZTT
	for <something@icloud.com>; Mon, 24 Aug 2020 06:20:04 +0000 (UTC)
Received-SPF: Pass (mailfrom) identity=mailfrom; client-ip=91.241.74.242;
 helo=mail23-242.srv2.de; envelope-from=return@mailing.dhl.de;
 receiver=<UNKNOWN>
Received: from mail23-242.srv2.de (mail23-242.srv2.de [91.241.74.242])
	(using TLSv1.3 with cipher TLS_AES_256_GCM_SHA384 (256/256 bits))
	(No client certificate requested)
	by mx1.simplelogin.co (Postfix) with ESMTPS id B7D123F1C6
	for <dhl@something.com>; Mon, 24 Aug 2020 06:20:03 +0000 (UTC)
Message-ID: <368362807.12707001.1598249997169@rnd-04.broadmail.live>
MIME-Version: 1.0
Content-Type: multipart/signed; protocol="application/pkcs7-signature";
 micalg=sha-256;
	boundary="----=_Part_12707000_248822956.1598249997168"
Date: Mon, 24 Aug 2020 08:19:57 +0200 (CEST)
To: dhl@something.com
Subject: Test subject
X-ulpe:
 re-pO_5F8NoxrdpyqkmsptkpyTxDqB3osb7gfyo-41ZOK78E-3EOXXNLB-FKZPLZ@mailing.dhl.de
List-Id: <1CZ4Z7YB-1DYLQB8.mailing.dhl.de>
X-Report-Spam: complaints@episerver.com
X-CSA-Complaints: whitelist-complaints@eco.de
List-Unsubscribe-Post: List-Unsubscribe=One-Click
mkaTechnicalID: 123456
Feedback-ID: 1CZ4Z7YB:3EOXXNLB:episerver
X-SimpleLogin-Type: Forward
X-SimpleLogin-Mailbox-ID: 1234
X-SimpleLogin-EmailLog-ID: 654321
From: "DHL Paket - noreply@dhl.de"
 <reply+longstring@simplelogin.co>
List-Unsubscribe: <mailto:unsubsribe@simplelogin.co?subject=123456=>
DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/simple; d=simplelogin.co;
  i=@simplelogin.co; q=dns/txt; s=dkim; t=1598250004; h=from : to;
  bh=nXVR9uziNfqtwyhq6gQLFJvFtdyQ8WY/w7c1mCaf7bg=;
  b=QY/Jb4ls0zFOqExWFkwW9ZOKNvkYPDsj74ar1LNm703kyL341KwX3rGnnicrLV7WxYo8+
  pBY0HO7OSAJEOqmYdagAlVouuFiBMUtS2Jw/jiPHzcuvunE9JFOZFRUnNMKrr099i10U4H9
  ZwE8i6lQzG6IMN4spjxJ2HCO8hiB3AU=

--XXYYZZTT.1598250007/mx1.simplelogin.co--

    """
    assert (
        get_header_from_bounce(
            email.message_from_string(msg_str), "X-SimpleLogin-Mailbox-ID"
        )
        == "1234"
    )
    assert (
        get_header_from_bounce(
            email.message_from_string(msg_str), "X-SimpleLogin-EmailLog-ID"
        )
        == "654321"
    )
    assert (
        get_header_from_bounce(email.message_from_string(msg_str), "Not-exist") is None
    )


def test_is_valid_email():
    assert is_valid_email("abcd@gmail.com")
    assert not is_valid_email("")
    assert not is_valid_email("  ")
    assert not is_valid_email("with space@gmail.com")
    assert not is_valid_email("strange char !ç@gmail.com")
    assert not is_valid_email("emoji👌@gmail.com")


def test_add_header_plain_text():
    msg = email.message_from_string(
        """Content-Type: text/plain; charset=us-ascii
Content-Transfer-Encoding: 7bit
Test-Header: Test-Value

coucou
"""
    )
    new_msg = add_header(msg, "text header", "html header")
    assert "text header" in new_msg.as_string()
    assert "html header" not in new_msg.as_string()


def test_add_header_html():
    msg = email.message_from_string(
        """Content-Type: text/html; charset=us-ascii
Content-Transfer-Encoding: 7bit
Test-Header: Test-Value

<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=us-ascii">
</head>
<body style="word-wrap: break-word;" class="">
<b class="">bold</b>
</body>
</html>
"""
    )
    new_msg = add_header(msg, "text header", "html header")
    assert "Test-Header: Test-Value" in new_msg.as_string()
    assert "<table" in new_msg.as_string()
    assert "</table>" in new_msg.as_string()
    assert "html header" in new_msg.as_string()
    assert "text header" not in new_msg.as_string()


def test_add_header_multipart_alternative():
    msg = email.message_from_string(
        """Content-Type: multipart/alternative;
    boundary="foo"
Content-Transfer-Encoding: 7bit
Test-Header: Test-Value

--foo
Content-Transfer-Encoding: 7bit
Content-Type: text/plain;
	charset=us-ascii

bold

--foo
Content-Transfer-Encoding: 7bit
Content-Type: text/html;
	charset=us-ascii

<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=us-ascii">
</head>
<body style="word-wrap: break-word;" class="">
<b class="">bold</b>
</body>
</html>
"""
    )
    new_msg = add_header(msg, "text header", "html header")
    assert "Test-Header: Test-Value" in new_msg.as_string()
    assert "<table" in new_msg.as_string()
    assert "</table>" in new_msg.as_string()
    assert "html header" in new_msg.as_string()
    assert "text header" in new_msg.as_string()


def test_replace_no_encoding():
    msg = email.message_from_string(
        """Content-Type: text/plain; charset=us-ascii
Content-Transfer-Encoding: 7bit
Test-Header: Test-Value

old
"""
    )
    new_msg = replace(msg, "old", "new")
    assert "new" in new_msg.as_string()
    assert "old" not in new_msg.as_string()

    # headers are not affected
    assert "Test-Header: Test-Value" in new_msg.as_string()


def test_replace_base64_encoding():
    # "b2xk" is "old" base64-encoded
    msg = email.message_from_string(
        """Content-Type: text/plain; charset=us-ascii
Content-Transfer-Encoding: base64

b2xk
"""
    )
    new_msg = replace(msg, "old", "new")
    # bmV3 is new base64 encoded
    assert "bmV3" in new_msg.as_string()
    assert "b2xk" not in new_msg.as_string()


def test_replace_multipart_alternative():
    msg = email.message_from_string(
        """Content-Type: multipart/alternative;
    boundary="foo"
Content-Transfer-Encoding: 7bit
Test-Header: Test-Value

--foo
Content-Transfer-Encoding: 7bit
Content-Type: text/plain;	charset=us-ascii

old

--foo
Content-Transfer-Encoding: 7bit
Content-Type: text/html;	charset=us-ascii

<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=us-ascii">
</head>
<body style="word-wrap: break-word;" class="">
<b class="">old</b>
</body>
</html>
"""
    )
    new_msg = replace(msg, "old", "new")
    # headers are not affected
    assert "Test-Header: Test-Value" in new_msg.as_string()

    assert "new" in new_msg.as_string()
    assert "old" not in new_msg.as_string()


def test_replace_str():
    msg = "a string"
    new_msg = replace(msg, "a", "still a")
    assert new_msg == "still a string"


def test_generate_reply_email(flask_client):
    user = create_new_user()
    reply_email = generate_reply_email("test@example.org", user)
    assert reply_email.endswith(EMAIL_DOMAIN)

    reply_email = generate_reply_email("", user)
    assert reply_email.endswith(EMAIL_DOMAIN)


def test_generate_reply_email_include_sender_in_reverse_alias(flask_client):
    # user enables include_sender_in_reverse_alias
    user = create_new_user()
    user.include_sender_in_reverse_alias = True

    reply_email = generate_reply_email("test@example.org", user)
    assert reply_email.startswith("test_at_example_org")
    assert reply_email.endswith(EMAIL_DOMAIN)

    reply_email = generate_reply_email("", user)
    assert reply_email.endswith(EMAIL_DOMAIN)

    reply_email = generate_reply_email("👌汉字@example.org", user)
    assert reply_email.startswith("yizi_at_example_org")

    # make sure reply_email only contain lowercase
    reply_email = generate_reply_email("TEST@example.org", user)
    assert reply_email.startswith("test_at_example_org")

    reply_email = generate_reply_email("test.dot@example.org", user)
    assert reply_email.startswith("test_dot_at_example_org")


def test_normalize_reply_email(flask_client):
    assert normalize_reply_email("re+abcd@sl.local") == "re+abcd@sl.local"
    assert normalize_reply_email('re+"ab cd"@sl.local') == "re+_ab_cd_@sl.local"


def test_get_encoding():
    msg = email.message_from_string("")
    assert get_encoding(msg) == EmailEncoding.NO

    msg = email.message_from_string("Content-TRANSFER-encoding: Invalid")
    assert get_encoding(msg) == EmailEncoding.NO

    msg = email.message_from_string("Content-TRANSFER-encoding: 7bit")
    assert get_encoding(msg) == EmailEncoding.NO

    msg = email.message_from_string("Content-TRANSFER-encoding: 8bit")
    assert get_encoding(msg) == EmailEncoding.NO

    msg = email.message_from_string("Content-TRANSFER-encoding: binary")
    assert get_encoding(msg) == EmailEncoding.NO

    msg = email.message_from_string("Content-TRANSFER-encoding: quoted-printable")
    assert get_encoding(msg) == EmailEncoding.QUOTED

    msg = email.message_from_string("Content-TRANSFER-encoding: base64")
    assert get_encoding(msg) == EmailEncoding.BASE64


def test_encode_text():
    assert encode_text("") == ""
    assert encode_text("ascii") == "ascii"
    assert encode_text("ascii", EmailEncoding.BASE64) == "YXNjaWk="
    assert encode_text("ascii", EmailEncoding.QUOTED) == "ascii"

    assert encode_text("mèo méo") == "mèo méo"
    assert encode_text("mèo méo", EmailEncoding.BASE64) == "bcOobyBtw6lv"
    assert encode_text("mèo méo", EmailEncoding.QUOTED) == "m=C3=A8o m=C3=A9o"


def test_decode_text():
    assert decode_text("") == ""
    assert decode_text("ascii") == "ascii"

    assert (
        decode_text(encode_text("ascii", EmailEncoding.BASE64), EmailEncoding.BASE64)
        == "ascii"
    )
    assert (
        decode_text(
            encode_text("mèo méo 🇪🇺", EmailEncoding.BASE64), EmailEncoding.BASE64
        )
        == "mèo méo 🇪🇺"
    )

    assert (
        decode_text(encode_text("ascii", EmailEncoding.QUOTED), EmailEncoding.QUOTED)
        == "ascii"
    )
    assert (
        decode_text(
            encode_text("mèo méo 🇪🇺", EmailEncoding.QUOTED), EmailEncoding.QUOTED
        )
        == "mèo méo 🇪🇺"
    )


def test_should_disable(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()

    assert not should_disable(alias)[0]

    # create a lot of bounce on this alias
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email="rep@sl.local",
        commit=True,
    )
    for _ in range(20):
        EmailLog.create(
            user_id=user.id,
            contact_id=contact.id,
            alias_id=contact.alias_id,
            commit=True,
            bounced=True,
        )

    assert should_disable(alias)[0]

    # should not affect another alias
    alias2 = Alias.create_new_random(user)
    Session.commit()
    assert not should_disable(alias2)[0]


def test_should_disable_bounces_every_day(flask_client):
    """if an alias has bounces every day at least 9 days in the last 10 days, disable alias"""
    user = login(flask_client)
    alias = Alias.create_new_random(user)
    Session.commit()

    assert not should_disable(alias)[0]

    # create a lot of bounce on this alias
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email="rep@sl.local",
        commit=True,
    )
    for i in range(9):
        EmailLog.create(
            user_id=user.id,
            contact_id=contact.id,
            alias_id=contact.alias_id,
            commit=True,
            bounced=True,
            created_at=arrow.now().shift(days=-i),
        )

    assert should_disable(alias)[0]


def test_should_disable_bounces_account(flask_client):
    """if an account has more than 10 bounces every day for at least 5 days in the last 10 days, disable alias"""
    user = login(flask_client)
    alias = Alias.create_new_random(user)

    Session.commit()

    # create a lot of bounces on alias
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email="rep@sl.local",
        commit=True,
    )

    for day in range(5):
        for _ in range(11):
            EmailLog.create(
                user_id=user.id,
                contact_id=contact.id,
                alias_id=contact.alias_id,
                commit=True,
                bounced=True,
                created_at=arrow.now().shift(days=-day),
            )

    alias2 = Alias.create_new_random(user)
    assert should_disable(alias2)[0]


def test_should_disable_bounce_consecutive_days(flask_client):
    user = login(flask_client)
    alias = Alias.create_new_random(user)
    Session.commit()

    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email="rep@sl.local",
        commit=True,
    )

    # create 6 bounce on this alias in the last 24h: alias is not disabled
    for _ in range(6):
        EmailLog.create(
            user_id=user.id,
            contact_id=contact.id,
            alias_id=contact.alias_id,
            commit=True,
            bounced=True,
        )
    assert not should_disable(alias)[0]

    # create +10 bounces in the last 7 days: alias should be disabled
    for _ in range(11):
        EmailLog.create(
            user_id=user.id,
            contact_id=contact.id,
            alias_id=contact.alias_id,
            commit=True,
            bounced=True,
            created_at=arrow.now().shift(days=-3),
        )
    assert should_disable(alias)[0]


def test_parse_id_from_bounce():
    assert parse_id_from_bounce("bounces+1234+@local") == 1234
    assert parse_id_from_bounce("anything+1234+@local") == 1234


def test_get_queue_id():
    msg = email.message_from_string(
        "Received: from mail-wr1-x434.google.com (mail-wr1-x434.google.com [IPv6:2a00:1450:4864:20::434])\r\n\t(using TLSv1.3 with cipher TLS_AES_128_GCM_SHA256 (128/128 bits))\r\n\t(No client certificate requested)\r\n\tby mx1.simplelogin.co (Postfix) with ESMTPS id 4FxQmw1DXdz2vK2\r\n\tfor <jglfdjgld@alias.com>; Fri,  4 Jun 2021 14:55:43 +0000 (UTC)"
    )

    assert get_queue_id(msg) == "4FxQmw1DXdz2vK2"


def test_get_queue_id_from_double_header():
    msg = load_eml_file("double_queue_id_header.eml")
    assert get_queue_id(msg) == "6D8C13F069"


def test_should_ignore_bounce(flask_client):
    assert not should_ignore_bounce("not-exist")

    IgnoreBounceSender.create(mail_from="to-ignore@example.com")
    assert should_ignore_bounce("to-ignore@example.com")


def test_get_header_unicode():
    assert get_header_unicode("ab@cd.com") == "ab@cd.com"
    assert get_header_unicode("=?utf-8?B?w6nDqQ==?=@example.com") == "éé@example.com"


def test_get_orig_message_from_bounce():
    with open(os.path.join(ROOT_DIR, "local_data", "email_tests", "bounce.eml")) as f:
        bounce_report = email.message_from_file(f)

    orig_msg = get_orig_message_from_bounce(bounce_report)
    assert orig_msg["X-SimpleLogin-Type"] == "Forward"
    assert orig_msg["X-SimpleLogin-Envelope-From"] == "sender@gmail.com"


def test_get_mailbox_bounce_info():
    with open(os.path.join(ROOT_DIR, "local_data", "email_tests", "bounce.eml")) as f:
        bounce_report = email.message_from_file(f)

    orig_msg = get_mailbox_bounce_info(bounce_report)
    assert orig_msg["Final-Recipient"] == "rfc822; not-existing@gmail.com"
    assert orig_msg["Original-Recipient"] == "rfc822;not-existing@gmail.com"


def test_is_invalid_mailbox_domain(flask_client):
    domain = random_domain()
    InvalidMailboxDomain.create(domain=domain, commit=True)

    assert is_invalid_mailbox_domain(domain)
    assert is_invalid_mailbox_domain(f"sub.{domain}")
    assert is_invalid_mailbox_domain(f"sub1.sub2.{domain}")

    assert not is_invalid_mailbox_domain("xy.zt")


@pytest.mark.parametrize("object_id", [10**i for i in range(0, 5)])
def test_generate_verp_email(object_id):
    generated_email = generate_verp_email(
        VerpType.bounce_forward, object_id, "somewhere.net"
    )
    info = get_verp_info_from_email(generated_email.lower())
    assert info[0] == VerpType.bounce_forward
    assert info[1] == object_id


def test_generate_verp_email_forward_reply_phase():
    """make sure the verp type is taken into account in verp generation"""
    for phase in [
        VerpType.bounce_forward,
        VerpType.bounce_reply,
        VerpType.transactional,
    ]:
        verp = generate_verp_email(phase, 100)
        verp_info = get_verp_info_from_email(verp)
        assert verp_info[0] == phase
        assert verp_info[1] == 100


def test_add_header_multipart_with_invalid_part():
    msg = load_eml_file("multipart_alternative.eml")
    parts = msg.get_payload() + ["invalid"]
    msg.set_payload(parts)
    msg = add_header(msg, "INJECT", "INJECT")
    for i, part in enumerate(msg.get_payload()):
        if i < 2:
            assert part.get_payload().index("INJECT") > -1
        else:
            assert part == "invalid"


def test_sl_formataddr():
    # when the name part (first element in the tuple) is empty, formataddr() returns a Header
    # this makes sure sl_formataddr always returns str
    assert sl_formataddr(("", "a@b.c")) == "a@b.c"

    assert sl_formataddr(("é", "è@ç.à")) == "=?utf-8?b?w6k=?= <è@ç.à>"
    # test that the same name-address can't be handled by the built-in formataddr
    with pytest.raises(UnicodeEncodeError):
        formataddr(("é", "è@ç.à"))

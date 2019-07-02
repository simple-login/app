"""POC on how to send email through postfix directly
TODO: need to improve email score before using this
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

fromaddr = "hello@u.sl.meo.ovh"
toaddr = "test-7hxfo@mail-tester.com"

# alternative is necessary so email client will display html version first, then use plain one as fall-back
msg = MIMEMultipart("alternative")

msg["From"] = fromaddr
msg["To"] = toaddr
msg["Subject"] = "test subject 2"

msg.attach(MIMEText("test plain body", "plain"))
msg.attach(
    MIMEText(
        """
<html>
<body>
<b>Test body</b>
</body>
</html>""",
        "html",
    )
)

with smtplib.SMTP(host="localhost") as server:
    server.sendmail(fromaddr, toaddr, msg.as_string())

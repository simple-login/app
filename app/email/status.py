# region 2** status
E200 = "250 Message accepted for delivery"
E201 = "250 SL E201"
E202 = "250 Unsubscribe request accepted"
E203 = "250 SL E203 email can't be sent from a reverse-alias"
E204 = "250 SL E204 ignore"
E205 = "250 SL E205 bounce handled"
# out-of-office status
E206 = "250 SL E206 Out of office"

# if mail_from is a IgnoreBounceSender, no need to send back a bounce report
E207 = "250 SL E207 No bounce report"

E208 = "250 SL E208 Hotmail complaint handled"

E209 = "250 SL E209 Email Loop"

E210 = "250 SL E210 Yahoo complaint handled"
E211 = "250 SL E211 Bounce Forward phase handled"
E212 = "250 SL E212 Bounce Reply phase handled"
E213 = "250 SL E213 Unknown email ignored"
E214 = "250 SL E214 Unauthorized for using reverse alias"
E215 = "250 SL E215 Handled dmarc policy"
E216 = "250 SL E216 Handled spf policy"

# endregion

# region 4** errors
# E401 = "421 SL E401 Retry later"
E402 = "421 SL E402 Encryption failed - Retry later"
# E403 = "421 SL E403 Retry later"
E404 = "421 SL E404 Unexpected error - Retry later"
E405 = "421 SL E405 Mailbox domain problem - Retry later"
E407 = "421 SL E407 Retry later"
# endregion

# region 5** errors
E501 = "550 SL E501"
E502 = "550 SL E502 Email not exist"
E503 = "550 SL E503"
E504 = "550 SL E504 Account disabled"
E505 = "550 SL E505"
E506 = "550 SL E506 Email detected as spam"
E507 = "550 SL E507 Wrongly formatted subject"
E508 = "550 SL E508 Email not exist"
E509 = "550 SL E509 unauthorized"
E510 = "550 SL E510 so such user"
E511 = "550 SL E511 unsubscribe error"
E512 = "550 SL E512 No such email log"
E514 = "550 SL E514 Email sent to noreply address"
E515 = "550 SL E515 Email not exist"
E516 = "550 SL E516 invalid mailbox"
E517 = "550 SL E517 unverified mailbox"
E518 = "550 SL E518 Disabled mailbox"
E519 = "550 SL E519 Email detected as spam"
E521 = "550 SL E521 Cannot reach mailbox"
E522 = (
    "550 SL E522 The user you are trying to contact is receiving mail "
    "at a rate that prevents additional messages from being delivered."
)
E523 = "550 SL E523 Unknown error"
E524 = "550 SL E524 Wrong use of reverse-alias"
# endregion

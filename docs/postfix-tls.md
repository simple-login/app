In case your Postfix server is on another server, it's recommended to enable TLS on Postfix submission to
secure the connection between SimpleLogin email handler and Postfix.

This can be enabled by adding those lines at the end of `/etc/postfix/master.cf`

```
submission inet n       -       y       -       -       smtpd
  -o syslog_name=postfix/submission
  -o smtpd_tls_security_level=encrypt
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_tls_auth_only=yes
```

Make sure to set the `POSTFIX_SUBMISSION_TLS` variable to `true` in the SimpleLogin `simplelogin.env` file.


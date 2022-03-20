# Using Gmail as SMTP relay to send email from SimpleLogin

###### port 25 blocked by ISP...?

> you can use postfix with a Gmail SMTP relay... So Postfix will send on port 587.

## How to:

- create a Gmail account
- set MFA
- create an app password

- update firewall's rules for port 587

- update Postfix conf:

=> nano /etc/postfix/master.cf
```
...
# ==========================================================================
# service type  private unpriv  chroot  wakeup  maxproc command + args
#               (yes)   (yes)   (no)    (never) (100)
# ==========================================================================
smtp      inet  n       -       y       -       -       smtpd
#smtp      inet  n       -       y       -       1       postscreen
#smtpd     pass  -       -       y       -       -       smtpd
#dnsblog   unix  -       -       y       -       0       dnsblog
#tlsproxy  unix  -       -       y       -       0       tlsproxy
submission inet n       -       y       -       -       smtpd
  -o syslog_name=postfix/submission
  -o smtpd_tls_security_level=encrypt
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_tls_auth_only=yes
#  -o smtpd_reject_unlisted_recipient=no
#  -o smtpd_client_restrictions=$mua_client_restrictions
#  -o smtpd_helo_restrictions=$mua_helo_restrictions
...
```
=> nano /etc/postfix/sasl_passwd
```
[smtp.gmail.com]:587 email_created@gmail.com:app_password_created
```
=> postmap /etc/postfix/sasl_passwd

=> chmod 600 /etc/postfix/sasl_passwd

=> nano /etc/postfix/main.cf
```
# POSTFIX config file, adapted for SimpleLogin
smtpd_banner = $myhostname ESMTP $mail_name (Ubuntu)
biff = no

# appending .domain is the MUA's job.
append_dot_mydomain = no

# Uncomment the next line to generate "delayed mail" warnings
#delay_warning_time = 4h

readme_directory = no

# See http://www.postfix.org/COMPATIBILITY_README.html -- default to 2 on
# fresh installs.
compatibility_level = 2

# TLS parameters
smtpd_tls_cert_file=/etc/letsencrypt/live/app.mydomain.com/fullchain.pem
smtpd_tls_key_file=/etc/letsencrypt/live/app.mydomain.com/privkey.pem
smtpd_tls_session_cache_database = btree:${data_directory}/smtpd_scache
smtp_tls_session_cache_database = btree:${data_directory}/smtp_scache
smtp_tls_security_level = may
smtpd_tls_security_level = may

# See /usr/share/doc/postfix/TLS_README.gz in the postfix-doc package for
# information on enabling SSL in the smtp client.

alias_maps = hash:/etc/aliases
mynetworks = 127.0.0.0/8 [::ffff:127.0.0.0]/104 [::1]/128 10.0.0.0/24

# Set your domain here
mydestination = localhost.localdomain, localhost
myhostname = app.mydomain.com
mydomain = mydomain.com
myorigin = /etc/mailname
relay_domains = pgsql:/etc/postfix/pgsql-relay-domains.cf
transport_maps = pgsql:/etc/postfix/pgsql-transport-maps.cf

# HELO restrictions
smtpd_delay_reject = yes
smtpd_helo_required = yes
smtpd_helo_restrictions =
    permit_mynetworks,
    reject_non_fqdn_helo_hostname,
    reject_invalid_helo_hostname,
    permit

# Sender restrictions:
smtpd_sender_restrictions =
    permit_mynetworks,
    reject_non_fqdn_sender,
    reject_unknown_sender_domain,
    permit

# Recipient restrictions:
smtpd_recipient_restrictions =
   reject_unauth_pipelining,
   reject_non_fqdn_recipient,
   reject_unknown_recipient_domain,
   permit_mynetworks,
   reject_unauth_destination,
   reject_rbl_client zen.spamhaus.org,
   reject_rbl_client bl.spamcop.net,
   permit

# Enfore SPF
body_checks = pcre:/etc/postfix/body_checks.pcre
smtpd_client_restrictions = pcre:/etc/postfix/client_headers.pcre

# Postfix conf
mailbox_size_limit = 10000000000
recipient_delimiter = -
inet_interfaces = all
inet_protocols = ipv4

# Relay Gmail
smtp_sasl_auth_enable = yes
smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd
smtp_sasl_security_options = noanonymous
smtp_sasl_tls_security_options = noanonymous
header_size_limit = 4096000
smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt
relayhost = [smtp.gmail.com]:587
```
>cat /etc/hosts
>
>127.0.0.1       localhost.localdomain   localhost

- restart Postfix:

=> systemctl reload postfix

=> service postfix restart

- update SimpleLogin conf:

=> nano /simplelogin.env
```
# WebApp URL
URL=http://app.mydomain.com

# domain used to create alias
EMAIL_DOMAIN=mydomaine.com

# transactional email is sent from this email address
SUPPORT_EMAIL=support@mydomain.com

# custom domain needs to point to these MX servers
EMAIL_SERVERS_WITH_PRIORITY=[(10, "app.mydomain.com.")]

# By default, new aliases must end with ".{random_word}". This is to avoid a person taking all "nice" aliases.
# this option doesn't make sense in self-hosted. Set this variable to disable this option.
DISABLE_ALIAS_SUFFIX=1

# the DKIM private key used to compute DKIM-Signature
DKIM_PRIVATE_KEY_PATH=/dkim.key

# DB Connection
DB_URI=postgresql://mysqluser:mysqlpassword@sl-db:5432/simplelogin

FLASK_SECRET=SomeThing_Secret

GNUPGHOME=/sl/pgp

LOCAL_FILE_UPLOAD=1

# Postfix 587 TLS
POSTFIX_PORT=587

POSTFIX_SUBMISSION_TLS=true

# Enforce SPF
ENFORCE_SPF=true

```
- restart SL-Mail:

=> docker restart sl-email

=> reboot

> for debug:
>
> view system logs => tail -f /var/log/syslog
>
> view postfix logs => tail -f /var/log/mail.log
>
> view postfix queue => mailq
>
> delete postfix queue => postsuper -d ALL

;-)

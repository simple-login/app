Some email services like Gmail, Proton Mail, etc don't have a strict SPF record (`-all`) to support the "classic" email forwarding
that is usually used for group mailing list. In this scenario, an email is sent to a group is forwarded as-is,
breaking therefore the SPF.

A malicious hacker could use this security fail to impersonate your alias via the reverse-alias. This rarely happens
as the reverse-alias is generated randomly and is unique for each sender.

However if you want to prevent this kind of attack, you can enforce the SPF policy even if your mailbox uses a "soft" policy.

1) Install `postfix-pcre`

```bash
apt install -y postfix-pcre
```

2) Add `/etc/postfix/body_checks.pcre` file with the following content

```
/^X-SimpleLogin-Client-IP:/    IGNORE
```

3) Add `/etc/postfix/client_headers.pcre` with the following content

```
/^([0-9a-f:.]+)$/ prepend X-SimpleLogin-Client-IP: $1
```

4) Add the following lines to your Postfix config file at `/etc/postfix/main.cf`

```
body_checks = pcre:/etc/postfix/body_checks.pcre
smtpd_client_restrictions = pcre:/etc/postfix/client_headers.pcre
```

5) Enable `ENFORCE_SPF` in your SimpleLogin config file

```
ENFORCE_SPF=true
```

6) Restart Postfix

```bash
systemctl restart postfix
```

7) Restart SimpleLogin mail handler

```bash
sudo docker restart sl-email
```

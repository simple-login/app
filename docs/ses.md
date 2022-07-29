Contribution from https://github.com/havedill/

## Integrating with Amazon SES

If you're self hosting, here is the method I used to route emails through Amazon's SES service.

For me, when hosting on AWS the public IP is widely blacklisted for abuse. If you have an SES account, you are whitelisted, use TLS, and amazon creates the DKIM records.

First, I modify the postfix inet protocols to only route via IPv4: in `/etc/postfix/main.cf`, change `inet_protocols = ipv4`

### Amazon Simple Email Service Console:

First, verify your domain with SES, and check off "Generate DKIM Records".

<img src=https://i.imgur.com/9KeIlhA.png>

I use Route53, so pressing the Use Route53 button will automatically generate my DNS values. If you do not use Route53, you will have to create them on your DNS provider.

If you do choose route53, this is what generating the record sets looks like
<img src=https://i.imgur.com/8FSHehx.png>

Now, in SES we need to generate SMTP Credentials to use. Go to the SMTP settings tab, and create credentails. Also note your server name, port, etc.

<img src=https://i.imgur.com/FcFjrCO.png>

Now on your server, run the following (Updating the SMTP DNS address to match what you see in the SMTP settings tab of SES)
```
sudo postconf -e "relayhost = [email-smtp.us-east-1.amazonaws.com]:587" \
"smtp_sasl_auth_enable = yes" \
"smtp_sasl_security_options = noanonymous" \
"smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd" \
"smtp_use_tls = yes" \
"smtp_tls_security_level = may" \
"smtp_tls_note_starttls_offer = yes"
```

Now let's create `/etc/postfix/sasl_passwd` and inside put your SMTP Setting values;
`[email-smtp.us-east-1.amazonaws.com]:587 SMTPUSERNAME:SMTPPASSWORD`

Create a hashmap with `sudo postmap hash:/etc/postfix/sasl_passwd`

Secure the files (optional but recommended)
```
sudo chown root:root /etc/postfix/sasl_passwd /etc/postfix/sasl_passwd.db
sudo chmod 0600 /etc/postfix/sasl_passwd /etc/postfix/sasl_passwd.db
```

For Ubuntu, we point postfix to the CA Certs;

```bash
sudo postconf -e 'smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt'
```

Also make sure that Postfix is able to authenticate successfully by installing the SASL package:

```bash
sudo apt install libsasl2-modules
```

Then restart postfix

```bash
sudo systemctl restart postfix
```

and you should see the mail in `/var/log/mail.log` and in your alias emails routed through Amazons servers!

<img src=https://i.imgur.com/0qLiqmH.png>

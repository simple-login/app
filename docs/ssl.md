# SSL, HTTPS, HSTS and additional security measures

It's highly recommended to enable SSL/TLS on your server, both for the web app and email server.

## Using Certbot to get a certificate

This doc will use https://letsencrypt.org to get a free SSL certificate for app.mydomain.com that's used by both Postfix and Nginx. Let's Encrypt provides Certbot, a tool to obtain and renew SSL certificates.

To install Certbot, please follow instructions on https://certbot.eff.org

Then obtain a certificate for Nginx, use the following command. You'd need to provide an email so Let's Encrypt can send you notifications when your domain is about to expire.

```bash
sudo certbot --nginx
```

After this step, you should see some "managed by Certbot" lines in `/etc/nginx/sites-enabled/simplelogin`

### Securing Postfix

Now let's use the new certificate for our Postfix.

Replace these lines in /etc/postfix/main.cf

```
smtpd_tls_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem
smtpd_tls_key_file=/etc/ssl/private/ssl-cert-snakeoil.key
```

with

```
smtpd_tls_cert_file = /etc/letsencrypt/live/app.mydomain.com/fullchain.pem
smtpd_tls_key_file = /etc/letsencrypt/live/app.mydomain.com/privkey.pem
```

Make sure to replace app.mydomain.com with your own domain.

### Updating `simplelogin.env`

Make sure to change the `URL` in `simplelogin.env` to `https://app.mydomain.com`, otherwise not all page assets will load securely, and some functionality (e.g. Webauthn) will break.
You will need to reload the docker containers for this to take effect.

## HTTP Strict Transport Security (HSTS)

HSTS is an extra step you can take to protect your web app from certain man-in-the-middle attacks. It does this by specifying an amount of time (usually a really long one) for which you should only accept HTTPS connections, not HTTP ones. Because of this **you should only enable HSTS once you know HTTPS is working correctly**, as otherwise you may find your browser blocking you from accessing your own web app.

To enable HSTS, add the following line to the `server` block of the Nginx configuration file:

```
add_header Strict-Transport-Security "max-age: 31536000; includeSubDomains" always;
```

(The `max-age` is the time in seconds to not permit a HTTP connection, in this case it's one year.)

Now, reload Nginx:

```bash
sudo systemctl reload nginx
```

## Additional security measures

For additional security, we recommend you take some extra steps.

### Enable Certificate Authority Authorization (CAA)

[Certificate Authority Authorization](https://letsencrypt.org/docs/caa/) is a step you can take to restrict the list of certificate authorities that are allowed to issue certificates for your domains.

Use [SSLMate’s CAA Record Generator](https://sslmate.com/caa/) to create a **CAA record** with the following configuration:

- `flags`: `0`
- `tag`: `issue`
- `value`: `"letsencrypt.org"`

To verify if the DNS works, the following command

```bash
dig @1.1.1.1 mydomain.com caa
```

should return:

```
mydomain.com.	3600	IN	CAA	0 issue "letsencrypt.org"
```

### SMTP MTA Strict Transport Security (MTA-STS)

[MTA-STS](https://datatracker.ietf.org/doc/html/rfc8461) is an extra step you can take to broadcast the ability of your instance to receive and, optionally enforce, TSL-secure SMTP connections to protect email traffic.

Enabling MTA-STS requires you serve a specific file from subdomain `mta-sts.domain.com` on a well-known route.

Create a text file `/var/www/.well-known/mta-sts.txt` with the content:

```txt
version: STSv1
mode: testing
mx: app.mydomain.com
max_age: 86400
```

It is recommended to start with `mode: testing` for starters to get time to review failure reports. Add as many `mx:` domain entries as you have matching **MX records** in your DNS configuration.

Create a **TXT record** for `_mta-sts.mydomain.com.` with the following value:

```txt
v=STSv1; id=UNIX_TIMESTAMP
```

With `UNIX_TIMESTAMP` being the current date/time.

Use the following command to generate the record:

```bash
echo "v=STSv1; id=$(date +%s)"
```

To verify if the DNS works, the following command

```bash
dig @1.1.1.1 _mta-sts.mydomain.com txt
```

should return a result similar to this one:

```
_mta-sts.mydomain.com.	3600	IN	TXT	"v=STSv1; id=1689416399"
```

Create an additional Nginx configuration in `/etc/nginx/sites-enabled/mta-sts` with the following content:

```
server {
	server_name mta-sts.mydomain.com;
	root /var/www;
	listen 80;

	location ^~ /.well-known {}
}
```

Restart Nginx with the following command:

```sh
sudo service nginx restart
```

A correct configuration of MTA-STS, however, requires that the certificate used to host the `mta-sts` subdomain matches that of the subdomain referred to by the **MX record** from the DNS. In other words, both `mta-sts.mydomain.com` and `app.mydomain.com` must share the same certificate.

The easiest way to do this is to _expand_ the certificate associated with `app.mydomain.com` to also support the `mta-sts` subdomain using the following command:

```sh
certbot --expand --nginx -d app.mydomain.com,mta-sts.mydomain.com
```

## SMTP TLS Reporting

[TLSRPT](https://datatracker.ietf.org/doc/html/rfc8460) is used by SMTP systems to report failures in establishing TLS-secure sessions as broadcast by the MTA-STS configuration.

Configuring MTA-STS in `mode: testing` as shown in the previous section gives you time to review failures from some SMTP senders.

Create a **TXT record** for `_smtp._tls.mydomain.com.` with the following value:

```txt
v=TSLRPTv1; rua=mailto:YOUR_EMAIL
```

The TLSRPT configuration at the DNS level allows SMTP senders that fail to initiate TLS-secure sessions to send reports to a particular email address.  We suggest creating a `tls-reports` alias in SimpleLogin for this purpose.

To verify if the DNS works, the following command

```bash
dig @1.1.1.1 _smtp._tls.mydomain.com txt
```

should return a result similar to this one:

```
_smtp._tls.mydomain.com.	3600	IN	TXT	"v=TSLRPTv1; rua=mailto:tls-reports@mydomain.com"
```

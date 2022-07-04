# SSL, HTTPS, and HSTS

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

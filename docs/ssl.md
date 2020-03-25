It's highly recommended to enable SSL/TLS on your server, both for the webapp and email server.

This doc will use https://letsencrypt.org to get a free SSL certificate for app.mydomain.com that's used by both Postfix and Nginx. Letsencrypt provides Certbot, a tool to obtain and renew SSL certificates.

To install Certbot, please follow instructions on https://certbot.eff.org

As of today (March 25 2020), you can install Certbot by using these commands:

```bash
sudo apt-get update
sudo apt-get install software-properties-common
sudo add-apt-repository universe
sudo add-apt-repository ppa:certbot/certbot
sudo apt-get update
sudo apt-get install certbot python-certbot-nginx
``` 

Then obtain a certificate for Nginx, use the following command. You'd need to provide an email so Letsencrypt can send you notifications when your domain is about to expire.

```bash
sudo certbot --nginx
```

After this step, you should see some Certbot lines in /etc/nginx/sites-enabled/simplelogin

Now let's use the new certificate for our Postfix.

Replace these lines in /etc/postfix/main.cf

```
smtpd_tls_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem
smtpd_tls_key_file=/etc/ssl/private/ssl-cert-snakeoil.key
```

by 

```
smtpd_tls_cert_file = /etc/letsencrypt/live/app.mydomain.com/fullchain.pem
smtpd_tls_key_file = /etc/letsencrypt/live/app.mydomain.com/privkey.pem
``` 

Make sure to replace app.mydomain.com by your domain. 
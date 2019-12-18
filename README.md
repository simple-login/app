SimpleLogin - privacy-first email alias and Single Sign-On (SSO) Identity Provider
---

https://simplelogin.io

> Yet another email forwarding service?

In some way yes ... However SimpleLogin is a bit different because:

- it's fully open-source: both the server and client code (browser extension, JS library) are open-source so anyone can freely inspect and (hopefully) improve the code.
- not just email alias: SimpleLogin is a privacy-first and developer-friendly identity provider that: a. offers privacy for users b. is simple to use for developers.
- plenty of features: custom domain, browser extension, OAuth libraries, etc.
- written in Python 🐍 😅 this is not a difference per se but hey I never found a Python email server so feel free to tweak this one if you want to use Python for handling emails.

## General Architecture

![](docs/archi.png)

SimpleLogin backend consists of 2 main components: 

- the `webapp` used by several clients: web UI (the dashboard), browser extension (Chrome & Firefox for now), OAuth clients (apps that integrate "Login with SimpleLogin" button) and mobile app (work in progress).

- the `email handler`: implements the email forwarding (i.e. alias receiveing email) and email sending (i.e. alias sending email). 

## Self hosting

### Prerequisites

- a Linux server (either a VM or dedicated server). This doc shows the setup for Ubuntu 18.04 LTS but the steps could be adapted for other popular Linux distributions. As most of components run as Docker container and Docker can be a bit heavy, having at least 2 GB of RAM is recommended. The server needs to have the port 25, 465 (email), 80, 443 (for the webapp), 22 (so you can ssh into it) open.

- a domain that you can config the DNS. It could be a subdomain. In the rest of the doc, let's say it's `mydomain.com` for the email and `app.mydomain.com` for SimpleLogin webapp. Please make sure to replace these values by your domain name.

- [Optional]: a Postgres database. If you don't want to manage and maintain a Postgres database, you can use managed services proposed by cloud providers. Otherwise this guide will show how to run a Postgres database using Docker. Database is not well-known to be run inside Docker but this is probably fine if you don't have thousands of emails to handle.

- [Optional] AWS S3, Sentry, Google/Facebook/Github developer accounts.

All the below steps, except for the DNS ones that are usually done inside your domain registrar interface, are done on your server.

### DKIM

From Wikipedia https://en.wikipedia.org/wiki/DomainKeys_Identified_Mail

> DomainKeys Identified Mail (DKIM) is an email authentication method designed to detect forged sender addresses in emails (email spoofing), a technique often used in phishing and email spam.

Setting up DKIM is highly recommended to reduce the chance your emails ending up in Spam folder.

First you need to generate a private and public key for DKIM:

```bash
openssl genrsa -out dkim.key 1024
openssl rsa -in dkim.key -pubout -out dkim.pub.key
```

You will need the files `dkim.key` and `dkim.pub.key` for the next steps.

For email gurus, we have chosen 1024 key length instead of 2048 for DNS simplicty as some registrars don't play well with long TXT record.

### DNS

Please note that DNS changes could take up to 24 hours to propagate. In practice, it's a lot faster though (~1 minute or so in our test).

#### MX record
Create a **MX record** that points `mydomain.com` to `app.mydomain.com` with priority 10.

To verify if the DNS works, `dig mydomain.com mx` should contain the following in the result. 

```
mydomain.com.	3600	IN	MX	10 app.mydomain.com.
```

#### A record
An **A record** that points `app.mydomain.com` to your server IP. To verify, `dig app.mydomain.com a` should return your server IP.

#### DKIM
Set up DKIM by adding a TXT record for `dkim._domainkey.mydomain.com` with the following value:

```
v=DKIM1; k=rsa; p=public_key
```

with the `public_key` being your `dkim.pub.key` but
- remove the `-----BEGIN PUBLIC KEY-----` and `-----END PUBLIC KEY-----`
- join all the lines on a single line.

For ex, if your `dkim.pub.key` is 

```
-----BEGIN PUBLIC KEY-----
ab
cd
ef
gh
-----END PUBLIC KEY-----
```

then the `public_key` would be `abcdefgh`.

To verify, `dig dkim._domainkey.mydomain.com txt` should return the above value.

#### SPF

From Wikipedia https://en.wikipedia.org/wiki/Sender_Policy_Framework

> Sender Policy Framework (SPF) is an email authentication method designed to detect forging sender addresses during the delivery of the email

Similar to DKIM, setting up SPF is highly recommended. 
Add a TXT record for `mydomain.com` with the value `v=spf1 mx -all`. What it means is only your server can send email with `@mydomain.com` domain. To verify, you can use `dig mydomain.com txt`

#### DMARC (optional) TODO

### Docker

Now the boring DNS stuffs are done, let's do something more fun!

Please follow the steps on [Docker CE for Ubuntu](https://docs.docker.com/v17.12/install/linux/docker-ce/ubuntu/) to install Docker on the server. 

Tips: if you want to run Docker without the `sudo` prefix, add your account to `docker` group:

```bash
sudo usermod -a -G docker $USER
```

### Prepare the Docker network

This Docker network will be used by the other Docker containers run in the next steps.
Later, we will setup Postfix to authorize this network.

```bash
docker network create -d bridge \
    --subnet=1.1.1.0/24 \
    --gateway=1.1.1.1 \
    sl-network
```

### Postgres

This sections show how to run a Postgres database using Docker. At the end of this section, you will have a database username and password that're going to be used in the next steps.

If you already have a Postgres database, you can skip this section and just copy the database username/password.

Run a postgres Docker container. Make sure to replace `myuser` and `mypassword` by something more secret 😎.

```bash
docker run -d \
    --name sl-db \
    -e POSTGRES_PASSWORD=mypassword \
    -e POSTGRES_USER=myuser \
    -e POSTGRES_DB=simplelogin \
    -p 5432:5432 \
    --network="sl-network" \
    postgres
```

To test if the database runs correctly, run `docker exec -it sl-db psql -U myuser simplelogin`, you should be logged into postgres console.

### Postfix

Install `postfix` and `postfix-pgsql`. The latter is used to connect Postfix and Postgres database in the next steps.

```bash
sudo apt-get install -y postfix postfix-pgsql
```

Choose "Internet Site" in Postfix installation window then keep using the proposed value as *System mail name* in the next window. 

Run the following commands to setup Postfix. Make sure to replace `mydomain.com` by your domain.

```bash
sudo postconf -e 'myhostname = app.mydomain.com'
sudo postconf -e 'mydomain = mydomain.com'
sudo postconf -e 'myorigin = mydomain.com'
sudo postconf -e 'mydestination = localhost'

sudo postconf -e 'mynetworks = 127.0.0.0/8 [::ffff:127.0.0.0]/104 [::1]/128 1.1.1.0/24'

sudo postconf -e 'relay_domains = pgsql:/etc/postfix/pgsql-relay-domains.cf'
sudo postconf -e 'transport_maps = pgsql:/etc/postfix/pgsql-transport-maps.cf'
```


Create the `relay-domains` file at `/etc/postfix/pgsql-relay-domains.cf` and put the following content. Make sure to replace `user` and `password` by your Postgres username and password and `mydomain.com` by your domain.

```
# postgres config
hosts = localhost
user = myuser
password = mypassword
dbname = simplelogin

query = SELECT domain FROM custom_domain WHERE domain='%s' AND verified=true UNION SELECT '%s' WHERE '%s' = 'mydomain.com' LIMIT 1;
```

Create the `transport-maps` file at `/etc/postfix/pgsql-transport-maps.cf` and put the following lines. Make sure to replace `user` and `password` by your Postgres username and password and `mydomain.com` by your domain.


```
# postgres config
hosts = localhost
user = myuser
password = mypassword
dbname = simplelogin

# forward to smtp:127.0.0.1:20381 for custom domain AND email domain
query = SELECT 'smtp:127.0.0.1:20381' FROM custom_domain WHERE domain = '%s' AND verified=true UNION SELECT 'smtp:127.0.0.1:20381' WHERE '%s' = 'mydomain.com' LIMIT 1;
```

Finally restart Postfix

> sudo systemctl restart postfix

### Run SimpleLogin Docker containers

To run the server, you would need a config file. Please have a look at [](./.env.example) for an example to create one. Some parameters are optional and are commented out by default. Some have "dummy" values, fill them up if you want to enable these features (Paddle, AWS). 

Let's put your config file at `~/simplelogin.env`.

Make sure to update the following variables

```.env
# Server url
URL=http://app.mydomain.com
EMAIL_DOMAIN=mydomain.com
SUPPORT_EMAIL=support@mydomain.com
EMAIL_SERVERS_WITH_PRIORITY=[(10, "app.mydomain.com.")]
DKIM_PRIVATE_KEY_PATH=/dkim.key

# optional, to have more choices for random alias.
WORDS_FILE_PATH=local_data/words_alpha.txt
```


Before running the webapp, you need to prepare the database by running the migration

```bash
docker run \
    --name sl-migration \
    -e CONFIG=/simplelogin.env \
    -v $(pwd)/dkim.key:/dkim.key \
    -v $(pwd)/simplelogin.env:/simplelogin.env \
    --network="sl-network" \
    simplelogin/app flask db upgrade
```

This command could take a while to download the `simplelogin/app` docker image.

Now it's time to run the webapp container!

```bash
docker run -d \
    --name sl-app \
    -e CONFIG=/simplelogin.env \
    -v $(pwd)/simplelogin.env:/simplelogin.env \
    -v $(pwd)/dkim.key:/dkim.key \
    -p 7777:7777 \
    --network="sl-network" \
    simplelogin/app
```

Next run the Mail Handler

```bash
docker run -d \
    --name sl-email \
    -e CONFIG=/simplelogin.env \
    -v $(pwd)/simplelogin.env:/simplelogin.env \
    -v $(pwd)/dkim.key:/dkim.key \
    -p 20381:20381 \
    --network="sl-network" \
    simplelogin/app python email_handler.py
```

[Optional] If you want to run the cronjob:

```bash
docker run -d \
    --name sl-cron \
    -e CONFIG=/simplelogin.env \
    -v $(pwd)/simplelogin.env:/simplelogin.env \
    -v $(pwd)/dkim.key:/dkim.key \
    --network="sl-network" \
    simplelogin/app yacron -c /code/crontab.yml
```

### Nginx

Install Nginx

```bash
sudo apt-get install -y nginx
```

Then create `/etc/nginx/sites-enabled/simplelogin` with the following lines:

```
server {
    server_name  app.mydomain.com;

    location / {
        proxy_pass http://localhost:7777;
    }
}
```

Reload nginx with 

```bash
sudo systemctl reload nginx
```

At this step, you should also setup the SSL for Nginx. [Certbot](https://certbot.eff.org/lets-encrypt/ubuntuxenial-nginx) can be a good option if you want a free SSL certificate.

### Enjoy!

If all the steps are successful, open http://app.mydomain.com/ and create your first account! 

## Contributing

To run the code locally, please create a local setting file based on `.env.example`:

```
cp .env.example .env
```

Feel free to custom your `.env` file, it would be your default setting when developing locally. This file is ignored by git.

You don't need all the parameters, for ex if you don't update images to s3, then
`BUCKET`, `AWS_ACCESS_KEY_ID` can be empty or if you don't use login with Github locally, `GITHUB_CLIENT_ID` doesn't have to be filled. The `.env.example` file contains minimal requirement so that if you run:

```
python3 server.py
```

then open http://localhost:7777, you should be able to login with the following account

```
john@wick.com / password
```

## Other topics

Please go to the following pages for different topics:

- [api](docs/api.md)
- [database migration](docs/db-migration.md)
- [oauth](docs/oauth.md)






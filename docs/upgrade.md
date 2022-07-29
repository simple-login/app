Upgrading SimpleLogin usually consists of simply pulling the latest version, stop & re-run SimpleLogin containers: *sl-migration*, *sl-app* and *sl-email*. It's not necessary to restart *sl-db* as it uses Postgres image.

No emails or any data is lost in the upgrade process. The same process is by the way used by the SimpleLogin SaaS version which is deployed several times per day.

Sometimes upgrading to a major version might require running a manual migration. This is for example the case when upgrading to 2.0.0. In this case please follow the corresponding migration first before running these scripts.

If you are running versions prior to 3x, please:

1. first upgrade to 2.1.2 then
2. upgrade to the latest version which is 3.4.0

<details>
<summary>After upgrade to 3x from 2x</summary>
<p>

3x has some data structure changes that cannot be automatically upgraded from 2x.
Once you have upgraded your installation to 3x, please run the following scripts to make your data fully compatible with 3x

First connect to your SimpleLogin container shell:

```bash
docker exec -it sl-app python shell.py
```

Then copy and run this below script:

```python
from app.extensions import db
from app.models import AliasUsedOn, Contact, EmailLog

for auo in AliasUsedOn.query.all():
    auo.user_id = auo.alias.user_id
db.session.commit()

for contact in Contact.query.all():
    contact.user_id = contact.alias.user_id
db.session.commit()

for email_log in EmailLog.query.all():
    email_log.user_id = email_log.contact.user_id

db.session.commit()
```

</p>
</details>

<details>
<summary>Upgrade to 2.1.0 from 2.0.0</summary>
<p>

2.1.0 comes with PGP support. If you use PGP, please follow these steps to enable this feature:

1) In your home directory (where `dkim.key` is located), create directory to store SimpleLogin data

```bash
mkdir sl
mkdir sl/pgp # to store PGP key
mkdir sl/db # to store database
```

2) Then add this line to your config simplelogin.env file

```
GNUPGHOME=/sl/pgp # where to store PGP keys
```

Now you can follow the usual steps to upgrade SimpleLogin.

</p>
</details>

<details>
<summary>Upgrade to 2.0.0</summary>
<p>

2.0.0 comes with mailbox feature that requires running a script that puts all existing users to "full-mailbox" mode.

1) First please make sure to upgrade to 1.0.5 which is the latest version before 2.0.0.

2) Then connect to your SimpleLogin container shell:

```bash
docker exec -it sl-app python shell.py
```

3) Finally copy and run this below script:

```python
"""This ad-hoc script is to be run when upgrading from 1.0.5 to 2.0.0
"""
from app.extensions import db
from app.log import LOG
from app.models import Mailbox, Alias, User

for user in User.query.all():
    if user.default_mailbox_id:
        # already run the migration on this user
        continue

    # create a default mailbox
    default_mb = Mailbox.get_by(user_id=user.id, email=user.email)
    if not default_mb:
        LOG.d("create default mailbox for user %s", user)
        default_mb = Mailbox.create(user_id=user.id, email=user.email, verified=True)
        db.session.commit()

    # assign existing alias to this mailbox
    for gen_email in Alias.query.filter_by(user_id=user.id):
        if not gen_email.mailbox_id:
            LOG.d("Set alias  %s mailbox to default mailbox", gen_email)
            gen_email.mailbox_id = default_mb.id

    # finally set user to full_mailbox
    user.full_mailbox = True
    user.default_mailbox_id = default_mb.id
    db.session.commit()
```
</p>
</details>

## Upgrade to the latest version 3.4.0

```bash
# Pull the latest version
sudo docker pull simplelogin/app:3.4.0

# Stop SimpleLogin containers
sudo docker stop sl-email sl-migration sl-app sl-db sl-job-runner

# Make sure to remove these containers to avoid conflict
sudo docker rm -f sl-email sl-migration sl-app sl-db

# create ./sl/upload/ if not exist
mkdir -p ./sl/upload/

# Run the database container. Make sure to replace `myuser` and `mypassword`
docker run -d \
    --name sl-db \
    -e POSTGRES_PASSWORD=mypassword \
    -e POSTGRES_USER=myuser \
    -e POSTGRES_DB=simplelogin \
    -p 127.0.0.1:5432:5432 \
    -v $(pwd)/sl/db:/var/lib/postgresql/data \
    --restart always \
    --network="sl-network" \
    postgres:12.1

# Run the database migration
sudo docker run --rm \
    --name sl-migration \
    -v $(pwd)/sl:/sl \
    -v $(pwd)/sl/upload:/code/static/upload \
    -v $(pwd)/dkim.key:/dkim.key \
    -v $(pwd)/dkim.pub.key:/dkim.pub.key \
    -v $(pwd)/simplelogin.env:/code/.env \
    --network="sl-network" \
    simplelogin/app:3.4.0 flask db upgrade

# Run init data
sudo docker run --rm \
    --name sl-init \
    -v $(pwd)/sl:/sl \
    -v $(pwd)/sl/upload:/code/static/upload \
    -v $(pwd)/simplelogin.env:/code/.env \
    -v $(pwd)/dkim.key:/dkim.key \
    -v $(pwd)/dkim.pub.key:/dkim.pub.key \
    --network="sl-network" \
    simplelogin/app:3.4.0 python init_app.py

# Run the webapp container
sudo docker run -d \
    --name sl-app \
    -v $(pwd)/sl:/sl \
    -v $(pwd)/sl/upload:/code/static/upload \
    -v $(pwd)/simplelogin.env:/code/.env \
    -v $(pwd)/dkim.key:/dkim.key \
    -v $(pwd)/dkim.pub.key:/dkim.pub.key \
    -p 127.0.0.1:7777:7777 \
    --restart always \
    --network="sl-network" \
    simplelogin/app:3.4.0

# Run the email handler container
sudo docker run -d \
    --name sl-email \
    -v $(pwd)/sl:/sl \
    -v $(pwd)/sl/upload:/code/static/upload \
    -v $(pwd)/simplelogin.env:/code/.env \
    -v $(pwd)/dkim.key:/dkim.key \
    -v $(pwd)/dkim.pub.key:/dkim.pub.key \
    -p 127.0.0.1:20381:20381 \
    --restart always \
    --network="sl-network" \
    simplelogin/app:3.4.0 python email_handler.py

# Run the job runner
docker run -d \
    --name sl-job-runner \
    -v $(pwd)/sl:/sl \
    -v $(pwd)/sl/upload:/code/static/upload \
    -v $(pwd)/simplelogin.env:/code/.env \
    -v $(pwd)/dkim.key:/dkim.key \
    -v $(pwd)/dkim.pub.key:/dkim.pub.key \
    --restart always \
    --network="sl-network" \
    simplelogin/app:3.4.0 python job_runner.py

```


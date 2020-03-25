Upgrading SimpleLogin usually consists of simply pulling the latest version, stop & re-run SimpleLogin containers: *sl-migration*, *sl-app* and *sl-email*. It's not necessary to restart *sl-db* as it uses Postgres image.

No emails or any data is lost in the upgrade process. The same process is by the way used by the SimpleLogin SaaS version which is deployed several times per day.

Sometimes upgrading to a major version might require running a manual migration. This is for example the case when upgrading to 2.0.0. In this case please follow the corresponding migration first before running these scripts.

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


```bash
# Pull the latest version
sudo docker pull simplelogin/app:2.1.0

# Stop SimpleLogin containers
sudo docker stop sl-email sl-migration sl-app

# Make sure to remove these containers to avoid conflict
sudo docker rm -f sl-email sl-migration sl-app

# Run the database migration
sudo docker run --rm \
    --name sl-migration \
    -v $(pwd)/sl:/sl \
    -v $(pwd)/dkim.key:/dkim.key \
    -v $(pwd)/dkim.pub.key:/dkim.pub.key \
    -v $(pwd)/simplelogin.env:/code/.env \
    --network="sl-network" \
    simplelogin/app:2.1.0 flask db upgrade

# Run init data
sudo docker run --rm \
    --name sl-init \
    -v $(pwd)/sl:/sl \
    -v $(pwd)/simplelogin.env:/code/.env \
    -v $(pwd)/dkim.key:/dkim.key \
    -v $(pwd)/dkim.pub.key:/dkim.pub.key \
    -p 7777:7777 \
    --restart always \
    --network="sl-network" \
    simplelogin/app:2.1.0 python init_app.py

# Run the webapp container
sudo docker run -d \
    --name sl-app \
    -v $(pwd)/sl:/sl \
    -v $(pwd)/simplelogin.env:/code/.env \
    -v $(pwd)/dkim.key:/dkim.key \
    -v $(pwd)/dkim.pub.key:/dkim.pub.key \
    -p 7777:7777 \
    --restart always \
    --network="sl-network" \
    simplelogin/app:2.1.0

# Run the email handler container
sudo docker run -d \
    --name sl-email \
    -v $(pwd)/sl:/sl \
    -v $(pwd)/simplelogin.env:/code/.env \
    -v $(pwd)/dkim.key:/dkim.key \
    -v $(pwd)/dkim.pub.key:/dkim.pub.key \
    -p 20381:20381 \
    --restart always \
    --network="sl-network" \
    simplelogin/app:2.1.0 python email_handler.py
```


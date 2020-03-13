Upgrading SimpleLogin usually consists of simply pulling the latest version, stop & re-run SimpleLogin containers: *sl-migration*, *sl-app* and *sl-email*. It's not necessary to restart *sl-db* as it uses Postgres image.

No emails or any data is lost in the upgrade process. The same process is by the way used by the SimpleLogin SaaS version which is deployed several times per day.

Sometimes upgrading to a major version might require running a manual migration. This is for example the case when upgrading to 2.0.0.

```bash
# Pull the latest version
sudo docker pull simplelogin/app:2.0.0

# Stop SimpleLogin containers
sudo docker stop sl-email sl-migration sl-app

# Make sure to remove these containers to avoid conflict
sudo docker rm -f sl-email sl-migration sl-app

# Run the database migration
sudo docker run --rm \
    --name sl-migration \
    -v $(pwd)/dkim.key:/dkim.key \
    -v $(pwd)/dkim.pub.key:/dkim.pub.key \
    -v $(pwd)/simplelogin.env:/code/.env \
    --network="sl-network" \
    simplelogin/app:2.0.0 flask db upgrade

# Run the webapp container
sudo docker run -d \
    --name sl-app \
    -v $(pwd)/simplelogin.env:/code/.env \
    -v $(pwd)/dkim.key:/dkim.key \
    -v $(pwd)/dkim.pub.key:/dkim.pub.key \
    -p 7777:7777 \
    --restart always \
    --network="sl-network" \
    simplelogin/app:2.0.0

# Run the email handler container
sudo docker run -d \
    --name sl-email \
    -v $(pwd)/simplelogin.env:/code/.env \
    -v $(pwd)/dkim.key:/dkim.key \
    -v $(pwd)/dkim.pub.key:/dkim.pub.key \
    -p 20381:20381 \
    --restart always \
    --network="sl-network" \
    simplelogin/app:2.0.0 python email_handler.py
```


## Upgrade to 2.0.0 from 1.0.5

2.0.0 comes with mailbox feature that requires running a script that puts all existing users to "full-mailbox" mode.

Please connect to your SimpleLogin container and runs this script:

First run shell.py:

```bash
docker exec -it sl-app python shell.py
```

Then copy and run this below script:

```python
"""This ad-hoc script is to be run when upgrading from 1.0.5 to 2.0.0
"""
from app.extensions import db
from app.log import LOG
from app.models import Mailbox, GenEmail, User

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
    for gen_email in GenEmail.query.filter_by(user_id=user.id):
        if not gen_email.mailbox_id:
            LOG.d("Set alias  %s mailbox to default mailbox", gen_email)
            gen_email.mailbox_id = default_mb.id

    # finally set user to full_mailbox
    user.full_mailbox = True
    user.default_mailbox_id = default_mb.id
    db.session.commit()
```
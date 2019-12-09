## How to create new migration

The database migration is handled by `alembic`

Whenever the model changes, a new migration needs to be created

Set the database connection to use staging environment, for ex if you have a staging config at `~/config/simplelogin/staging.env`, you can do: 

> ln -sf ~/config/simplelogin/staging.env .env

Generate the migration script and make sure to review it before commit it. Sometimes (very rarely though), the migration generation can go wrong.

> flask db migrate

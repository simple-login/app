#!/bin/sh

export DB_URI=postgresql://myuser:mypassword@localhost:15432/test
echo 'drop schema public cascade; create schema public;' | psql  $DB_URI

poetry run alembic upgrade head

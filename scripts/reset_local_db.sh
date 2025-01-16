#!/bin/sh

export DB_URI=postgresql://myuser:mypassword@localhost:15432/simplelogin
echo 'drop schema public cascade; create schema public;' | psql  $DB_URI

rye run alembic upgrade head
rye run flask dummy-data

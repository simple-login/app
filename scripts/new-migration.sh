# Generate a new migration script using Docker
# To run it:
# sh scripts/new-migration.sh

container_name=sl-db-new-migration

# create a postgres database for SimpleLogin
docker rm -f ${container_name}
docker run -p 25432:5432 --name ${container_name} -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=sl -d postgres:13

# sleep a little bit for the db to be ready
sleep 3

# upgrade the DB to the latest stage and
env DB_URI=postgresql://postgres:postgres@127.0.0.1:25432/sl poetry run alembic upgrade head

# generate the migration script.
env DB_URI=postgresql://postgres:postgres@127.0.0.1:25432/sl poetry run alembic revision --autogenerate $@

# remove the db
docker rm -f ${container_name}

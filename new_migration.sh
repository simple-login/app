# Generate a new migration script using Docker
# To run it:
# sh new_migration.sh

# create a postgres database for SimpleLogin
docker rm -f sl-db
docker run -p 15432:5432 --name sl-db -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=sl -d postgres

# run run `flask db upgrade` to upgrade the DB to the latest stage and
env DB_URI=postgresql://postgres:postgres@127.0.0.1:15432/sl flask db upgrade

# finally `flask db migrate` to generate the migration script.
env DB_URI=postgresql://postgres:postgres@127.0.0.1:15432/sl flask db migrate

# remove the db
docker rm -f sl-db
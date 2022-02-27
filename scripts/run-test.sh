# Run tests

docker rm -f sl-test-db

docker run -d --name sl-test-db -e POSTGRES_PASSWORD=test -e POSTGRES_USER=test -e POSTGRES_DB=test -p 15432:5432 postgres:13

# the time the DB container starts
sleep 3

poetry run pytest

docker rm -f sl-test-db

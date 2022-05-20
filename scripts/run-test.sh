# Run tests

# Delete the test DB if it isn't properly removed
docker rm -f sl-test-db

# Create a test DB
docker run -d --name sl-test-db -e POSTGRES_PASSWORD=test -e POSTGRES_USER=test -e POSTGRES_DB=test -p 15432:5432 postgres:13

# the time for the test DB container to start
sleep 3

# migrate the DB to the latest version
CONFIG=tests/test.env poetry run alembic upgrade head

# run test
poetry run pytest -c pytest.ci.ini

# Delete the test DB
docker rm -f sl-test-db

# Install npm packages
FROM node:10.17.0-alpine AS npm
WORKDIR /code
COPY ./static/package*.json /code/static/
RUN cd /code/static && npm install

# Base build
FROM python:3.7 as base

# install poetry, "pip3 install poetry==1.1.5" doesn't work
# poetry will be available at /root/.poetry/bin/poetry
RUN curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python -

WORKDIR /code

# install dependencies
COPY poetry.lock pyproject.toml ./

RUN /root/.poetry/bin/poetry config virtualenvs.create false \
  && /root/.poetry/bin/poetry install --no-root

# copy npm packages
COPY --from=npm /code /code

# copy everything else into /code
COPY . .

# Email client image
FROM base as email-handler
CMD ["./entrypoints/email-handler-entrypoint.sh"]

# Main image
FROM base
EXPOSE 7777

CMD ["./entrypoints/webapp-entrypoint.sh"]

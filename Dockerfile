# Install npm packages
FROM node:10.17.0-alpine AS npm
WORKDIR /code
COPY ./static/package*.json /code/static/
RUN cd /code/static && npm install

# Base build
FROM python:3.7 as base

RUN pip3 install poetry==1.0.10

# install dependencies
WORKDIR /code
COPY poetry.lock pyproject.toml ./
RUN poetry config virtualenvs.create false \
  && poetry install --no-root

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

#gunicorn wsgi:app -b 0.0.0.0:7777 -w 2 --timeout 15 --log-level DEBUG
CMD ["./entrypoints/webapp-entrypoint.sh"]

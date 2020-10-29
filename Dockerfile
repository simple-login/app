# Install npm packages
FROM node:10.17.0-alpine AS npm
WORKDIR /code
COPY ./static/package*.json /code/static/
RUN cd /code/static && npm install

# Main image
# python:3.7 -> python:3.7-alpine
# https://github.com/docker-library/python/issues/431
FROM python:3.7-alpine

# install some utility packages
# apt -> apk missing/replacements:
# telnet -> busybox-extras
# gcc -> build-base
# ffi.h -> libffi-dev
# openssl/opensslv.h -> libressl-dev musl-dev
# psycopg2-binary install error -> postgresql-dev python3-dev
RUN apk update && apk add --no-cache vim busybox-extras build-base libffi-dev libressl-dev musl-dev postgresql-dev python3-dev

RUN pip3 install poetry==1.0.10

# install dependencies
WORKDIR /code
COPY poetry.lock pyproject.toml ./
RUN poetry config virtualenvs.create false \
  && poetry install

# copy npm packages
COPY --from=npm /code /code

# copy everything else into /code
COPY . .

EXPOSE 7777

#gunicorn wsgi:app -b 0.0.0.0:7777 -w 2 --timeout 15 --log-level DEBUG
CMD ["gunicorn","wsgi:app","-b","0.0.0.0:7777","-w","2","--timeout","15"]

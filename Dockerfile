# Install npm packages
FROM node:10.17.0-alpine AS npm
WORKDIR /code
COPY ./static/package*.json /code/static/
RUN cd /code/static && npm install

# Main image
FROM python:3.7

# install some utility packages
RUN apt update && apt install -y vim telnet

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

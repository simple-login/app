# Install npm packages
FROM node:10.17.0-alpine AS npm
WORKDIR /code
COPY ./static/package*.json /code/static/
RUN cd /code/static && npm install

# Main image
FROM python:3.7-slim

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE 1
# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED 1

# Install and setup poetry
RUN pip install -U pip \
    && apt-get update \
    && apt install -y curl netcat gcc python3-dev \
    && curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python - 
    # Clear apt cache
    # && apt-get clean \
    # && rm -rf /var/lib/apt/lists/*

ENV PATH="${PATH}:/root/.poetry/bin"


WORKDIR /code

# install dependencies
COPY poetry.lock pyproject.toml ./

RUN poetry config virtualenvs.create false \
  && poetry install  --no-interaction --no-ansi --no-root

# copy npm packages
COPY --from=npm /code /code

# copy everything else into /code
COPY . .

EXPOSE 7777

#gunicorn wsgi:app -b 0.0.0.0:7777 -w 2 --timeout 15 --log-level DEBUG
CMD ["gunicorn","wsgi:app","-b","0.0.0.0:7777","-w","2","--timeout","15"]

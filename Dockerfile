# Install npm packages
FROM node:10.17.0-alpine AS npm
WORKDIR /code
COPY ./static/package*.json /code/static/
RUN cd /code/static && npm install

# Main image
FROM python:3.10

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE 1
# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED 1

# Add poetry to PATH
ENV PATH="${PATH}:/root/.local/bin"

WORKDIR /code

# Copy poetry files
COPY poetry.lock pyproject.toml ./

# Install and setup poetry
RUN pip install -U pip \
    && apt-get update \
    && apt install -y curl netcat gcc python3-dev gnupg git libre2-dev \
    && curl -sSL https://install.python-poetry.org | python3 - \
    # Remove curl and netcat from the image
    && apt-get purge -y curl netcat \
    # Run poetry
    && poetry config virtualenvs.create false \
    && poetry install  --no-interaction --no-ansi --no-root \
    # Clear apt cache \
    && apt-get purge -y libre2-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# copy npm packages
COPY --from=npm /code /code

# copy everything else into /code
COPY . .

EXPOSE 7777

#gunicorn wsgi:app -b 0.0.0.0:7777 -w 2 --timeout 15 --log-level DEBUG
CMD ["gunicorn","wsgi:app","-b","0.0.0.0:7777","-w","2","--timeout","15"]

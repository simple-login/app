# Install npm packages
FROM node:10.17.0-alpine AS npm
WORKDIR /code
COPY ./static/package*.json /code/static/
RUN cd /code/static && npm ci

FROM --platform=linux/amd64 ubuntu:22.04

ARG RYE_VERSION="0.43.0"
ARG RYE_HASH="ca702c3d93fd6ec76a1a0efaaa605e10736ee79a0674d241aad1bc0fe26f7d80"

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1
# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1


WORKDIR /code

# Copy dependency files
COPY pyproject.toml requirements.lock requirements-dev.lock .python-version ./

# Install deps
RUN apt-get update \
    && apt-get install -y curl netcat-traditional gcc python3-dev gnupg git libre2-dev build-essential pkg-config cmake ninja-build bash clang \
    && curl -sSL "https://github.com/astral-sh/rye/releases/download/${RYE_VERSION}/rye-x86_64-linux.gz" > rye.gz \
    && echo "${RYE_HASH}  rye.gz" | sha256sum -c - \
    && gunzip rye.gz \
    && chmod +x rye \
    && mv rye /usr/bin/rye \
    && rye toolchain fetch `cat .python-version` \
    && rye sync --no-lock --no-dev \
    && apt-get autoremove -y \
    && apt-get purge -y curl netcat-traditional build-essential pkg-config cmake ninja-build python3-dev clang\
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy code
COPY . .

# copy npm packages
COPY --from=npm /code /code

ENV PATH="/code/.venv/bin:$PATH"
EXPOSE 7777

#gunicorn wsgi:app -b 0.0.0.0:7777 -w 2 --timeout 15 --log-level DEBUG
CMD ["gunicorn","wsgi:app","-b","0.0.0.0:7777","-w","2","--timeout","15"]

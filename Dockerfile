# Install npm packages
FROM node:10.17.0-alpine AS npm
WORKDIR /code
COPY ./static/package*.json /code/static/
RUN cd /code/static && npm ci

FROM ubuntu:22.04

ARG UV_VERSION="0.5.21"
ARG UV_HASH_x86_64="e108c300eafae22ad8e6d94519605530f18f8762eb58d2b98a617edfb5d088fc"
ARG UV_HASH_aarch64="c4cc2ec78a294378b867ebd08c5842d3ce71074c2818dc7f641422fb3bf4b2d2"
ARG TARGETARCH

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1
# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

WORKDIR /code

# Copy dependency files
COPY pyproject.toml uv.lock .python-version ./

# Install deps
RUN apt-get update \
    && apt-get install -y curl netcat-traditional gcc python3-dev gnupg git libre2-dev build-essential pkg-config cmake ninja-build bash clang \
    && if [ "$TARGETARCH" = "amd64" ]; then \
        curl -sSL "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz" > uv.tar.gz \
        && echo "${UV_HASH_x86_64}  uv.gz" | sha256sum -c - \
        && tar xf uv.tar.gz -C /tmp/ \
        && mv /tmp/uv-x86_64-unknown-linux-gnu/uv /usr/bin/uv \
        && mv /tmp/uv-x86_64-unknown-linux-gnu/uvx /usr/bin/uvx ; \
    elif [ "$TARGETARCH" = "arm64" ]; then \
        curl -sSL "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-aarch64-unknown-linux-gnu.tar.gz" > uv.tar.gz \
        && echo "${UV_HASH_aarch64}  uv.tar.gz" | sha256sum -c - \
        && tar xf uv.tar.gz -C /tmp/ \
        && mv /tmp/uv-aarch64-unknown-linux-gnu/uv /usr/bin/uv \
        && mv /tmp/uv-aarch64-unknown-linux-gnu/uvx /usr/bin/uvx ; \
    else \
        echo "compatible arch not detected" ; \
    fi \
    && rm -rf /tmp/uv* \
    && rm -f uv.tar.gz \
    && uv python install `cat .python-version` \
    && uv sync --locked \
    && apt-get autoremove -y \
    && apt-get purge -y curl netcat-traditional build-essential pkg-config cmake ninja-build python3-dev clang \
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

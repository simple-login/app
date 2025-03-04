# Install npm packages
FROM node:10.17.0-alpine AS npm
WORKDIR /code
COPY ./static/package*.json /code/static/
RUN cd /code/static && npm ci

FROM ubuntu:24.04

ARG TARGETARCH

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1
# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

WORKDIR /code

# Copy dependency files
COPY pyproject.toml uv.lock .python-version ./

# Install deps
RUN \
    echo "**** install build packages ****" && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        netcat-traditional \
        gcc \
        python3-dev \
        gnupg \
        git \
        libre2-dev \
        build-essential \
        pkg-config \
        cmake \
        ninja-build \
        bash \
        clang \
        ca-certificates && \
    curl -o /tmp/uv-installer.sh -L https://astral.sh/uv/install.sh && \
    sh /tmp/uv-installer.sh && \
    export PATH="$HOME/.local/bin:$PATH" && \
    uv python install `cat .python-version` && \
    uv sync --no-dev --no-cache && \
    echo "**** install runtime packages ****" && \
    apt-get install -y \
        gnupg \
        libre2-10 && \
    echo "**** cleanup ****" && \
    apt-get purge -y \
        curl \
        netcat-traditional \
        build-essential \
        pkg-config \
        cmake \
        ninja-build \
        python3-dev \
        clang && \
    apt-get autoremove -y && \
    apt-get autoclean -y && \
    rm -rf \
        /var/lib/apt/lists/*

# Copy code
COPY . .

# copy npm packages
COPY --from=npm /code /code

ENV PATH="/code/.venv/bin:$PATH"
EXPOSE 7777

#gunicorn wsgi:app -b 0.0.0.0:7777 -w 2 --timeout 15 --log-level DEBUG
CMD ["gunicorn","wsgi:app","-b","0.0.0.0:7777","-w","2","--timeout","15"]
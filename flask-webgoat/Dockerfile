FROM python:3.8.5-buster

# docker build --build-arg SHIFTLEFT_ACCESS_TOKEN=$SHIFTLEFT_ACCESS_TOKEN
ARG SHIFTLEFT_ACCESS_TOKEN
ARG BRANCH=master

WORKDIR /app
COPY . /app/

# Download ShiftLeft
RUN curl https://cdn.shiftleft.io/download/sl > sl && chmod a+rx sl

# Create virtual env
RUN python3 -m venv .venv \
    && . .venv/bin/activate \
    && pip install --upgrade setuptools wheel \
    && pip install -r requirements.txt

# Perform sl analysis
RUN ./sl analyze --app flask-webgoat-docker --tag branch=$BRANCH --python --cpg --beta .

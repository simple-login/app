FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       postfix postfix-pgsql postfix-pcre \
       ca-certificates gettext-base ssl-cert openssl tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY conf/ /conf/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 25: SMTP entrante  ·  587: submission (opcional)
EXPOSE 25 587

# Postfix escribe el log en stdout (maillog_file en main.cf)
ENTRYPOINT ["/entrypoint.sh"]

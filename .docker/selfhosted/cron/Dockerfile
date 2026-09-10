# Cron de mantenimiento de SimpleLogin.
#
# Parte de la imagen de la app (que debe existir ya). install.sh / manage.sh
# construyen `app` antes que `cron`. Para reconstruir a mano:
#   docker compose build app && docker compose --profile cron build
FROM simplelogin-selfhosted:local

ARG SUPERCRONIC_VERSION=v0.2.33
ADD https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64 /usr/local/bin/supercronic
RUN chmod +x /usr/local/bin/supercronic

COPY crontab /app/crontab

WORKDIR /code
CMD ["supercronic", "/app/crontab"]

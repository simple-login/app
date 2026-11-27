#!/bin/bash
set -euo pipefail

: "${POSTFIX_MYHOSTNAME:?falta POSTFIX_MYHOSTNAME}"
: "${POSTFIX_MYDOMAIN:?falta POSTFIX_MYDOMAIN}"
: "${DB_HOST:?falta DB_HOST}"
: "${DB_USER:?falta DB_USER}"
: "${DB_PASSWORD:?falta DB_PASSWORD}"
: "${DB_NAME:?falta DB_NAME}"
: "${EMAIL_HANDLER_HOST:=email}"
: "${EMAIL_HANDLER_PORT:=20381}"
: "${POSTFIX_MYNETWORKS:=127.0.0.0/8 10.42.0.0/24}"
export POSTFIX_MYHOSTNAME POSTFIX_MYDOMAIN POSTFIX_MYNETWORKS \
       DB_HOST DB_USER DB_PASSWORD DB_NAME EMAIL_HANDLER_HOST EMAIL_HANDLER_PORT

render() { envsubst "$3" < "$1" > "$2"; }

render /conf/main.cf.template /etc/postfix/main.cf \
  '${POSTFIX_MYHOSTNAME} ${POSTFIX_MYDOMAIN} ${POSTFIX_MYNETWORKS}'
render /conf/pgsql-relay-domains.cf.template /etc/postfix/pgsql-relay-domains.cf \
  '${DB_HOST} ${DB_USER} ${DB_PASSWORD} ${DB_NAME} ${POSTFIX_MYDOMAIN}'
render /conf/pgsql-transport-maps.cf.template /etc/postfix/pgsql-transport-maps.cf \
  '${DB_HOST} ${DB_USER} ${DB_PASSWORD} ${DB_NAME} ${POSTFIX_MYDOMAIN} ${EMAIL_HANDLER_HOST} ${EMAIL_HANDLER_PORT}'

chgrp postfix /etc/postfix/pgsql-*.cf
chmod 640 /etc/postfix/pgsql-*.cf
newaliases 2>/dev/null || true

# En contenedor no queremos chroot: los mapas pgsql y el resolver DNS viven fuera
# de /var/spool/postfix. Desactiva chroot para todos los servicios de master.cf.
postconf -F '*/*/chroot = n'

# Certificado autofirmado si no hay ninguno (STARTTLS funcional aunque no verificado)
if [ ! -s /etc/ssl/certs/ssl-cert-snakeoil.pem ]; then
  make-ssl-cert generate-default-snakeoil --force-overwrite 2>/dev/null || \
  openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout /etc/ssl/private/ssl-cert-snakeoil.key \
    -out /etc/ssl/certs/ssl-cert-snakeoil.pem \
    -subj "/CN=${POSTFIX_MYHOSTNAME}"
fi

# Puerto submission 587 opcional
if [ "${POSTFIX_SUBMISSION:-0}" = "1" ]; then
  postconf -M "submission/inet=submission inet n - y - - smtpd"
  postconf -P \
    "submission/inet/syslog_name=postfix/submission" \
    "submission/inet/smtpd_tls_security_level=may" \
    "submission/inet/milter_macro_daemon_name=ORIGINATING"
fi

# Relay SMTP saliente opcional (ISP que bloquea el puerto 25 saliente)
if [ -n "${RELAY_HOST:-}" ]; then
  postconf -e "relayhost=${RELAY_HOST}"
  if [ -n "${RELAY_USER:-}" ]; then
    echo "${RELAY_HOST} ${RELAY_USER}:${RELAY_PASSWORD}" > /etc/postfix/sasl_passwd
    postmap /etc/postfix/sasl_passwd
    chmod 600 /etc/postfix/sasl_passwd /etc/postfix/sasl_passwd.db
    postconf -e \
      "smtp_sasl_auth_enable=yes" \
      "smtp_sasl_password_maps=hash:/etc/postfix/sasl_passwd" \
      "smtp_sasl_security_options=noanonymous" \
      "smtp_tls_security_level=encrypt"
  fi
fi

# Espera a que PostgreSQL acepte conexiones (los mapas pgsql lo necesitan)
echo "postfix-entrypoint: esperando a ${DB_HOST}:5432 ..."
for _ in $(seq 1 30); do
  if (exec 3<>"/dev/tcp/${DB_HOST}/5432") 2>/dev/null; then exec 3>&-; break; fi
  sleep 2
done

# Postfix necesita reescribir permisos/estructura en cada arranque
postfix set-permissions 2>/dev/null || true
echo "postfix-entrypoint: arrancando Postfix para ${POSTFIX_MYDOMAIN} (mx ${POSTFIX_MYHOSTNAME})"
exec postfix start-fg

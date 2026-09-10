#!/usr/bin/env bash
#
# Entorno DEMO LOCAL de SimpleLogin — sin dominio ni DNS reales.
#
#   ./demo.sh                        # arranca la demo (webapp HTTPS + Mailpit + Postfix)
#   ./demo.sh send-test <alias>      # inyecta un correo hacia un alias y prueba el reenvío
#   ./demo.sh activate <email>       # activa una cuenta sin el email de confirmación
#   ./demo.sh make-premium <email>   # alias ilimitados
#   ./demo.sh down                   # para la demo (conserva los datos)
#   ./demo.sh destroy                # para y BORRA los datos de la demo
#   ./demo.sh logs [svc] | ps | urls
#
# Cómo funciona:
#   • traefik.me: cualquier *.traefik.me resuelve a 127.0.0.1 -> HTTPS local
#     (certificado autofirmado; un aviso del navegador la primera vez).
#   • Postfix arranca SIN publicar el :25 y con relayhost=[mailpit]:1025, así que
#     TODO el correo (activación, reenvíos de alias, respuestas) acaba en Mailpit.
#   • send-test envía un correo a postfix:25 dirigido al alias -> email_handler lo
#     reenvía a tu buzón -> Postfix -> Mailpit. Así ves el alias funcionando en local.
#
# La imagen de la app se construye desde el repo; la de Postfix desde
# ../selfhosted/postfix (compartidas con el despliegue real).
#
set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DEMO_DIR"

# helpers de logging / .env compartidos con el despliegue real
# shellcheck source=../selfhosted/lib/common.sh
source "$DEMO_DIR/../selfhosted/lib/common.sh"

DEMO_APP_HOST="${DEMO_APP_HOST:-slapp.traefik.me}"
DEMO_MAIL_HOST="${DEMO_MAIL_HOST:-slmail.traefik.me}"
CERT_DIR="$DEMO_DIR/certs"
DATA_DIR="$DEMO_DIR/data"
ENV_FILE="$DEMO_DIR/.env"
SL_ENV="$DEMO_DIR/simplelogin.env"

dc() { docker compose --project-directory "$DEMO_DIR" -f "$DEMO_DIR/docker-compose.yml" "$@"; }

rand_hex() { openssl rand -hex "${1:-32}"; }

prepare_dirs() {
  mkdir -p "$DATA_DIR"/db "$DATA_DIR"/pgp "$DATA_DIR"/upload "$DATA_DIR"/dkim "$CERT_DIR"
  chmod 700 "$DATA_DIR/pgp"
}

generate_dkim() {
  local key="$DATA_DIR/dkim/dkim.key" pub="$DATA_DIR/dkim/dkim.pub.key"
  [ -s "$key" ] && [ -s "$pub" ] && { ok "clave DKIM ya presente"; return; }
  log "generando par de claves DKIM"
  if openssl genrsa -help 2>&1 | grep -q -- '-traditional'; then
    openssl genrsa -out "$key" -traditional 1024 2>/dev/null
  else
    openssl genrsa -out "$key" 1024 2>/dev/null
  fi
  openssl rsa -in "$key" -pubout -out "$pub" 2>/dev/null
  chmod 600 "$key"
}

render_dynamic() {
  sed -e "s|__APP_HOST__|${DEMO_APP_HOST}|g" \
      -e "s|__MAIL_HOST__|${DEMO_MAIL_HOST}|g" \
      "$DEMO_DIR/traefik/dynamic.yml.template" > "$DEMO_DIR/traefik/dynamic.yml"
}

fetch_certs() {
  mkdir -p "$CERT_DIR"
  if [ -s "$CERT_DIR/fullchain.pem" ] && [ -s "$CERT_DIR/privkey.pem" ]; then
    ok "certificado de la demo ya presente"; return
  fi
  if [ -n "${DEMO_CERT_URL:-}" ] && [ -n "${DEMO_KEY_URL:-}" ] && has_cmd curl \
     && curl -fsS "$DEMO_CERT_URL" -o "$CERT_DIR/fullchain.pem" \
     && curl -fsS "$DEMO_KEY_URL"  -o "$CERT_DIR/privkey.pem"; then
    ok "certificado descargado de DEMO_CERT_URL"; return
  fi
  log "generando certificado autofirmado para *.traefik.me (el navegador pedirá aceptarlo una vez)"
  openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
    -keyout "$CERT_DIR/privkey.pem" -out "$CERT_DIR/fullchain.pem" \
    -subj "/CN=*.traefik.me" \
    -addext "subjectAltName=DNS:*.traefik.me,DNS:traefik.me"
  [ -s "$CERT_DIR/fullchain.pem" ] && [ -s "$CERT_DIR/privkey.pem" ] \
    || die "no se pudo generar el certificado autofirmado (¿openssl?)"
  ok "certificado autofirmado generado ($CERT_DIR)"
}

write_config() {
  if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" <<ENV
# Generado por demo.sh — entorno DEMO LOCAL
DB_USER=simplelogin
DB_NAME=simplelogin
DB_PASSWORD=$(rand_hex 16)
FLASK_SECRET=$(rand_hex 32)
PARTNER_API_TOKEN_SECRET=$(rand_hex 32)
DEMO_APP_HOST=${DEMO_APP_HOST}
DEMO_MAIL_HOST=${DEMO_MAIL_HOST}
ENV
    ok ".env de demo generado"
  fi
  load_env_file "$ENV_FILE"
  prepare_dirs
  generate_dkim

  cat > "$SL_ENV" <<SLENV
URL=https://${DEMO_APP_HOST}
EMAIL_DOMAIN=${DEMO_APP_HOST}
SUPPORT_EMAIL=support@${DEMO_APP_HOST}
EMAIL_SERVERS_WITH_PRIORITY=[(10, "${DEMO_APP_HOST}.")]
DISABLE_ALIAS_SUFFIX=1
DKIM_PRIVATE_KEY_PATH=/dkim.key
DB_URI=postgresql://${DB_USER}:${DB_PASSWORD}@db:5432/${DB_NAME}
FLASK_SECRET=${FLASK_SECRET}
PARTNER_API_TOKEN_SECRET=${PARTNER_API_TOKEN_SECRET}
GNUPGHOME=/sl/pgp
LOCAL_FILE_UPLOAD=1
POSTFIX_SERVER=postfix
POSTFIX_PORT=25
DISABLE_ONBOARDING=true
NAMESERVERS=1.1.1.1
ALLOWED_REDIRECT_DOMAINS=[]
SLENV
  chmod 600 "$SL_ENV"
  ok "simplelogin.env de demo generado (correo -> Postfix -> Mailpit)"
}

print_urls() {
  hr
  cat <<EOF
${C_BOLD}Demo lista${C_RESET}

  Webapp:  https://${DEMO_APP_HOST}/
  Mailpit: https://${DEMO_MAIL_HOST}/     (todo el correo)

Flujo:
  1) https://${DEMO_APP_HOST}/  -> regístrate (dominio con MX real, p.ej.
     loquesea@gmail.com — el correo va a Mailpit, no a Gmail).
  2) https://${DEMO_MAIL_HOST}/ -> pincha el enlace de activación.
     (o actívala a mano:  ./demo.sh activate loquesea@gmail.com)
  3) Crea un alias en el panel y prueba el reenvío:
       ./demo.sh send-test <alias@${DEMO_APP_HOST}>
     -> el correo reenviado aparece en Mailpit dirigido a tu buzón.

Nota: *.traefik.me resuelve a 127.0.0.1: la demo solo es accesible desde esta
máquina. Postfix no publica el :25 y relaya todo a Mailpit.
EOF
  hr
}

case "${1:-up}" in
  up)
    require_cmd docker
    step "Preparando la demo"
    write_config
    render_dynamic
    fetch_certs
    step "Base de datos"
    dc up -d db
    for _ in $(seq 1 30); do
      dc exec -T db pg_isready -U "${DB_USER}" -d "${DB_NAME}" >/dev/null 2>&1 && break
      sleep 2
    done
    dc run --rm migration
    dc run --rm init
    step "Arrancando servicios"
    dc up -d app email job-runner postfix mailpit traefik
    sleep 4
    dc ps
    print_urls
    ;;

  send-test)
    shift
    from="probe@gmail.com"
    if [ "${1:-}" = "--from" ]; then from="$2"; shift 2; fi
    alias_addr="${1:-}"
    [ -n "$alias_addr" ] || die "uso: ./demo.sh send-test [--from remitente] <alias@${DEMO_APP_HOST}>"
    log "enviando  ${from}  ->  ${alias_addr}   (vía postfix:25)"
    dc run --rm --no-deps -T app python - "$from" "$alias_addr" <<'PY'
import sys, smtplib
from email.message import EmailMessage
frm, to = sys.argv[1], sys.argv[2]
m = EmailMessage()
m["From"] = frm
m["To"] = to
m["Subject"] = "Prueba de alias (demo local)"
m.set_content("Si ves este mensaje reenviado a tu buzon en Mailpit, el alias funciona.")
s = smtplib.SMTP("postfix", 25, timeout=20)
s.send_message(m)
s.quit()
print("OK: Postfix ha aceptado el mensaje")
PY
    ok "abre https://${DEMO_MAIL_HOST}/ — deberías ver el reenvío (de la reverse-alias, a tu buzón)"
    ;;

  activate)
    email="${2:?uso: ./demo.sh activate <email>}"
    dc exec -T db psql -U "${DB_USER:-simplelogin}" "${DB_NAME:-simplelogin}" \
      -c "UPDATE users SET activated=TRUE WHERE email='${email}';" \
      -c "DELETE FROM activation_code WHERE user_id=(SELECT id FROM users WHERE email='${email}');"
    ok "cuenta ${email} activada"
    ;;
  make-premium)
    email="${2:?uso: ./demo.sh make-premium <email>}"
    dc exec -T db psql -U "${DB_USER:-simplelogin}" "${DB_NAME:-simplelogin}" \
      -c "UPDATE users SET lifetime=TRUE WHERE email='${email}';"
    ok "cuenta ${email} marcada como lifetime"
    ;;

  down)   dc down ;;
  destroy)
    dc down -v
    docker run --rm -v "$DEMO_DIR":/w alpine sh -c 'rm -rf /w/data /w/certs /w/traefik/dynamic.yml' 2>/dev/null \
      || rm -rf "$DATA_DIR" "$CERT_DIR" "$DEMO_DIR/traefik/dynamic.yml"
    rm -f "$ENV_FILE" "$SL_ENV"
    ok "demo destruida (datos borrados)"
    ;;
  logs)   shift; dc logs --tail=200 "$@" ;;
  ps)     dc ps ;;
  urls)   print_urls ;;
  *)      grep '^#' "$0" | sed 's/^# \{0,1\}//' ;;
esac

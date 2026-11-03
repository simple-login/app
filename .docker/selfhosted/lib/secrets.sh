# shellcheck shell=bash
# Genera directorios de datos, claves DKIM y secretos.

DATA_DIR="$SELFHOSTED_DIR/data"

rand_hex() { openssl rand -hex "${1:-32}"; }

prepare_data_dirs() {
  mkdir -p "$DATA_DIR"/db "$DATA_DIR"/pgp "$DATA_DIR"/upload "$DATA_DIR"/dkim
  chmod 700 "$DATA_DIR/pgp"
}

generate_dkim() {
  local key="$DATA_DIR/dkim/dkim.key" pub="$DATA_DIR/dkim/dkim.pub.key"
  if [ -s "$key" ] && [ -s "$pub" ]; then
    ok "clave DKIM ya existente ($key)"; return
  fi
  log "Generando par de claves DKIM (RSA 1024)"
  if openssl genrsa -help 2>&1 | grep -q -- '-traditional'; then
    openssl genrsa -out "$key" -traditional 1024 2>/dev/null
  else
    openssl genrsa -out "$key" 1024 2>/dev/null
  fi
  openssl rsa -in "$key" -pubout -out "$pub" 2>/dev/null
  chmod 600 "$key"
  ok "DKIM generado"
}

# Valor listo para el registro TXT de DKIM (una sola línea)
dkim_txt_value() {
  sed 's/-----BEGIN PUBLIC KEY-----/v=DKIM1; k=rsa; p=/' "$DATA_DIR/dkim/dkim.pub.key" \
    | sed 's/-----END PUBLIC KEY-----//' | tr -d '\n' | tr -s ' '
}

# Parte base64 de la clave pública (para comparar con lo publicado en DNS)
dkim_pubkey_b64() {
  grep -v 'PUBLIC KEY' "$DATA_DIR/dkim/dkim.pub.key" | tr -d '\n '
}

# Rellena en el fichero .env los secretos que falten
ensure_secrets_in_env() {
  local env="$1"
  if [ -z "${DB_PASSWORD:-}" ]; then
    DB_PASSWORD="$(rand_hex 16)"; set_env_kv "$env" DB_PASSWORD "$DB_PASSWORD"; log "DB_PASSWORD generada"
  fi
  if [ -z "${FLASK_SECRET:-}" ]; then
    FLASK_SECRET="$(rand_hex 32)"; set_env_kv "$env" FLASK_SECRET "$FLASK_SECRET"; log "FLASK_SECRET generado"
  fi
  if [ -z "${PARTNER_API_TOKEN_SECRET:-}" ]; then
    PARTNER_API_TOKEN_SECRET="$(rand_hex 32)"; set_env_kv "$env" PARTNER_API_TOKEN_SECRET "$PARTNER_API_TOKEN_SECRET"
  fi
}

# Renderiza simplelogin.env desde la plantilla
render_simplelogin_env() {
  local tpl="$SELFHOSTED_DIR/simplelogin.env.template"
  local out="$SELFHOSTED_DIR/simplelogin.env"
  local scheme="${URL_SCHEME:-http}"
  local url="${scheme}://${APP_HOSTNAME}"

  sed \
    -e "s|__URL__|${url}|g" \
    -e "s|__ROOT_DOMAIN__|${ROOT_DOMAIN}|g" \
    -e "s|__APP_HOSTNAME__|${APP_HOSTNAME}|g" \
    -e "s|__SUPPORT_EMAIL__|${SUPPORT_EMAIL}|g" \
    -e "s|__DB_USER__|${DB_USER:-simplelogin}|g" \
    -e "s|__DB_PASSWORD__|${DB_PASSWORD}|g" \
    -e "s|__DB_NAME__|${DB_NAME:-simplelogin}|g" \
    -e "s|__FLASK_SECRET__|${FLASK_SECRET}|g" \
    -e "s|__PARTNER_API_TOKEN_SECRET__|${PARTNER_API_TOKEN_SECRET}|g" \
    "$tpl" > "$out"

  chmod 600 "$out"
  ok "simplelogin.env generado ($out)"
}

# Renderiza la config del proxy según DEPLOY_MODE (nada para "simple")
render_proxy_config() {
  case "${DEPLOY_MODE:-simple}" in
    caddy)
      sed -e "s|__APP_HOSTNAME__|${APP_HOSTNAME}|g" \
          -e "s|__ACME_EMAIL__|${ACME_EMAIL}|g" \
          "$SELFHOSTED_DIR/caddy/Caddyfile.template" > "$SELFHOSTED_DIR/caddy/Caddyfile"
      ok "caddy/Caddyfile generado"
      ;;
    traefik)
      sed -e "s|__ACME_EMAIL__|${ACME_EMAIL}|g" \
          "$SELFHOSTED_DIR/traefik/traefik.yml.template" > "$SELFHOSTED_DIR/traefik/traefik.yml"
      sed -e "s|__APP_HOSTNAME__|${APP_HOSTNAME}|g" \
          "$SELFHOSTED_DIR/traefik/dynamic.yml.template" > "$SELFHOSTED_DIR/traefik/dynamic.yml"
      ok "traefik/{traefik,dynamic}.yml generados"
      ;;
  esac
}

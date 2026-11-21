#!/usr/bin/env bash
#
# Instalador guiado del despliegue full-dockerizado de SimpleLogin.
#
#   ./install.sh                      # interactivo
#   ./install.sh --mode simple|caddy|traefik   # elige el reverse proxy / TLS
#   ./install.sh --reconfigure        # vuelve a preguntar aunque exista .env
#   ./install.sh --yes                # no interactivo (usa .env tal cual)
#   ./install.sh --skip-dns-check     # no espera a que el DNS propague
#   ./install.sh --skip-dns           # omite por completo el paso de DNS
#
set -euo pipefail

SELFHOSTED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELFHOSTED_DIR/../.." && pwd)"
ENV_FILE="$SELFHOSTED_DIR/.env"

# shellcheck source=lib/common.sh
source "$SELFHOSTED_DIR/lib/common.sh"

RECONFIGURE=0
SKIP_DNS=0
SKIP_DNS_CHECK=0
MODE_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --reconfigure) RECONFIGURE=1 ;;
    --yes|-y) NONINTERACTIVE=1 ;;
    --skip-dns) SKIP_DNS=1 ;;
    --skip-dns-check|--no-dns-check) SKIP_DNS_CHECK=1 ;;
    --mode) MODE_ARG="${2:?--mode necesita simple|caddy|traefik}"; shift ;;
    --mode=*) MODE_ARG="${1#--mode=}" ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//' | head -20; exit 0 ;;
    *) die "opción desconocida: $1" ;;
  esac
  shift
done
case "${MODE_ARG:-}" in ""|simple|caddy|traefik) ;; *) die "--mode inválido: $MODE_ARG" ;; esac
export NONINTERACTIVE="${NONINTERACTIVE:-0}"

# Cargar .env existente (si lo hay) para tener valores por defecto
[ -f "$ENV_FILE" ] && load_env_file "$ENV_FILE"

# shellcheck source=lib/preflight.sh
source "$SELFHOSTED_DIR/lib/preflight.sh"
# shellcheck source=lib/secrets.sh
source "$SELFHOSTED_DIR/lib/secrets.sh"
# shellcheck source=lib/dns.sh
source "$SELFHOSTED_DIR/lib/dns.sh"
# shellcheck source=lib/ports.sh
source "$SELFHOSTED_DIR/lib/ports.sh"
# shellcheck source=lib/verify.sh
source "$SELFHOSTED_DIR/lib/verify.sh"

printf '%s\n' "${C_BOLD}SimpleLogin — instalador dockerizado${C_RESET}"
printf '%s\n' "repo: $REPO_ROOT"

preflight

# ─────────────────────────────────────────────────────────────────────────────
step "1/7 · Configuración"
# ─────────────────────────────────────────────────────────────────────────────
if [ ! -f "$ENV_FILE" ] || [ "$RECONFIGURE" = 1 ]; then
  [ -f "$ENV_FILE" ] || cp "$SELFHOSTED_DIR/.env.example" "$ENV_FILE"

  ask ROOT_DOMAIN   "Dominio para los alias (ROOT_DOMAIN)"          "${ROOT_DOMAIN:-}"
  [ -n "${ROOT_DOMAIN:-}" ] || die "ROOT_DOMAIN es obligatorio"
  ask APP_HOSTNAME  "Host del webapp / objetivo MX (APP_HOSTNAME)"  "${APP_HOSTNAME:-app.$ROOT_DOMAIN}"
  ask SUPPORT_EMAIL "Email remitente (SUPPORT_EMAIL)"               "${SUPPORT_EMAIL:-support@$ROOT_DOMAIN}"

  local_ip_default="${SERVER_IP:-}"
  if [ -z "$local_ip_default" ] && detected_ip="$(public_ip)"; then
    local_ip_default="$detected_ip"
  fi
  ask SERVER_IP "IP pública del servidor (registro A)" "$local_ip_default"
  [[ "${SERVER_IP:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "SERVER_IP no es una IPv4 válida"

  # Modo de proxy / TLS
  DEPLOY_MODE="${MODE_ARG:-${DEPLOY_MODE:-}}"
  if [ -z "$DEPLOY_MODE" ]; then
    echo "  Reverse proxy / TLS:"
    echo "    1) simple  — sin proxy (webapp en 127.0.0.1:7777, pones el tuyo delante)"
    echo "    2) caddy   — Caddy con HTTPS automático (Let's Encrypt)"
    echo "    3) traefik — Traefik con HTTPS automático (Let's Encrypt)"
    proxy_choice=""; ask proxy_choice "Elige modo [1-3]" "1"
    case "$proxy_choice" in 2|caddy) DEPLOY_MODE=caddy ;; 3|traefik) DEPLOY_MODE=traefik ;; *) DEPLOY_MODE=simple ;; esac
  fi
  if [ "$DEPLOY_MODE" = simple ]; then
    URL_SCHEME="${URL_SCHEME:-http}"
  else
    URL_SCHEME=https
    ask ACME_EMAIL "Email para Let's Encrypt (ACME_EMAIL)" "${ACME_EMAIL:-$SUPPORT_EMAIL}"
  fi

  if confirm "¿Configurar los registros DNS automáticamente vía API de Cloudflare?"; then
    ask_secret CF_API_TOKEN "Cloudflare API token (Zone.DNS:Edit + Zone:Read)"
    ask CF_ZONE_NAME "Nombre de la zona en Cloudflare" "${CF_ZONE_NAME:-$ROOT_DOMAIN}"
  fi

  ask DB_USER "Usuario de PostgreSQL" "${DB_USER:-simplelogin}"
  ask DB_NAME "Base de datos"          "${DB_NAME:-simplelogin}"

  # Persistir
  for k in ROOT_DOMAIN APP_HOSTNAME SUPPORT_EMAIL SERVER_IP DEPLOY_MODE ACME_EMAIL \
           URL_SCHEME CF_API_TOKEN CF_ZONE_NAME DB_USER DB_NAME POSTFIX_SUBMISSION \
           RELAY_HOST RELAY_USER RELAY_PASSWORD; do
    set_env_kv "$ENV_FILE" "$k" "${!k:-}"
  done
  ok ".env guardado ($ENV_FILE)"
elif [ -n "$MODE_ARG" ] && [ "$MODE_ARG" != "${DEPLOY_MODE:-}" ]; then
  set_env_kv "$ENV_FILE" DEPLOY_MODE "$MODE_ARG"
  [ "$MODE_ARG" != simple ] && set_env_kv "$ENV_FILE" URL_SCHEME https
  ok "modo cambiado a '$MODE_ARG' en $ENV_FILE"
else
  ok "usando el .env existente ($ENV_FILE) — usa --reconfigure para cambiarlo"
fi

load_env_file "$ENV_FILE"
: "${ROOT_DOMAIN:?}" "${APP_HOSTNAME:?}" "${SUPPORT_EMAIL:?}" "${SERVER_IP:?}"
export DEPLOY_MODE="${DEPLOY_MODE:-simple}"
if [ "$DEPLOY_MODE" != simple ]; then
  : "${ACME_EMAIL:?define ACME_EMAIL en .env para el modo $DEPLOY_MODE}"
fi

# ─────────────────────────────────────────────────────────────────────────────
step "2/7 · Claves y secretos"
# ─────────────────────────────────────────────────────────────────────────────
prepare_data_dirs
generate_dkim
ensure_secrets_in_env "$ENV_FILE"
load_env_file "$ENV_FILE"
render_simplelogin_env
render_proxy_config

# ─────────────────────────────────────────────────────────────────────────────
step "3/7 · DNS"
# ─────────────────────────────────────────────────────────────────────────────
if [ "$SKIP_DNS" = 1 ]; then
  warn "Paso de DNS omitido (--skip-dns). Asegúrate de tener MX/A/SPF/DKIM/DMARC configurados."
  build_records
  print_records_table
else
  build_records
  print_records_table
  if [ -n "${CF_API_TOKEN:-}" ]; then
    cloudflare_apply
  else
    log "Modo manual: crea los registros de arriba en tu proveedor DNS."
    if [ "$SKIP_DNS_CHECK" != 1 ]; then
      confirm "He creado los registros. ¿Continuar?" || die "Vuelve a ejecutar cuando estén creados."
    fi
  fi
  reverse_dns_notice

  if [ "$SKIP_DNS_CHECK" = 1 ]; then
    warn "Verificación de DNS omitida (--skip-dns-check). Re-verifica luego con: ./manage.sh verify"
  elif ! confirm "¿Verificar ahora que los registros DNS resuelven (dig)?"; then
    log "Verificación de DNS saltada. Re-verifica luego con: ./manage.sh verify"
  elif ! wait_for_dns 10; then
    warn "Continuo igualmente; puedes re-verificar luego con:  ./manage.sh verify"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
step "4/7 · Puertos"
# ─────────────────────────────────────────────────────────────────────────────
check_local_port_conflicts
open_firewall
check_outbound_25 || true

# ─────────────────────────────────────────────────────────────────────────────
step "5/7 · Construcción de imágenes"
# ─────────────────────────────────────────────────────────────────────────────
log "docker compose build app postfix  (la primera vez puede tardar 10-20 min)"
compose build app postfix
compose --profile cron build || warn "no se pudo construir la imagen 'cron' (opcional)"

# ─────────────────────────────────────────────────────────────────────────────
step "6/7 · Base de datos y arranque"
# ─────────────────────────────────────────────────────────────────────────────
compose up -d db
log "esperando a que PostgreSQL esté listo..."
for i in $(seq 1 30); do
  if compose exec -T db pg_isready -U "${DB_USER:-simplelogin}" -d "${DB_NAME:-simplelogin}" >/dev/null 2>&1; then
    ok "PostgreSQL listo"; break
  fi
  sleep 2
done

log "migración de la base de datos (alembic upgrade head)"
compose run --rm migration
log "datos iniciales (init_app.py)"
compose run --rm init

log "levantando el stack"
compose up -d
if confirm "¿Levantar también el cron de mantenimiento (recomendado)?"; then
  compose --profile cron up -d && set_env_kv "$ENV_FILE" ENABLE_CRON 1
fi

# ─────────────────────────────────────────────────────────────────────────────
step "7/7 · Verificación"
# ─────────────────────────────────────────────────────────────────────────────
sleep 5
verify_stack || true
print_summary

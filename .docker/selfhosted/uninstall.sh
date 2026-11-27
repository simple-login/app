#!/usr/bin/env bash
#
# Desinstalador del despliegue dockerizado de SimpleLogin.
#
#   ./uninstall.sh            para y elimina contenedores + red
#                             (CONSERVA data/, imágenes y config)
#   ./uninstall.sh --purge    además borra data/ (BBDD, PGP, DKIM, uploads),
#                             la config generada, las imágenes y los volúmenes
#   ./uninstall.sh --purge --yes    sin preguntar  (¡IRREVERSIBLE!)
#
# Durante el proceso ofrece (preguntando): hacer un backup antes de borrar,
# cerrar los puertos del firewall y borrar los registros DNS de Cloudflare.
#
set -euo pipefail

SELFHOSTED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELFHOSTED_DIR/../.." && pwd)"
ENV_FILE="$SELFHOSTED_DIR/.env"
SL_ENV="$SELFHOSTED_DIR/simplelogin.env"
PROJECT="simplelogin"

# shellcheck source=lib/common.sh
source "$SELFHOSTED_DIR/lib/common.sh"

PURGE=0
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    --yes|-y) NONINTERACTIVE=1 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "opción desconocida: $arg" ;;
  esac
done
export NONINTERACTIVE="${NONINTERACTIVE:-0}"

[ -f "$ENV_FILE" ] && load_env_file "$ENV_FILE"
export DEPLOY_MODE="${DEPLOY_MODE:-simple}"
CRON_PROFILE=(); [ "${ENABLE_CRON:-0}" = "1" ] && CRON_PROFILE=(--profile cron)

# shellcheck source=lib/secrets.sh
source "$SELFHOSTED_DIR/lib/secrets.sh"   # DATA_DIR
# shellcheck source=lib/ports.sh
source "$SELFHOSTED_DIR/lib/ports.sh"     # close_firewall

# Baja el stack. Si falta .env, compose no puede interpolar el fichero -> usa docker directo.
stack_down() {
  local extra=("$@")
  if [ -f "$ENV_FILE" ]; then
    compose "${CRON_PROFILE[@]}" down --remove-orphans "${extra[@]}" && return 0
  fi
  warn "sin .env utilizable — eliminando por etiquetas de compose"
  docker ps -aq --filter "label=com.docker.compose.project=${PROJECT}" | xargs -r docker rm -f >/dev/null
  docker network rm "${PROJECT}-sl" >/dev/null 2>&1 || true
  if printf '%s\n' "${extra[@]}" | grep -q -- '--volumes'; then
    docker volume ls -q --filter "label=com.docker.compose.project=${PROJECT}" | xargs -r docker volume rm >/dev/null 2>&1 || true
  fi
}

hr
if [ "$PURGE" = 1 ]; then
  printf '%s\n' "${C_BOLD}${C_RED}Desinstalación COMPLETA (--purge)${C_RESET}"
  echo "Se van a eliminar:"
  echo "  • contenedores, red y volúmenes de Docker"
  echo "  • imágenes  simplelogin-selfhosted{,-postfix,-cron}:local"
  echo "  • ${DATA_DIR}/   (base de datos, claves PGP, DKIM, ficheros subidos)"
  echo "  • .env, simplelogin.env y la config del proxy generada"
else
  printf '%s\n' "${C_BOLD}Parada y limpieza${C_RESET}"
  echo "Se van a eliminar los contenedores y la red."
  echo "Se CONSERVAN  ${DATA_DIR}/, las imágenes y la config."
  echo "(para borrarlo todo:  ./uninstall.sh --purge)"
fi
hr
confirm "¿Continuar?" || { log "cancelado"; exit 0; }

# ── Backup opcional (solo si vamos a purgar y la BBDD está en marcha) ──────
if [ "$PURGE" = 1 ] && [ -f "$ENV_FILE" ] \
   && compose ps --status running --services 2>/dev/null | grep -qx db; then
  if confirm "¿Hacer un backup de la BBDD + data/ antes de borrar?"; then
    bash "$SELFHOSTED_DIR/manage.sh" backup || warn "el backup falló"
    confirm "¿Continuar con la desinstalación?" || exit 0
  fi
fi

# ── Cloudflare DNS opcional ────────────────────────────────────────────────
if [ -n "${CF_API_TOKEN:-}" ] && [ -n "${ROOT_DOMAIN:-}" ] && has_cmd jq && has_cmd curl; then
  if confirm "¿Borrar también los registros DNS (MX/A/SPF/DKIM/DMARC) de Cloudflare?"; then
    # shellcheck source=lib/dns.sh
    source "$SELFHOSTED_DIR/lib/dns.sh"
    build_records
    cloudflare_remove || warn "revisa los registros en el panel de Cloudflare"
  fi
fi

# ── Docker down ───────────────────────────────────────────────────────────
step "Deteniendo el stack"
if [ "$PURGE" = 1 ]; then
  stack_down --volumes
else
  stack_down
fi
ok "contenedores y red eliminados"

# ── Firewall opcional ─────────────────────────────────────────────────────
[ "$PURGE" = 1 ] && close_firewall

# ── Borrado de ficheros ───────────────────────────────────────────────────
if [ "$PURGE" = 1 ]; then
  step "Borrando datos, config e imágenes"
  rm -f "$ENV_FILE" "$SL_ENV" \
        "$SELFHOSTED_DIR/caddy/Caddyfile" \
        "$SELFHOSTED_DIR/traefik/traefik.yml" "$SELFHOSTED_DIR/traefik/dynamic.yml"
  if [ -d "$DATA_DIR" ]; then
    docker run --rm -v "$SELFHOSTED_DIR":/w alpine sh -c 'rm -rf /w/data' 2>/dev/null \
      || sudo rm -rf "$DATA_DIR" 2>/dev/null \
      || rm -rf "$DATA_DIR"
  fi
  docker image rm -f simplelogin-selfhosted:local simplelogin-selfhosted-postfix:local \
                     simplelogin-selfhosted-cron:local >/dev/null 2>&1 || true
  ok "data/, config e imágenes eliminados"
  [ -d "$SELFHOSTED_DIR/backups" ] && log "backups/ NO se ha tocado ($SELFHOSTED_DIR/backups)"
fi

hr
if [ "$PURGE" = 1 ]; then
  ok "SimpleLogin desinstalado por completo."
  echo "Pendiente a mano si aplica:"
  echo "  • registro PTR / rDNS en tu proveedor de VPS"
  echo "  • ${SELFHOSTED_DIR}/backups/  (si hiciste backups)"
  echo "  • el código sigue en $REPO_ROOT"
else
  ok "Stack detenido. Para volver a arrancar:  ./manage.sh up"
  echo "Para borrarlo todo:  ./uninstall.sh --purge"
fi
hr

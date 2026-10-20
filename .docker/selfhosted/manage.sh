#!/usr/bin/env bash
#
# Operaciones del día a día del SimpleLogin dockerizado.
#
#   ./manage.sh <comando> [args]
#
# Comandos:
#   up                     Levanta el stack (+ caddy/cron si están habilitados en .env)
#   down                   Para el stack
#   restart [servicio]     Reinicia todo o un servicio
#   ps                     Estado de los contenedores
#   logs [servicio] [-f]   Logs (por defecto de todos)
#   verify                 Re-ejecuta las comprobaciones de salud
#   build                  Reconstruye las imágenes
#   upgrade                git pull + build + migración + up
#   migrate                Ejecuta solo la migración de la BBDD
#   backup [dir]           Vuelca la BBDD y los datos a un tar.gz
#   restore <archivo>      Restaura desde un backup
#   shell                  Abre el shell de SimpleLogin (python shell.py)
#   psql                   Abre psql en la base de datos
#   make-premium <email>   Marca una cuenta como lifetime/premium
#   activate <email>       Activa la cuenta sin el email de confirmación
#   activation-link <email>  Imprime el enlace de activación pendiente
#   disable-registration   Cierra el alta de nuevas cuentas y reinicia la webapp
#   set-mode <simple|caddy|traefik>   Cambia el reverse proxy / TLS
#
set -euo pipefail

SELFHOSTED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELFHOSTED_DIR/../.." && pwd)"
ENV_FILE="$SELFHOSTED_DIR/.env"
SL_ENV="$SELFHOSTED_DIR/simplelogin.env"

# shellcheck source=lib/common.sh
source "$SELFHOSTED_DIR/lib/common.sh"
[ -f "$ENV_FILE" ] || die "No existe $ENV_FILE — ejecuta ./install.sh primero"
load_env_file "$ENV_FILE"

export DEPLOY_MODE="${DEPLOY_MODE:-simple}"
CRON_PROFILE=()
[ "${ENABLE_CRON:-0}" = "1" ] && CRON_PROFILE=(--profile cron)

# shellcheck source=lib/secrets.sh
source "$SELFHOSTED_DIR/lib/secrets.sh"

# Asegura que la config del proxy esté renderizada para el modo activo
case "$DEPLOY_MODE" in
  caddy)   [ -f "$SELFHOSTED_DIR/caddy/Caddyfile" ]     || render_proxy_config ;;
  traefik) [ -f "$SELFHOSTED_DIR/traefik/dynamic.yml" ] || render_proxy_config ;;
esac

cmd="${1:-}"; shift || true

case "$cmd" in
  up)      compose "${CRON_PROFILE[@]}" up -d "$@" ;;
  down)    compose "${CRON_PROFILE[@]}" down "$@" ;;
  restart) compose "${CRON_PROFILE[@]}" restart "$@" ;;
  ps)      compose "${CRON_PROFILE[@]}" ps "$@" ;;
  logs)    compose "${CRON_PROFILE[@]}" logs --tail=200 "$@" ;;
  build)   compose build app postfix && compose "${CRON_PROFILE[@]}" build ;;

  verify)
    # shellcheck source=lib/dns.sh
    source "$SELFHOSTED_DIR/lib/dns.sh"
    source "$SELFHOSTED_DIR/lib/verify.sh"
    : "${ROOT_DOMAIN:?}" "${APP_HOSTNAME:?}"
    verify_stack || true
    ;;

  set-mode)
    new_mode="${1:?uso: ./manage.sh set-mode <simple|caddy|traefik>}"
    case "$new_mode" in simple|caddy|traefik) ;; *) die "modo inválido: $new_mode" ;; esac
    if [ "$new_mode" != simple ] && [ -z "${ACME_EMAIL:-}" ]; then
      die "define ACME_EMAIL en $ENV_FILE antes de usar el modo $new_mode"
    fi
    # baja el stack con el modo ANTERIOR para no dejar el proxy viejo huérfano
    compose down --remove-orphans || true
    set_env_kv "$ENV_FILE" DEPLOY_MODE "$new_mode"
    [ "$new_mode" != simple ] && set_env_kv "$ENV_FILE" URL_SCHEME https
    export DEPLOY_MODE="$new_mode"
    load_env_file "$ENV_FILE"
    render_proxy_config
    # actualiza URL en simplelogin.env
    scheme="http"; [ "$new_mode" != simple ] && scheme="https"
    set_env_kv "$SL_ENV" URL "${scheme}://${APP_HOSTNAME}"
    compose "${CRON_PROFILE[@]}" up -d
    ok "modo = $new_mode. Revisa:  ./manage.sh ps"
    ;;

  migrate)
    compose run --rm migration
    ;;

  upgrade)
    step "Actualizando SimpleLogin"
    git -C "$REPO_ROOT" pull --ff-only
    compose build app postfix
    compose "${CRON_PROFILE[@]}" build
    compose up -d db
    sleep 3
    compose run --rm migration
    compose "${CRON_PROFILE[@]}" up -d
    ok "actualizado"
    ;;

  backup)
    dir="${1:-$SELFHOSTED_DIR/backups}"; mkdir -p "$dir"
    ts="$(date +%Y%m%d-%H%M%S)"
    dump="$dir/db-$ts.sql.gz"
    log "volcando base de datos -> $dump"
    compose exec -T db pg_dump -U "${DB_USER:-simplelogin}" "${DB_NAME:-simplelogin}" | gzip > "$dump"
    tarball="$dir/data-$ts.tar.gz"
    log "empaquetando data/ (sin la BBDD, ya volcada) -> $tarball"
    tar -C "$SELFHOSTED_DIR" --exclude='data/db' -czf "$tarball" data
    cp "$SL_ENV" "$dir/simplelogin.env-$ts"
    cp "$ENV_FILE" "$dir/env-$ts"
    ok "backup completo en $dir"
    ;;

  restore)
    archive="${1:?uso: ./manage.sh restore <db-*.sql.gz>}"
    [ -f "$archive" ] || die "no existe $archive"
    confirm "Esto SOBREESCRIBE la base de datos actual. ¿Seguro?" || exit 1
    compose up -d db; sleep 3
    gunzip -c "$archive" | compose exec -T db psql -U "${DB_USER:-simplelogin}" "${DB_NAME:-simplelogin}"
    ok "restaurado. Reinicia:  ./manage.sh restart"
    ;;

  shell)  compose exec app python shell.py ;;
  psql)   compose exec db psql -U "${DB_USER:-simplelogin}" "${DB_NAME:-simplelogin}" ;;

  make-premium)
    email="${1:?uso: ./manage.sh make-premium <email>}"
    compose exec -T db psql -U "${DB_USER:-simplelogin}" "${DB_NAME:-simplelogin}" \
      -c "UPDATE users SET lifetime = TRUE WHERE email = '${email}';"
    ok "cuenta ${email} marcada como lifetime"
    ;;

  activate)
    email="${1:?uso: ./manage.sh activate <email>}"
    compose exec -T db psql -U "${DB_USER:-simplelogin}" "${DB_NAME:-simplelogin}" \
      -c "UPDATE users SET activated = TRUE WHERE email = '${email}';" \
      -c "DELETE FROM activation_code WHERE user_id = (SELECT id FROM users WHERE email = '${email}');"
    ok "cuenta ${email} activada (sin necesidad del email de confirmación)"
    ;;

  activation-link)
    email="${1:?uso: ./manage.sh activation-link <email>}"
    code="$(compose exec -T db psql -tA -U "${DB_USER:-simplelogin}" "${DB_NAME:-simplelogin}" \
      -c "SELECT ac.code FROM activation_code ac JOIN users u ON u.id = ac.user_id WHERE u.email = '${email}' ORDER BY ac.id DESC LIMIT 1;")"
    [ -n "$code" ] || die "no hay código de activación pendiente para ${email} (¿ya activada? usa 'activate')"
    url="$(grep -E '^URL=' "$SL_ENV" | cut -d= -f2-)"
    ok "${url%/}/auth/activate?code=${code}"
    ;;

  disable-registration)
    set_env_kv "$SL_ENV" DISABLE_REGISTRATION 1
    set_env_kv "$SL_ENV" DISABLE_ONBOARDING true
    compose restart app email job-runner
    ok "registro cerrado (DISABLE_REGISTRATION=1). Reiniciados app/email/job-runner."
    ;;

  ""|-h|--help)
    grep '^#' "$0" | sed 's/^# \{0,1\}//'
    ;;
  *)
    die "comando desconocido: $cmd  (usa ./manage.sh --help)"
    ;;
esac

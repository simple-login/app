# shellcheck shell=bash
# Helpers compartidos por install.sh / manage.sh / lib/*.sh

# ── Colores / logging ──────────────────────────────────────────────────────
if [ -t 1 ]; then
  C_RESET=$'\033[0m'; C_RED=$'\033[31m'; C_GRN=$'\033[32m'
  C_YEL=$'\033[33m'; C_BLU=$'\033[34m'; C_BOLD=$'\033[1m'
else
  C_RESET=; C_RED=; C_GRN=; C_YEL=; C_BLU=; C_BOLD=
fi

log()  { printf '%s\n' "${C_BLU}::${C_RESET} $*"; }
ok()   { printf '%s\n' "${C_GRN}✓${C_RESET} $*"; }
warn() { printf '%s\n' "${C_YEL}!${C_RESET} $*" >&2; }
err()  { printf '%s\n' "${C_RED}✗${C_RESET} $*" >&2; }
die()  { err "$*"; exit 1; }
hr()   { printf '%s\n' "────────────────────────────────────────────────────────"; }
step() { printf '\n%s\n' "${C_BOLD}${C_BLU}▸ $*${C_RESET}"; }

has_cmd() { command -v "$1" >/dev/null 2>&1; }
require_cmd() { has_cmd "$1" || die "Falta el comando '$1'. Instálalo y reintenta."; }

# ── Prompts ────────────────────────────────────────────────────────────────
# ask VAR "Pregunta" "valor_por_defecto"
ask() {
  local __var="$1" __prompt="$2" __def="${3:-}" __ans
  if [ "${NONINTERACTIVE:-0}" = "1" ]; then
    printf -v "$__var" '%s' "${!__var:-$__def}"; return
  fi
  if [ -n "$__def" ]; then
    read -r -p "$__prompt [$__def]: " __ans || true
    __ans="${__ans:-$__def}"
  else
    read -r -p "$__prompt: " __ans || true
  fi
  printf -v "$__var" '%s' "$__ans"
}

# ask_secret VAR "Pregunta"   (entrada oculta, vacío permitido)
ask_secret() {
  local __var="$1" __prompt="$2" __ans
  if [ "${NONINTERACTIVE:-0}" = "1" ]; then return; fi
  read -r -s -p "$__prompt: " __ans || true; echo
  printf -v "$__var" '%s' "$__ans"
}

# confirm "Pregunta"  -> 0 si sí
confirm() {
  local __ans
  if [ "${NONINTERACTIVE:-0}" = "1" ]; then return 0; fi
  read -r -p "$1 [s/N]: " __ans || true
  [[ "$__ans" =~ ^[sSyY]$ ]]
}

# ── .env ───────────────────────────────────────────────────────────────────
# Lee KEY=VALUE de un fichero .env a variables de shell (sin ejecutar el fichero)
load_env_file() {
  local file="$1" line key val
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    key="${line%%=*}"; val="${line#*=}"
    key="$(printf '%s' "$key" | tr -d '[:space:]')"
    [ -z "$key" ] && continue
    printf -v "$key" '%s' "$val"
  done < "$file"
}

# set_env_kv fichero KEY VALUE  -> añade o reemplaza la línea
set_env_kv() {
  local file="$1" key="$2" val="$3"
  touch "$file"
  if grep -qE "^${key}=" "$file"; then
    local tmp; tmp="$(mktemp)"
    grep -vE "^${key}=" "$file" > "$tmp"
    printf '%s=%s\n' "$key" "$val" >> "$tmp"
    mv "$tmp" "$file"
  else
    printf '%s=%s\n' "$key" "$val" >> "$file"
  fi
}

# ── Docker Compose ─────────────────────────────────────────────────────────
# Modo de despliegue: simple (sin proxy) | caddy | traefik. Se lee de DEPLOY_MODE.
compose() {
  local args=(--project-directory "$SELFHOSTED_DIR" -f "$SELFHOSTED_DIR/docker-compose.yml")
  case "${DEPLOY_MODE:-simple}" in
    caddy)   args+=(-f "$SELFHOSTED_DIR/caddy/docker-compose.caddy.yml") ;;
    traefik) args+=(-f "$SELFHOSTED_DIR/traefik/docker-compose.traefik.yml") ;;
    simple|"") ;;
    *) die "DEPLOY_MODE desconocido: '${DEPLOY_MODE}' (usa simple|caddy|traefik)" ;;
  esac
  docker compose "${args[@]}" "$@"
}

# ── DNS lookups (dig, host o contenedor de respaldo) ───────────────────────
sl_dig() {   # sl_dig TYPE NAME  -> valores, uno por línea, en minúsculas y sin comillas
  local type="$1" name="$2" out=""
  if has_cmd dig; then
    out="$(dig +short "$type" "$name" @1.1.1.1 2>/dev/null)"
  elif has_cmd host; then
    out="$(host -t "$type" "$name" 1.1.1.1 2>/dev/null | sed 's/.* //')"
  elif has_cmd docker; then
    out="$(docker run --rm --network host alpine:3 sh -c \
      "apk add --no-cache -q bind-tools >/dev/null 2>&1 && dig +short $type $name @1.1.1.1" 2>/dev/null)"
  fi
  printf '%s' "$out" | tr -d '"' | tr '[:upper:]' '[:lower:]' | sed '/^$/d'
}

# ── TCP ────────────────────────────────────────────────────────────────────
tcp_check() {  # tcp_check HOST PORT [timeout]
  local host="$1" port="$2" t="${3:-5}"
  timeout "$t" bash -c "exec 3<>/dev/tcp/${host}/${port}" 2>/dev/null
}

public_ip() {
  local ip=""
  for u in "https://api.ipify.org" "https://ifconfig.me/ip" "https://icanhazip.com"; do
    if has_cmd curl; then ip="$(curl -fsS --max-time 5 "$u" 2>/dev/null | tr -d '[:space:]')"
    elif has_cmd wget; then ip="$(wget -qO- --timeout=5 "$u" 2>/dev/null | tr -d '[:space:]')"; fi
    [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && { printf '%s' "$ip"; return 0; }
  done
  return 1
}

# shellcheck shell=bash
# Comprobaciones previas del entorno.

preflight() {
  step "Comprobaciones previas"
  local fail=0

  if has_cmd docker; then ok "docker: $(docker --version | awk '{print $3}' | tr -d ',')"
  else err "docker no está instalado — https://docs.docker.com/engine/install/"; fail=1; fi

  if docker compose version >/dev/null 2>&1; then
    ok "docker compose: $(docker compose version --short 2>/dev/null || echo ok)"
  else err "falta el plugin 'docker compose' (v2)"; fail=1; fi

  if docker info >/dev/null 2>&1; then ok "el daemon de Docker responde"
  else err "no se puede hablar con el daemon de Docker (¿permisos? ¿docker arrancado?)"; fail=1; fi

  if has_cmd openssl; then ok "openssl: $(openssl version | awk '{print $1, $2}')"
  else err "openssl no está instalado"; fail=1; fi

  if has_cmd dig || has_cmd host; then ok "utilidades DNS disponibles"
  else warn "sin 'dig' ni 'host' — se usará un contenedor para verificar DNS (más lento). Recomendado: apt install dnsutils / bind-utils"; fi

  if has_cmd curl || has_cmd wget; then ok "curl/wget disponible"
  else warn "sin curl/wget — tendrás que indicar la IP pública manualmente"; fi

  # arquitectura: la imagen de la app fija linux/amd64
  local arch; arch="$(uname -m)"
  if [ "$arch" != "x86_64" ] && [ "$arch" != "amd64" ]; then
    warn "arquitectura $arch: la imagen de SimpleLogin es linux/amd64 y se emulará (build y arranque lentos). Instala qemu-user-static / binfmt."
  fi

  # jq solo es necesario para el modo API de Cloudflare
  if [ -n "${CF_API_TOKEN:-}" ] && ! has_cmd jq; then
    err "CF_API_TOKEN definido pero falta 'jq' (necesario para la API de Cloudflare). apt install jq"; fail=1
  fi

  [ "$fail" -eq 0 ] || die "Corrige los errores anteriores y vuelve a ejecutar."
}

# shellcheck shell=bash
# Smoke tests posteriores al arranque.

verify_stack() {
  step "Verificación del stack"
  local fail=0

  # 1) contenedores
  local expected=(db app email job-runner postfix)
  local s
  for s in "${expected[@]}"; do
    local state
    state="$(compose ps --status running --services 2>/dev/null | grep -Fx "$s" || true)"
    if [ -n "$state" ]; then ok "contenedor '${s}' en ejecución"
    else err "contenedor '${s}' NO está en ejecución  (compose logs ${s})"; fail=1; fi
  done

  # 2) webapp /health
  if compose exec -T app python -c \
      "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7777/health').read().decode().strip()=='success' else 1)" 2>/dev/null; then
    ok "webapp responde en /health"
  else
    err "webapp no responde en /health  (compose logs app)"; fail=1
  fi

  # 3) Postfix <-> PostgreSQL: relay_domains + transport_maps
  local rd tm
  rd="$(compose exec -T postfix postmap -q "$ROOT_DOMAIN" pgsql:/etc/postfix/pgsql-relay-domains.cf 2>/dev/null || true)"
  tm="$(compose exec -T postfix postmap -q "$ROOT_DOMAIN" pgsql:/etc/postfix/pgsql-transport-maps.cf 2>/dev/null || true)"
  if [ "$rd" = "$ROOT_DOMAIN" ]; then ok "Postfix reconoce el dominio (${ROOT_DOMAIN})"
  else err "Postfix NO reconoce ${ROOT_DOMAIN} (relay-domains). ¿Migración ejecutada? ¿credenciales DB?"; fail=1; fi
  if printf '%s' "$tm" | grep -q 'smtp:email:20381'; then ok "Postfix enruta a email:20381"
  else err "transport-maps no devuelve 'smtp:email:20381' (obtenido: '${tm:-<vacío>}')"; fail=1; fi

  # 4) Postfix acepta conexiones SMTP
  if compose exec -T postfix bash -c 'exec 3<>/dev/tcp/127.0.0.1/25 && head -1 <&3' 2>/dev/null | grep -qi ESMTP; then
    ok "Postfix acepta SMTP en el puerto 25"
  else
    warn "no obtengo banner ESMTP de Postfix (puede tardar unos segundos tras el arranque)"
  fi

  # 5) DKIM: la clave publicada coincide con la local
  local pub_local pub_dns
  pub_local="$(dkim_pubkey_b64 | tr '[:upper:]' '[:lower:]')"
  pub_dns="$(sl_dig TXT "dkim._domainkey.${ROOT_DOMAIN}" | tr -d ' "' | sed 's/.*p=//')"
  if [ -n "$pub_dns" ] && [ "${pub_local:0:40}" = "${pub_dns:0:40}" ]; then
    ok "el registro DKIM del DNS coincide con la clave local"
  else
    warn "DKIM DNS aún no coincide/propaga (local ${pub_local:0:16}... / dns ${pub_dns:0:16}...)"
  fi

  hr
  if [ "$fail" -eq 0 ]; then
    ok "Verificación OK"
  else
    warn "Hay comprobaciones en rojo — revisa los logs indicados."
  fi
  return "$fail"
}

print_summary() {
  local scheme="${URL_SCHEME:-http}"
  hr
  cat <<EOF
${C_BOLD}SimpleLogin self-hosted — listo${C_RESET}

  Webapp:            ${scheme}://${APP_HOSTNAME}/
  Dominio de alias:  ${ROOT_DOMAIN}
  Datos:             ${SELFHOSTED_DIR}/data/   (BBDD, PGP, uploads, DKIM)
  Config app:        ${SELFHOSTED_DIR}/simplelogin.env
  Config despliegue: ${SELFHOSTED_DIR}/.env

Primeros pasos:
  1) Abre ${scheme}://${APP_HOSTNAME}/ y crea tu cuenta.
  2) Hazla premium (alias ilimitados):
       ./manage.sh make-premium tu-email@dominio
  3) Cuando tengas todas tus cuentas, cierra el registro:
       ./manage.sh disable-registration
  4) Envía un email de prueba a un alias y revisa:  ./manage.sh logs email

Operación:
  ./manage.sh ps | logs [servicio] | restart | verify | upgrade | backup
EOF
  hr
}

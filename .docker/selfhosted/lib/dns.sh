# shellcheck shell=bash
# Definición, publicación (Cloudflare API) y verificación de los registros DNS.

# Rellena el array RECORDS con "TIPO|NOMBRE|VALOR|PRIO"
build_records() {
  RECORDS=()
  RECORDS+=("MX|${ROOT_DOMAIN}|${APP_HOSTNAME}.|10")
  RECORDS+=("A|${APP_HOSTNAME}|${SERVER_IP}|")
  RECORDS+=("TXT|${ROOT_DOMAIN}|v=spf1 mx ~all|")
  RECORDS+=("TXT|dkim._domainkey.${ROOT_DOMAIN}|$(dkim_txt_value)|")
  RECORDS+=("TXT|_dmarc.${ROOT_DOMAIN}|v=DMARC1; p=quarantine; adkim=r; aspf=r|")
}

print_records_table() {
  hr
  printf '%-6s %-34s %s\n' "TIPO" "NOMBRE" "VALOR"
  hr
  local r type name val prio
  for r in "${RECORDS[@]}"; do
    IFS='|' read -r type name val prio <<< "$r"
    [ "$type" = "MX" ] && val="${prio} ${val}"
    printf '%-6s %-34s %s\n' "$type" "$name" "$val"
  done
  hr
  cat <<'EOF'
Notas:
  • Cloudflare: el registro A debe ir en modo "DNS only" (nube GRIS, sin proxy).
    Cloudflare no hace proxy de SMTP y el objetivo del MX debe resolver a la IP real.
  • Otros proveedores: crea los registros tal cual. El punto final del MX
    (app.dominio.) es opcional en la mayoría de paneles.
  • TTL: usa el mínimo que permita tu proveedor mientras pruebas.
EOF
}

# ── Cloudflare API ─────────────────────────────────────────────────────────
cf_api() {  # cf_api METHOD PATH [JSON_BODY]
  local method="$1" path="$2" body="${3:-}"
  if [ -n "$body" ]; then
    curl -sS -X "$method" "https://api.cloudflare.com/client/v4/${path}" \
      -H "Authorization: Bearer ${CF_API_TOKEN}" \
      -H "Content-Type: application/json" --data "$body"
  else
    curl -sS -X "$method" "https://api.cloudflare.com/client/v4/${path}" \
      -H "Authorization: Bearer ${CF_API_TOKEN}"
  fi
}

cf_resolve_zone() {
  local candidate="${CF_ZONE_NAME:-$ROOT_DOMAIN}"
  # prueba el dominio y hasta 2 niveles superiores
  for _ in 1 2 3; do
    local id
    id="$(cf_api GET "zones?name=${candidate}&status=active" | jq -r '.result[0].id // empty')"
    if [ -n "$id" ]; then ZONE_ID="$id"; CF_ZONE_NAME="$candidate"; return 0; fi
    case "$candidate" in
      *.*.*) candidate="${candidate#*.}" ;;
      *) break ;;
    esac
  done
  return 1
}

cf_upsert() {  # cf_upsert TYPE NAME CONTENT [PRIORITY]
  local type="$1" name="$2" content="$3" prio="${4:-}"
  local rec_id body
  rec_id="$(cf_api GET "zones/${ZONE_ID}/dns_records?type=${type}&name=${name}" \
            | jq -r '.result[0].id // empty')"
  if [ -n "$prio" ]; then
    body="$(jq -nc --arg t "$type" --arg n "$name" --arg c "$content" --argjson p "$prio" \
      '{type:$t,name:$n,content:$c,ttl:1,priority:$p,proxied:false}')"
  else
    body="$(jq -nc --arg t "$type" --arg n "$name" --arg c "$content" \
      '{type:$t,name:$n,content:$c,ttl:1,proxied:false}')"
  fi
  local resp ok_flag
  if [ -n "$rec_id" ]; then
    resp="$(cf_api PUT "zones/${ZONE_ID}/dns_records/${rec_id}" "$body")"
  else
    resp="$(cf_api POST "zones/${ZONE_ID}/dns_records" "$body")"
  fi
  ok_flag="$(printf '%s' "$resp" | jq -r '.success')"
  if [ "$ok_flag" = "true" ]; then
    ok "${type} ${name}"
  else
    err "${type} ${name}: $(printf '%s' "$resp" | jq -c '.errors')"
    return 1
  fi
}

cloudflare_apply() {
  require_cmd jq; require_cmd curl
  step "Cloudflare — publicando registros por API"
  if ! cf_resolve_zone; then
    die "No encuentro la zona en Cloudflare (CF_ZONE_NAME='${CF_ZONE_NAME:-$ROOT_DOMAIN}'). ¿Token válido? ¿Zona activa?"
  fi
  ok "zona: ${CF_ZONE_NAME} (${ZONE_ID})"
  local r type name val prio rc=0
  for r in "${RECORDS[@]}"; do
    IFS='|' read -r type name val prio <<< "$r"
    cf_upsert "$type" "$name" "$val" "$prio" || rc=1
  done
  [ "$rc" -eq 0 ] || warn "Algún registro falló; revísalo en el panel de Cloudflare."
}

cf_delete() {  # cf_delete TYPE NAME
  local type="$1" name="$2" rec_id resp
  rec_id="$(cf_api GET "zones/${ZONE_ID}/dns_records?type=${type}&name=${name}" \
            | jq -r '.result[0].id // empty')"
  if [ -z "$rec_id" ]; then log "${type} ${name}: no existe (nada que borrar)"; return 0; fi
  resp="$(cf_api DELETE "zones/${ZONE_ID}/dns_records/${rec_id}")"
  if [ "$(printf '%s' "$resp" | jq -r '.success')" = "true" ]; then
    ok "borrado ${type} ${name}"
  else
    err "no se pudo borrar ${type} ${name}: $(printf '%s' "$resp" | jq -c '.errors')"; return 1
  fi
}

cloudflare_remove() {
  require_cmd jq; require_cmd curl
  step "Cloudflare — borrando los registros de SimpleLogin por API"
  cf_resolve_zone || { warn "no encuentro la zona; borra los registros a mano"; return 1; }
  ok "zona: ${CF_ZONE_NAME} (${ZONE_ID})"
  local r type name val prio
  for r in "${RECORDS[@]}"; do
    IFS='|' read -r type name val prio <<< "$r"
    cf_delete "$type" "$name" || true
  done
}

# ── Verificación con dig ───────────────────────────────────────────────────
_norm() { printf '%s' "$1" | tr -d '"' | tr '[:upper:]' '[:lower:]' | tr -s ' '; }

verify_one() {  # verify_one DESC TYPE NAME REGEX  -> 0/1
  local desc="$1" type="$2" name="$3" re="$4" got
  got="$(sl_dig "$type" "$name" | tr '\n' ' ')"
  got="$(_norm "$got")"
  if printf '%s' "$got" | grep -qiE "$re"; then
    ok "${desc}"
    return 0
  fi
  warn "${desc}: obtenido '${got:-<vacío>}'"
  return 1
}

verify_dns() {  # verify_dns [strict]  -> 0 si MX y A ok
  step "Verificando DNS (dig @1.1.1.1)"
  local reip; reip="$(printf '%s' "$SERVER_IP" | sed 's/\./\\./g')"
  local rehost; rehost="$(printf '%s' "$APP_HOSTNAME" | sed 's/\./\\./g')"
  local dkim_b64; dkim_b64="$(dkim_pubkey_b64 | tr '[:upper:]' '[:lower:]')"
  local dkim_head="${dkim_b64:0:24}"

  local mx_ok=1 a_ok=1
  verify_one "MX  ${ROOT_DOMAIN} -> ${APP_HOSTNAME}" MX  "$ROOT_DOMAIN" "10 ${rehost}\.?" || mx_ok=0
  verify_one "A   ${APP_HOSTNAME} -> ${SERVER_IP}"   A   "$APP_HOSTNAME" "(^| )${reip}( |$)" || a_ok=0
  verify_one "TXT SPF"   TXT "$ROOT_DOMAIN"                    "v=spf1.*mx" || true
  verify_one "TXT DKIM"  TXT "dkim._domainkey.$ROOT_DOMAIN"   "v=dkim1.*${dkim_head}" || true
  verify_one "TXT DMARC" TXT "_dmarc.$ROOT_DOMAIN"            "v=dmarc1" || true

  if [ "$mx_ok" = 1 ] && [ "$a_ok" = 1 ]; then
    ok "Registros críticos (MX + A) correctos"
    return 0
  fi
  warn "MX y/o A todavía no resuelven. La propagación puede tardar (habitualmente < 5 min)."
  return 1
}

# Bucle de espera para MX + A
wait_for_dns() {
  local tries="${1:-20}" i=1
  while [ "$i" -le "$tries" ]; do
    if verify_dns; then return 0; fi
    log "reintento ${i}/${tries} en 30s ..."
    sleep 30
    i=$((i+1))
  done
  return 1
}

reverse_dns_notice() {
  cat <<EOF

${C_YEL}PTR / DNS inverso${C_RESET}
  El registro PTR de ${SERVER_IP} debería resolver a ${APP_HOSTNAME}.
  Esto NO se configura en el DNS del dominio: hazlo en el panel de tu proveedor
  de hosting/VPS (o pídeselo al ISP). Sin un PTR correcto muchos destinos
  marcarán tu correo como spam o lo rechazarán.

  Comprobar:  dig +short -x ${SERVER_IP}
EOF
}

# shellcheck shell=bash
# Comprobación y apertura de puertos + test del puerto 25 saliente.

REQUIRED_INBOUND=(25 80)          # 443 se añade si Caddy
port_in_use_locally() {
  local p="$1"
  if has_cmd ss; then ss -ltn 2>/dev/null | grep -qE "[:.]${p}\b"
  elif has_cmd netstat; then netstat -ltn 2>/dev/null | grep -qE "[:.]${p}\b"
  else return 1; fi
}

check_local_port_conflicts() {
  step "Puertos en uso en el host"
  local ports=(25)
  [ "${DEPLOY_MODE:-simple}" != simple ] && ports+=(80 443)
  local p conflict=0
  for p in "${ports[@]}"; do
    if port_in_use_locally "$p"; then
      # ¿es ya un contenedor de este stack?
      if docker ps --format '{{.Ports}}' 2>/dev/null | grep -qE ":${p}->"; then
        ok "puerto ${p}: lo publica un contenedor Docker (ok si es este stack)"
      else
        err "puerto ${p} ya ocupado por otro proceso del host (p.ej. postfix/nginx del sistema). Deténlo: systemctl stop postfix nginx"
        conflict=1
      fi
    else
      ok "puerto ${p} libre"
    fi
  done
  [ "$conflict" -eq 0 ] || warn "Resuelve los conflictos de puertos antes de continuar."
}

open_firewall() {
  step "Firewall (puertos entrantes)"
  local ports=(22 25)
  [ "${DEPLOY_MODE:-simple}" != simple ] && ports+=(80 443)
  [ "${POSTFIX_SUBMISSION:-0}" = "1" ] && ports+=(587)

  if has_cmd ufw && ufw status 2>/dev/null | grep -qi active; then
    log "UFW activo. Se abrirán: ${ports[*]}"
    if confirm "¿Abrir esos puertos en UFW ahora?"; then
      local p; for p in "${ports[@]}"; do sudo ufw allow "$p" >/dev/null && ok "ufw allow $p"; done
    fi
  elif has_cmd firewall-cmd && firewall-cmd --state 2>/dev/null | grep -qi running; then
    log "firewalld activo. Se abrirán: ${ports[*]}"
    if confirm "¿Abrir esos puertos en firewalld ahora?"; then
      local p; for p in "${ports[@]}"; do
        sudo firewall-cmd --permanent --add-port="${p}/tcp" >/dev/null && ok "firewalld +${p}/tcp"
      done
      sudo firewall-cmd --reload >/dev/null
    fi
  else
    warn "No detecto UFW/firewalld activos. Asegúrate en tu proveedor (Security Groups / panel del VPS) de abrir: ${ports[*]}"
  fi
}

close_firewall() {
  step "Firewall — cerrar puertos de SimpleLogin"
  # 22 NUNCA se toca (SSH). El resto según el modo/submission.
  local ports=(25)
  [ "${DEPLOY_MODE:-simple}" != simple ] && ports+=(80 443)
  [ "${POSTFIX_SUBMISSION:-0}" = "1" ] && ports+=(587)

  if has_cmd ufw && ufw status 2>/dev/null | grep -qi active; then
    if confirm "¿Quitar de UFW las reglas allow para ${ports[*]}? (22/SSH no se toca)"; then
      local p; for p in "${ports[@]}"; do sudo ufw delete allow "$p" >/dev/null 2>&1 && ok "ufw delete allow $p"; done
    fi
  elif has_cmd firewall-cmd && firewall-cmd --state 2>/dev/null | grep -qi running; then
    if confirm "¿Quitar de firewalld los puertos ${ports[*]}/tcp? (22/SSH no se toca)"; then
      local p; for p in "${ports[@]}"; do
        sudo firewall-cmd --permanent --remove-port="${p}/tcp" >/dev/null 2>&1 && ok "firewalld -${p}/tcp"
      done
      sudo firewall-cmd --reload >/dev/null
    fi
  else
    warn "Sin UFW/firewalld activos. Si abriste puertos en el panel de tu VPS, ciérralos a mano: ${ports[*]}"
  fi
}

check_outbound_25() {
  step "Puerto 25 saliente (envío de correo)"
  local hosts=(aspmx.l.google.com alt1.aspmx.l.google.com)
  local h
  for h in "${hosts[@]}"; do
    if tcp_check "$h" 25 6; then
      ok "conexión saliente a ${h}:25 correcta"
      return 0
    fi
  done
  warn "No se puede conectar al puerto 25 saliente."
  cat <<EOF
  Muchos ISP/VPS bloquean el puerto 25 de salida. Sin él, SimpleLogin no puede
  entregar correo directamente. Opciones:
    1) Pide a tu proveedor que desbloquee el puerto 25 saliente.
    2) Usa un relay SMTP (Gmail, Amazon SES, Mailgun, Brevo...):
       define en .env  RELAY_HOST / RELAY_USER / RELAY_PASSWORD
       y añade a simplelogin.env:  POSTFIX_PORT=587  y  POSTFIX_SUBMISSION_TLS=true
  Guías: ../../docs/gmail-relay.md  ·  ../../docs/ses.md
EOF
  return 1
}

# Modo `caddy`

Reverse proxy [Caddy](https://caddyserver.com/) delante del webapp, con
**HTTPS automático** de Let's Encrypt (obtención y renovación del certificado sin
intervención).

## Activar

```bash
./install.sh --mode caddy       # en una instalación nueva
# o, sobre una existente:
./manage.sh set-mode caddy
```

Requiere en `.env`: `DEPLOY_MODE=caddy` y `ACME_EMAIL=<tu-email>`.
`install.sh` los pone por ti y deja `URL=https://APP_HOSTNAME` en `simplelogin.env`.

## Qué añade

- Contenedor `caddy` con los puertos **80** y **443** publicados.
- `caddy/Caddyfile` (renderizado desde `Caddyfile.template`): `reverse_proxy
  app:7777` + cabeceras de seguridad (HSTS, `X-Frame-Options`, …).
- Volúmenes `caddy_data` / `caddy_config` (certificados y estado de ACME).

## Requisitos previos

- Puertos 80 y 443 abiertos en el firewall y **apuntando a este servidor**.
- El registro **A** de `APP_HOSTNAME` ya propagado (Caddy valida el dominio por
  HTTP-01 antes de emitir el certificado).

## Ficheros

| | |
|---|---|
| `docker-compose.caddy.yml` | override que añade el servicio `caddy` |
| `Caddyfile.template` | plantilla; `install.sh` genera `Caddyfile` (git-ignored) |

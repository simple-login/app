# Modo `traefik`

Reverse proxy [Traefik v3](https://traefik.io/traefik/) delante del webapp, con
**HTTPS automático** de Let's Encrypt (challenge HTTP-01, renovación automática).

Equivalente funcional al modo [`caddy`](../caddy/README.md); elige el que ya
conozcas o el que encaje con tu infraestructura.

## Activar

```bash
./install.sh --mode traefik      # en una instalación nueva
# o, sobre una existente:
./manage.sh set-mode traefik
```

Requiere en `.env`: `DEPLOY_MODE=traefik` y `ACME_EMAIL=<tu-email>`.
`install.sh` los pone por ti y deja `URL=https://APP_HOSTNAME` en `simplelogin.env`.

## Qué añade

- Contenedor `traefik` con los puertos **80** y **443** publicados.
- `traefik/traefik.yml` (config estática, desde `traefik.yml.template`):
  entrypoints `web`/`websecure`, redirección 80→443 y el resolver ACME `le`.
- `traefik/dynamic.yml` (routers, desde `dynamic.yml.template`): enruta
  `Host(APP_HOSTNAME)` → `app:7777` con `tls.certResolver=le` y cabeceras de
  seguridad (HSTS, nosniff, `frameDeny`).
- Volumen `traefik_letsencrypt` (`/letsencrypt/acme.json`).
- Usa el **file provider**, no monta el socket de Docker.

## Requisitos previos

- Puertos 80 y 443 abiertos y **apuntando a este servidor**.
- El registro **A** de `APP_HOSTNAME` ya propagado (Let's Encrypt valida por
  HTTP-01 en el puerto 80).

## BYO certificado (sin ACME)

Si prefieres montar tus propios `.pem`: sustituye el bloque `certificatesResolvers`
de `traefik.yml` y en `dynamic.yml` cambia `tls: { certResolver: le }` por un
bloque `tls.certificates` apuntando a los ficheros que montes en el contenedor.

## Ficheros

| | |
|---|---|
| `docker-compose.traefik.yml` | override que añade el servicio `traefik` |
| `traefik.yml.template` / `dynamic.yml.template` | plantillas; `install.sh` genera `traefik.yml` y `dynamic.yml` (git-ignored) |

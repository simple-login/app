# `.docker/` — despliegues dockerizados de SimpleLogin

Dos carpetas independientes:

| Carpeta | Para qué |
|---------|----------|
| [`demo/`](demo/README.md) | **Demo local** en tu máquina, sin dominio ni DNS reales. Traefik + `*.traefik.me` para HTTPS local y Mailpit para ver todo el correo (activación, reenvíos de alias…). Un solo script: `./demo/demo.sh`. |
| [`selfhosted/`](selfhosted/README.md) | **Despliegue real** en un servidor. Instalador guiado (`install.sh`) + operación (`manage.sh`). Tres modos de reverse proxy / TLS. |

## `selfhosted/` — modos de despliegue

El núcleo (compose, Postfix, cron, scripts, `lib/`) es común; cada modo añade
—o no— un reverse proxy:

| Modo | Carpeta | TLS |
|------|---------|-----|
| `simple`  | [`selfhosted/simple/`](selfhosted/simple/README.md)   | ninguno — webapp en `127.0.0.1:7777`, pones tu proxy delante |
| `caddy`   | [`selfhosted/caddy/`](selfhosted/caddy/README.md)     | Caddy + Let's Encrypt automático |
| `traefik` | [`selfhosted/traefik/`](selfhosted/traefik/README.md) | Traefik v3 + Let's Encrypt automático |

```bash
cd .docker/selfhosted
./install.sh --mode caddy      # o simple / traefik, o sin --mode y responde
./manage.sh set-mode traefik   # cambiar de modo más tarde
./uninstall.sh [--purge]       # desinstalar
```

## Estructura

```
.docker/
├── demo/
│   ├── docker-compose.yml        # stack de demo autocontenido (+ traefik + mailpit)
│   ├── demo.sh
│   ├── traefik/dynamic.yml.template
│   └── certs/  data/             # (git-ignored)
└── selfhosted/
    ├── docker-compose.yml        # núcleo: db, app, email, job-runner, postfix, cron…
    ├── install.sh  manage.sh  uninstall.sh
    ├── .env.example  simplelogin.env.template
    ├── lib/                      # preflight, secrets, dns, ports, verify
    ├── postfix/  cron/           # imágenes propias (postfix compartida con la demo)
    ├── simple/                   # solo README (modo por defecto)
    ├── caddy/                    # override + Caddyfile.template + README
    └── traefik/                  # override + traefik.yml/dynamic.yml.template + README
```

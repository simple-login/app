# SimpleLogin — despliegue full-dockerizado

Alternativa 100 % Docker Compose a la instalación "en el host" del
[README raíz](../../README.md). Todo (webapp, email handler, job runner, cron,
**Postfix** y PostgreSQL) corre en contenedores. Un instalador guiado
(`install.sh`) configura claves, DNS, puertos y arranca el stack.

¿Solo quieres verlo funcionar en tu portátil? Usa la
[demo local](../demo/README.md) en su lugar.

```
┌──────────────────────────── host ────────────────────────────┐
│  :25  ───────────────►  postfix ──┐                           │
│  :80/:443 (modo caddy/traefik) ─► proxy ─┼─► app  :7777       │
│                                   │   email  :20381 ◄─────────┤ (postfix → transport)
│                                   │   job-runner              │
│                                   │   cron (perfil)           │
│                                   └─► db  :5432               │
│   red bridge  simplelogin-sl  10.42.0.0/24                    │
│   volúmenes:  ./data/{db,pgp,upload,dkim}                     │
└──────────────────────────────────────────────────────────────┘
```

Tres **modos** de reverse proxy / TLS (carpeta = docs de cada uno):

| Modo | | TLS |
|------|-|-----|
| [`simple/`](simple/README.md)   | por defecto | ninguno — webapp en `127.0.0.1:7777`, pon tu proxy delante |
| [`caddy/`](caddy/README.md)     | | Caddy + Let's Encrypt automático |
| [`traefik/`](traefik/README.md) | | Traefik v3 + Let's Encrypt automático |

## Requisitos

- Un servidor Linux (VM o dedicado), **≥ 2 GB RAM**, Docker Engine + plugin
  `docker compose` v2.
- Puertos entrantes abiertos: **25** (correo), **80**/**443** (webapp, en modo
  `caddy`/`traefik`), **22** (SSH).
- Puerto **25 saliente** disponible (muchos VPS/ISP lo bloquean → ver
  [Puerto 25 bloqueado](#puerto-25-bloqueado)).
- Un dominio cuyo DNS puedas gestionar. En esta guía `example.com` es el dominio
  de los alias y `app.example.com` el del webapp / objetivo del MX.
- Recomendado: `dnsutils`/`bind-utils` (`dig`) y, si vas a usar la API de
  Cloudflare, `jq` y `curl`.

## Quickstart

```bash
cd .docker/selfhosted
./install.sh                 # pregunta el modo (simple/caddy/traefik)
./install.sh --mode caddy    # o fíjalo desde el principio
```

El instalador hace, paso a paso:

| Paso | Qué hace |
|------|----------|
| 1. Configuración | pregunta dominios, IP pública, **modo de proxy**, Cloudflare sí/no → escribe `.env` |
| 2. Claves | crea `data/`, par DKIM (RSA 1024), `FLASK_SECRET`, contraseña de BBDD → renderiza `simplelogin.env` |
| 3. DNS | crea los registros por **API de Cloudflare** *o* los imprime para pegarlos a mano; verifica con `dig` en bucle; recuerda el PTR |
| 4. Puertos | detecta conflictos en el host, abre el firewall (ufw/firewalld), prueba el 25 saliente |
| 5. Build | `docker compose build` de las imágenes `app`, `postfix` y `cron` |
| 6. Arranque | `db` → `alembic upgrade head` → `init_app.py` → `docker compose up -d` |
| 7. Verificación | contenedores, `/health`, `postmap -q`, banner SMTP, match DKIM |

Es **idempotente**: puedes re-lanzarlo.

| Flag | Efecto |
|------|--------|
| `--reconfigure` | vuelve a preguntar todo aunque exista `.env` |
| `--yes` / `-y` | no interactivo (usa `.env` tal cual) |
| `--skip-dns-check` | publica/muestra los registros pero **no** espera a que propaguen (`dig`) |
| `--skip-dns` | omite por completo el paso 3 (gestionas el DNS por tu cuenta) |

En modo interactivo el instalador también **pregunta** antes de verificar el DNS,
así que puedes saltártelo sin flags. Re-verifica cuando quieras con
`./manage.sh verify`.

## Registros DNS

El instalador los calcula a partir de tu configuración. Para `example.com` /
`app.example.com` / IP `203.0.113.10`:

| Tipo | Nombre | Valor |
|------|--------|-------|
| `MX`  | `example.com` | `app.example.com.` (prioridad 10) |
| `A`   | `app.example.com` | `203.0.113.10` |
| `TXT` | `example.com` | `v=spf1 mx ~all` |
| `TXT` | `dkim._domainkey.example.com` | `v=DKIM1; k=rsa; p=<clave pública>` |
| `TXT` | `_dmarc.example.com` | `v=DMARC1; p=quarantine; adkim=r; aspf=r` |

### Cloudflare

- El instalador usa la API si defines `CF_API_TOKEN` (permisos **Zone.DNS:Edit**
  + **Zone:Read**). Crea/actualiza los registros de forma idempotente.
- El registro **A debe ir en "DNS only" (nube gris)**. Cloudflare no hace proxy
  de SMTP y el objetivo del MX tiene que resolver a la IP real del servidor.
- Comprueba el token: <https://dash.cloudflare.com/profile/api-tokens>.

### Otros proveedores

Modo manual (`./install.sh` sin `CF_API_TOKEN`): el script imprime la tabla
exacta y espera a que confirmes. Crea los registros en tu panel y el script los
verifica con `dig @1.1.1.1`.

### PTR / DNS inverso

`dig +short -x <IP>` debe devolver `app.example.com`. **No se configura en el DNS
del dominio**: hazlo en el panel de tu proveedor de VPS/hosting o pídeselo al
ISP. Sin PTR correcto, buena parte de tu correo irá a spam.

## Reverse proxy / TLS

El modo se guarda en `DEPLOY_MODE` (`.env`) y lo elige `install.sh`. Para
cambiarlo después:

```bash
./manage.sh set-mode caddy      # simple | caddy | traefik
```

| Modo | Qué hace | Necesita |
|------|----------|----------|
| `simple`  | webapp en `127.0.0.1:7777`; tú pones nginx/HAProxy/… delante | nada extra — ver [`simple/`](simple/README.md) |
| `caddy`   | contenedor Caddy, HTTPS automático (Let's Encrypt) | `ACME_EMAIL` + 80/443 abiertos + A propagado — ver [`caddy/`](caddy/README.md) |
| `traefik` | contenedor Traefik v3, HTTPS automático (Let's Encrypt) | ídem — ver [`traefik/`](traefik/README.md) |

`caddy` y `traefik` son equivalentes; elige el que ya conozcas. Ambos dejan
`URL=https://APP_HOSTNAME` en `simplelogin.env`.

## Puerto 25 bloqueado

Si `./install.sh` avisa de que no puede salir por el puerto 25:

1. Pide a tu proveedor que lo desbloquee, **o**
2. Usa un relay SMTP (Gmail, Amazon SES, Mailgun, Brevo…):

```bash
# en .env
RELAY_HOST=[smtp.gmail.com]:587
RELAY_USER=tucuenta@gmail.com
RELAY_PASSWORD=app-password
```

y añade a `simplelogin.env`: `POSTFIX_PORT=587` y `POSTFIX_SUBMISSION_TLS=true`.
Reconstruye Postfix: `./manage.sh build && ./manage.sh restart postfix`.
Guías detalladas: [`../../docs/gmail-relay.md`](../../docs/gmail-relay.md),
[`../../docs/ses.md`](../../docs/ses.md).

## Operación

```bash
./manage.sh ps                     # estado
./manage.sh logs email -f          # seguir logs del email handler
./manage.sh verify                 # re-ejecutar comprobaciones
./manage.sh restart [servicio]
./manage.sh make-premium tu@email  # alias ilimitados
./manage.sh activate tu@email      # activar cuenta sin el email de confirmación
./manage.sh activation-link tu@email  # imprimir el enlace de activación pendiente
./manage.sh disable-registration   # cerrar altas cuando termines
./manage.sh set-mode traefik       # cambiar de reverse proxy (simple/caddy/traefik)
./manage.sh upgrade                # git pull + build + migración + up
./manage.sh backup                 # pg_dump + tar de data/  ->  ./backups/
./manage.sh restore backups/db-XXXX.sql.gz
./manage.sh shell                  # python shell.py
./manage.sh psql
```

### Cron de mantenimiento

Perfil opcional (recomendado) que ejecuta `cron.py` periódicamente
(equivalente a [`../../crontab.yml`](../../crontab.yml)):

```bash
./manage.sh up            # lo incluye si ENABLE_CRON=1 en .env
# o puntualmente:
docker compose --project-directory . --profile cron up -d cron
```

## Activar una cuenta sin recibir el email

En una instancia self-hosted el primer registro necesita confirmar el email, pero
si has usado un buzón que no controlas (o Postfix aún no entrega correo) el
mensaje no llega. Opciones:

```bash
./manage.sh activate tu@email          # marca la cuenta como activada
./manage.sh activation-link tu@email   # imprime el enlace /auth/activate?code=…
```

O a mano con `./manage.sh psql`:

```sql
UPDATE users SET activated = TRUE WHERE email = 'tu@email';
-- o, para ver el código y construir  <URL>/auth/activate?code=<code>
SELECT ac.code FROM activation_code ac JOIN users u ON u.id = ac.user_id
 WHERE u.email = 'tu@email' ORDER BY ac.id DESC LIMIT 1;
```

> SimpleLogin **rechaza en el registro** los dominios sin MX real (`@algo.test`,
> `@admin.admin`…). Usa un dominio real aunque la parte local sea inventada
> (`loquesea@gmail.com`); el correo de activación se envía a donde apunte
> `POSTFIX_SERVER`.

Para la cuenta real usa un **buzón que controles**: SimpleLogin manda ahí el
reset de contraseña, las alertas de seguridad y, sobre todo, la verificación de
mailbox que necesitas para que un alias reenvíe a tu buzón.

## Demo local

Para probar SimpleLogin sin dominio ni DNS (Traefik + `*.traefik.me` + Mailpit,
incluido probar el **reenvío de un alias** en local), usa
[`../demo/`](../demo/README.md):

```bash
cd ../demo && ./demo.sh
```

## Actualizar

```bash
git pull
./manage.sh upgrade
```

No se pierde ningún dato. Si una versión mayor requiere migración manual, sigue
primero [`../../docs/upgrade.md`](../../docs/upgrade.md).

## Desinstalar

```bash
./uninstall.sh            # para y elimina contenedores + red (conserva data/, imágenes, config)
./uninstall.sh --purge    # + borra data/, config generada, imágenes y volúmenes
./uninstall.sh --purge --yes    # sin preguntar (IRREVERSIBLE)
```

Durante `--purge` ofrece (preguntando): un **backup** previo (`manage.sh backup`),
**cerrar** los puertos del firewall que abrió el instalador (el 22/SSH nunca se
toca) y **borrar** los registros DNS de Cloudflare si hay `CF_API_TOKEN` en
`.env`. Nunca borra `backups/` ni el PTR (ese lo quitas en tu proveedor).

## Backup / restauración

- `./manage.sh backup` genera en `./backups/`: `db-<ts>.sql.gz` (pg_dump),
  `data-<ts>.tar.gz` (PGP, uploads, DKIM) y copia de `.env` / `simplelogin.env`.
- Guarda **también** `data/dkim/` fuera del servidor: si pierdes la clave DKIM
  tendrás que republicar el registro TXT.
- PostgreSQL está fijado a la major **14**. Cambiar de major exige dump + restore.

## Troubleshooting

| Síntoma | Comprobación |
|---------|--------------|
| No llega el email de bienvenida | `./manage.sh logs email`; ¿Postfix puede entregar a tu buzón? (25 saliente / relay) |
| Envías a un alias y no reenvía | `docker compose exec postfix postmap -q example.com pgsql:/etc/postfix/pgsql-relay-domains.cf` → debe devolver `example.com`; `…/pgsql-transport-maps.cf` → `smtp:email:20381` |
| Postfix no arranca | `./manage.sh logs postfix`; ¿`db` healthy?, ¿variables `APP_HOSTNAME`/`ROOT_DOMAIN` en `.env`? |
| Webapp 502 / no carga | `./manage.sh logs app`; `./manage.sh verify` |
| DKIM en spam | `./manage.sh verify` compara la clave publicada con la local; revisa SPF/DMARC/PTR |
| Cambié `simplelogin.env` | `./manage.sh restart app email job-runner` |

Referencia general: [`../../docs/troubleshooting.md`](../../docs/troubleshooting.md).

## Ficheros

| Fichero | Rol |
|---------|-----|
| `docker-compose.yml` | stack del núcleo (db, app, email, job-runner, postfix, cron…) |
| `.env` / `.env.example` | variables del despliegue (interpolación de compose) — **secreto** |
| `simplelogin.env` / `.template` | config de la app, montada en los contenedores — **secreto** |
| `install.sh` | instalador guiado (`--mode simple\|caddy\|traefik`) |
| `manage.sh` | operaciones del día a día |
| `uninstall.sh` | desinstalador (`--purge` borra datos e imágenes) |
| `lib/*.sh` | preflight, secrets, dns, ports, verify |
| `postfix/` | imagen de Postfix (ubuntu + postfix-pgsql/pcre) — compartida con la demo |
| `cron/` | imagen del cron de mantenimiento (supercronic) |
| `simple/` `caddy/` `traefik/` | docs + (caddy/traefik) override de compose y plantillas del proxy |
| `data/` | estado persistente (git-ignored) |

La demo local vive aparte, en [`../demo/`](../demo/README.md).

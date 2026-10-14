# Modo `simple`

Sin reverse proxy. El webapp escucha en **`127.0.0.1:7777`** y tú pones tu propio
proxy / terminación TLS delante (nginx, HAProxy, Traefik externo, el balanceador
de tu proveedor…), o lo sirves en HTTP plano si es una red interna.

Es el modo **por defecto** (`DEPLOY_MODE=simple`): el `docker-compose.yml` del
núcleo ya publica `127.0.0.1:7777` y no hay nada que añadir — por eso esta
carpeta solo contiene este README.

## Activar

```bash
./install.sh --mode simple      # o simplemente ./install.sh y responde "simple"
```

Con este modo `install.sh` deja `URL=http://APP_HOSTNAME` en `simplelogin.env`.
Si tu proxy termina TLS, cambia a `URL=https://APP_HOSTNAME` (edita
`simplelogin.env` y `./manage.sh restart app email job-runner`) y añade
`URL_SCHEME=https` a `.env`.

## Tu proxy debe

- reenviar a `http://127.0.0.1:7777`
- preservar el `Host` original
- enviar `X-Forwarded-For` (el webapp lo respeta vía `ProxyFix`)

Ejemplo mínimo con nginx:

```nginx
server {
    server_name app.midominio.com;
    location / {
        proxy_pass       http://127.0.0.1:7777;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Para TLS con Let's Encrypt gestionado por el propio stack, usa el modo
[`caddy`](../caddy/README.md) o [`traefik`](../traefik/README.md).

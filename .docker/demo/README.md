# SimpleLogin — demo local

Entorno de **demostración** que corre entero en tu máquina, **sin dominio ni DNS
reales**. Para el despliegue de verdad usa [`../selfhosted/`](../selfhosted/README.md).

```bash
cd .docker/demo
./demo.sh                 # arranca
./demo.sh send-test <alias@slapp.traefik.me>
./demo.sh down            # para (conserva datos)
./demo.sh destroy         # para y borra todo
```

## Qué levanta

| Servicio | |
|---|---|
| `traefik` | sirve el webapp por HTTPS en `https://slapp.traefik.me/` |
| `mailpit` | `https://slmail.traefik.me/` — captura **todo** el correo |
| `db` `app` `email` `job-runner` | el stack de SimpleLogin |
| `postfix` | **sin** publicar el `:25`, con `relayhost = [mailpit]:1025` |

- **`*.traefik.me` resuelve a `127.0.0.1`** (servicio público): cero configuración
  de DNS o `/etc/hosts`. Solo accesible desde esta máquina.
- Certificado **autofirmado** para `*.traefik.me` (un aviso del navegador la
  primera vez). Si tienes un wildcard válido, pásalo con `DEMO_CERT_URL` /
  `DEMO_KEY_URL`.
- La imagen de la app se construye desde el repo (`../..`); la de Postfix desde
  [`../selfhosted/postfix`](../selfhosted/postfix). Son las mismas que usa el
  despliegue real.
- Datos aislados en `.docker/demo/data/` (no comparte nada con `../selfhosted`).

## Flujo completo

```bash
./demo.sh
# 1) https://slapp.traefik.me/   -> regístrate con  loquesea@gmail.com
#    (dominio con MX real; SimpleLogin rechaza dominios sin MX. El correo va a
#     Mailpit, no a Gmail.)
# 2) https://slmail.traefik.me/  -> abre el email y pincha el enlace de activación
#    (o:  ./demo.sh activate loquesea@gmail.com)
./demo.sh make-premium loquesea@gmail.com
# 3) crea un alias en el panel, p.ej.  giddy_army355@slapp.traefik.me
./demo.sh send-test giddy_army355@slapp.traefik.me
# 4) https://slmail.traefik.me/  -> ves el correo reenviado a tu buzón
```

`send-test` mete un correo en `postfix:25` dirigido al alias:
`postfix → transport_maps → email_handler → forward al buzón → postfix → Mailpit`.

## Limitaciones

- Recibir correo de fuera de la máquina no es posible (sin MX real): por eso
  existe `send-test`.
- No ejecutes la demo y `../selfhosted` a la vez: ambos usan los puertos 80/443.

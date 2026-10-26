# Instalación avanzada: Python a pelo, sin Docker

El camino oficial es `./instalar.sh` (ver el [README](../README.md)). Esto es para quien no puede o no quiere usar Docker. Sin Docker no hay HTTPS automático ni vigilante: eso lo pones tú (un proxy inverso como Caddy o nginx delante).

## Requisitos

- **Python 3.10 o superior.** El servidor usa solo la biblioteca estándar.
- Para subir fotos desde el backoffice y generar los iconos de la app: `pip install pillow numpy scipy`. Sin ellos todo lo demás funciona; solo falla la subida de fotos.
- `openssl` y, para el aviso a Apple Wallet con credenciales reales, `curl` con HTTP/2 (ambos suelen venir ya en el sistema).

## Arrancar

```
git clone https://github.com/gastro-360/gastro-360.git
cd gastro-360/carta
export RESTAURANTE=demo            # la carpeta de restaurantes/<local>/ que quieras servir
export CLAVE_BACKOFFICE='una-clave-larga'   # opcional; ver «Clave» más abajo
python3 preparar_netlify.py        # genera carta/web/ (la primera vez y tras cambiar la carta a mano)
python3 servidor.py                # http://localhost:8080/  ·  /admin  ·  /cocina
```

Un restaurante propio: `python3 nuevo_restaurante.py bar-pepe --nombre "Bar Pepe"` y `export RESTAURANTE=bar-pepe`.

### Variables de entorno

| Variable | Qué hace | Por defecto |
|---|---|---|
| `RESTAURANTE` | Qué restaurante sirve | `demo` |
| `PUERTO` / `ESCUCHAR` | Puerto y dirección de escucha (usa `127.0.0.1` si hay un proxy delante) | `8080` / `0.0.0.0` |
| `CLAVE_BACKOFFICE` | Contraseña del backoffice; solo se usa si el restaurante aún no tiene una | al azar, en `clave_inicial.txt` |
| `PROXY_CONFIABLE` | Proxies de confianza (IP, red CIDR o nombre de host, separados por comas): solo de ellos se leen `X-Forwarded-For`, `CF-Connecting-IP` y `X-Forwarded-Proto` (IP real y https). El compose pone `caddy`. Nunca expongas `app:8080` | sin definir (se usa la IP del socket) |
| `CONFIAR_CF` | `1`: usar `CF-Connecting-IP` como IP real (solo viene de un `PROXY_CONFIABLE`). Actívala solo si delante hay Cloudflare (túnel o proxy naranja) y el proxy no es accesible salvo por Cloudflare; si no, cualquiera inventa la cabecera y evade los frenos | sin definir (se ignora) |
| `URL_PUBLICA` | Dirección pública (`https://tu-dominio`); la llevan las tarjetas de Wallet | vacía |
| `COPIA_HORAS` | Cada cuántas horas se copian los pedidos | `6` |
| `MAX_PEDIDOS_IP` | Freno de pedidos por IP | `10` |
| `MAX_RESERVAS_IP` | Freno de reservas por IP (cupo aparte del de pedidos) | `10` |
| `CARTA_RESTAURANTES`, `CARTA_WEB` | Dónde están los restaurantes y la carpeta `web/` generada | `restaurantes/` y `carta/web/` del clon |
| `BREVO_API_KEY`, `BREVO_REMITENTE` | Correo de promociones (Brevo) | vacías |
| `WALLET_DIR` | Carpeta de credenciales de Wallet | `restaurantes/<local>/wallet/` |
| `CONFIRMACION_DOBLE` | `1`: el permiso de publicidad exige confirmar por correo (enlace de un solo uso; hace falta canal de correo y `URL_PUBLICA`). Vacío o `0`: alta directa al marcar la casilla (suficiente para la LSSI art. 21) | sin definir (alta directa) |
| `CORREO_MODO`, `WALLET_MODO` | `prueba`: simulan correo y Wallet (nada sale a Internet). Solo para probar | sin definir |

> **Detrás de un proxy, `PROXY_CONFIABLE` no puede quedar vacío.** Sin ella todas las visitas llegan con la IP del proxy: comparten el mismo freno de pedidos y de intentos de contraseña, y el dueño puede quedar bloqueado junto con los clientes. Con un túnel Cloudflare (cloudflared) delante de Caddy, Caddy reescribe `X-Forwarded-For` con la IP de cloudflared; para que la app use `CF-Connecting-IP` pon `PROXY_CONFIABLE=<nombre del servicio Caddy>` (p. ej. `qa-proxy`) **y** `CONFIAR_CF=1`; ese Caddy no debe borrar `CF-Connecting-IP` (el `docker/Caddyfile` de este repo la borra a propósito, porque el compose por defecto no va detrás de Cloudflare), y solo si el proxy no es accesible salvo por Cloudflare.

Las variables se leen del entorno del proceso; no hay `.env` automático fuera de Docker (usa `set -a; . ./mi.env; set +a`, con ese archivo fuera de git).

### Clave

La primera vez, si no pones `CLAVE_BACKOFFICE`, el servidor crea una al azar, la muestra y la guarda en `restaurantes/<local>/clave_inicial.txt`. Cambiarla: `python3 servidor.py --clave NUEVA`.

## Dónde guarda los datos

Todo lo del día a día queda dentro de `restaurantes/<local>/` (o de `CARTA_RESTAURANTES`): `datos.json`/`datos.js` (la carta), `fotos/`, `marca.json`, y lo que genera el uso: `config.json` (contraseña), `sesiones.json`, `pedidos.json`, `historial/`, `ajustes.json`, `clientes.db`, `sellos.db`, `kpis.db`, `promociones.db`, `copias/`, `copias_pedidos/` y `wallet/`. Nada de eso entra en git.

## Copia de seguridad

Con el servidor parado (o aunque esté en marcha, para la carta y los pedidos), copia la carpeta entera del restaurante:

```
tar czf copia-$(date +%F).tgz restaurantes/<local>
```

Las bases `*.db` guardan la prueba del permiso de los clientes y los sellos: son las que no se pueden perder. El servidor ya guarda copias de `datos.json` (`copias/`) y de los pedidos (`copias_pedidos/`), pero en el mismo disco: sácalas fuera del servidor.

## Qué falta sin credenciales (y cómo se activa)

Una instalación recién hecha no tiene cuentas de terceros y no simula nada. La carta, la cocina, los pedidos, las mesas y la tarjeta de sellos como página web funcionan; esto no, y el backoffice lo dice en su pestaña:

- **Promociones por correo**: «no disponible, faltan las credenciales de Brevo». Se activa creando una cuenta en Brevo, validando un remitente y poniendo `BREVO_API_KEY` y `BREVO_REMITENTE` en el entorno.
- **Apple Wallet y Google Wallet**: «no disponible, faltan las credenciales». Hacen falta una cuenta de Apple Developer (certificado del pase y WWDR en `restaurantes/<local>/wallet/apple/`) y una cuenta emisora de Google Wallet (cuenta de servicio en `restaurantes/<local>/wallet/google/`), más `URL_PUBLICA` con HTTPS. Detalle en el [manual técnico](MANUAL.md#tarjeta-de-sellos-y-wallet).
- **Botón de reseña de Google**: no sale hasta que `marca.json` lleve el `google_place_id` del local.
- **Aviso de caída por Telegram** (solo con Docker): `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.

Para probar esas partes sin cuentas: `CORREO_MODO=prueba` y `WALLET_MODO=prueba`.

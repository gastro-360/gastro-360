# Gastro 360 — manual técnico

Carta interactiva para restaurantes y bares: el cliente ve cada plato con foto y despiece por capas, quita ingredientes, añade extras y monta su pedido. Incluye un backoffice para que el local cambie precios, platos e ingredientes, los oculte cuando se agotan y suba fotos. Desde la mesa el cliente envía el pedido a la cocina, que lo ve en vivo en su propia pantalla.

**Qué NO hace:** no cobra (no hay pasarela de pago), no imprime tickets y no emite facturas. Es software libre bajo licencia [EUPL-1.2](../LICENSE) y se ofrece **sin garantía** de ningún tipo (ver [SUPPORT.md](../SUPPORT.md)). El nombre del producto vive en `carta/producto.json`; en este README está escrito a mano.

Es el primer módulo de un sistema de pedidos por mesa (QR o tablet), pantalla de cocina, aviso de entrega y backoffice.

## Instalar en un comando

Solo hace falta Docker con Compose. Es el camino oficial:

```
git clone https://github.com/gastro-360/gastro-360.git && cd gastro-360
./instalar.sh                # prueba local, sin preguntas
./instalar.sh --produccion   # servidor real, con dominio y HTTPS
```

- **Sin argumentos (prueba local)**: restaurante `demo`, genera un `.env` con una clave aleatoria del backoffice (se muestra una sola vez al final y queda solo en el `.env`), `CORREO_MODO=prueba` y `WALLET_MODO=prueba` (correo y Wallet simulados: nada sale a Internet), busca puertos libres desde el 8080 (`HTTP_PORT=9080 ./instalar.sh` para fijarlo), deja la app arrancada y muestra las direcciones de carta, cocina y backoffice (en `http://localhost:PUERTO`).
- **`--produccion`**: pregunta el nombre del restaurante (crea su carpeta con la plantilla), el dominio y la clave del backoffice (vacía = la genera), escribe el `.env` **sin modos de prueba** (no simula nada), usa el Caddy del repo para sacar el HTTPS de ese dominio en los puertos 80 y 443 (`HTTP_PORT`/`HTTPS_PORT` los cambian) y arranca. Si ya hay un `.env`, pregunta antes de tocarlo (y guarda `.env.anterior`).
- **Imagen**: `instalar.sh` construye la imagen `gastro-360:local` desde este repo (`docker compose build`); no se descarga de ningún registro. Aparte de las imágenes base de Docker, no descarga nada más ni envía nada a ningún sitio.
- Un restaurante recién instalado no tiene cuentas de terceros: Promociones por correo, Apple/Google Wallet y el botón de reseña salen desactivados y el backoffice dice qué falta (detalle en [docs/INSTALAR-AVANZADO.md](INSTALAR-AVANZADO.md)).
- Instalación sin Docker (Python a pelo): [docs/INSTALAR-AVANZADO.md](INSTALAR-AVANZADO.md).

## Arrancar a mano (sin instalador)

Requisitos: Python 3.10 o superior. Para subir fotos desde el backoffice y para los scripts de fotos, además:

```
pip install pillow numpy scipy
```

```
cd carta
python preparar_netlify.py   # genera la carpeta web/ (la primera vez y cada vez que cambie la carta)
python servidor.py           # carta en http://localhost:8080/  ·  backoffice en /admin  ·  cocina en /cocina
```

La primera vez el servidor crea una contraseña para el backoffice, la muestra y la guarda en `carta/clave_inicial.txt`. Para cambiarla:

```
python servidor.py --clave TU_CLAVE
```

Otro puerto: `python servidor.py --puerto 9000`. Desde el móvil, en la misma wifi: `http://IP-DEL-PC:8080/` (el servidor la muestra al arrancar).

## En producción con Docker

Es la forma de ponerlo en un servidor y de probarlo en local. Dos servicios: `app` (el servidor de la carta) y `caddy` (HTTPS automático). Solo Caddy publica puertos.

```
cp .env.example .env     # rellenar: DOMINIO, puertos, CLAVE_BACKOFFICE (ver el propio archivo)
docker compose up -d --build
```

| | `DOMINIO` | `HTTP_PORT` / `HTTPS_PORT` |
|---|---|---|
| Servidor con dominio | `carta.tudominio.es` (apuntando al servidor; Caddy pide y renueva el certificado solo) | `80` / `443` |
| Pruebas o Docker rootless (sin puertos < 1024) | `localhost` (certificado propio de Caddy: el navegador avisa) | `8080` / `8443` |

Con eso, la carta está en `https://DOMINIO/`, el backoffice en `/admin` y la cocina en `/cocina`. En ese caso, entra directamente por `https://localhost:8443/` (la redirección desde `http://localhost:8080` quita el puerto).

- **Datos**: el volumen `datos` (`/datos/restaurantes/<local>/`) guarda la carta, fotos, contraseña, pedidos, historial y copias, y sobrevive a `docker compose restart/down/up` (solo `down -v` lo borra). La primera vez se copia ahí la carta de git; después manda el volumen, no el código de la imagen.
- **Contraseña**: `CLAVE_BACKOFFICE` del `.env` (solo se usa si aún no hay contraseña). Cambiarla después: `docker compose exec app python servidor.py --clave NUEVA`.
- **`/salud`**: JSON (`{"ok": true, "restaurante": …, "aceptar_pedidos": …, "problemas": [], "version": "…"}`; `version` es el `GIT_SHA` con el que se arrancó la app, vacío si no se le dio ninguno), 200 si todo va bien y 503 si no se puede leer `datos.json` o escribir en la carpeta del restaurante. Es el healthcheck del contenedor `app` (Caddy espera a que esté `healthy`).
- **Logs**: todo a stdout: `docker compose logs -f app` (peticiones, pedidos nuevos, cambios de estado, apertura/cierre de pedidos y copias). `/salud` no se apunta.
- **Aceptar pedidos**: botón «Pedidos: abiertos/CERRADOS» en el backoffice y en la cocina. Cerrado, la carta lo avisa («Ahora mismo no se aceptan pedidos…»), desactiva «Enviar a cocina» y el servidor rechaza los pedidos (503). El estado se guarda en `ajustes.json` y sobrevive a reinicios; los pedidos que ya estaban en cocina siguen su curso.
- **Copias de pedidos**: cada `COPIA_HORAS` (6) horas `pedidos.json` + `historial/` se copian a `copias_pedidos/pedidos-AAAAMMDD-HHMMSS.json` (se guardan las 60 últimas). Además, cada guardado del backoffice sigue haciendo su copia de `datos.json` en `copias/`. Para sacarlas del servidor: `docker compose cp app:/datos/restaurantes/demo/copias_pedidos .`.
- **Dependencias**: la imagen instala Pillow, numpy y scipy (necesarios para subir fotos desde el backoffice y generar los iconos de la app); el servidor sigue siendo biblioteca estándar. Variables que usa el servidor: `RESTAURANTE`, `CLAVE_BACKOFFICE`, `COPIA_HORAS`, `PUERTO`, `ESCUCHAR`, `PROXY_CONFIABLE` (desactivada por defecto: lista de IP, redes CIDR o nombres de host, separados por comas, de los proxies de los que te fías para leer la IP real del cliente —`X-Forwarded-For`, `CF-Connecting-IP`— y el https —`X-Forwarded-Proto`—; el compose pone `caddy`. Sin ella se usa la IP del socket, así que una cabecera falsa no anula el freno de pedidos ni el de intentos de contraseña. `app:8080` nunca debe quedar expuesto directamente. Detrás de un proxy no la dejes vacía: todas las visitas compartirían la IP del proxy y el freno bloquearía a todos, dueño incluido. `CONFIAR_CF` (desactivada por defecto): con `CONFIAR_CF=1` la app usa `CF-Connecting-IP` como IP real; actívala solo si delante hay Cloudflare (túnel o proxy naranja) y el proxy no es accesible salvo por Cloudflare, o cualquiera podría inventarse la cabecera y evadir los frenos. Con túnel Cloudflare + Caddy, Caddy reescribe `X-Forwarded-For` con la IP de cloudflared: `PROXY_CONFIABLE=<nombre del servicio Caddy>` + `CONFIAR_CF=1`).

### Vigilancia (aviso por Telegram)

Tercer servicio del compose, `vigilante` (`carta/vigilante.py`, solo biblioteca estándar, misma imagen): cada `VIGILANTE_INTERVALO` (30) s pide `/salud` a `app` y, tras `VIGILANTE_FALLOS` (3) comprobaciones malas seguidas (sin respuesta, 503 o `ok` falso), manda **un** aviso de caída por Telegram con el motivo; en cuanto vuelve a ir bien, **un** aviso de recuperación con lo que duró. Si Telegram no acepta un aviso, lo reintenta en el siguiente ciclo. No depende de `app`, así que sigue vivo cuando esta cae.

En el `.env`: `TELEGRAM_BOT_TOKEN` (secreto, del bot creado con @BotFather) y `TELEGRAM_CHAT_ID` (escribe `/start` al bot y mira `https://api.telegram.org/bot<TOKEN>/getUpdates`). Sin ellas el vigilante arranca igual pero solo escribe en el log (`docker compose logs vigilante`). `TELEGRAM_API_URL` es solo para pruebas (simulador). Límite: si se cae el servidor entero, el vigilante cae con él y no avisa; para eso haría falta un sondeo desde fuera (p. ej. UptimeRobot sobre `/salud`).

`tests/test_vigilante.py` (unitarias, con `/salud` y Telegram simulados) y `tests/vigilancia.sh` (extremo a extremo en Docker: levanta `app` + `vigilante` + un Telegram simulado, para el contenedor `app`, espera el aviso de caída, lo arranca y espera el de recuperación; luego `down -v`).

### Probar el contenedor

```
export XDG_RUNTIME_DIR=/run/user/$(id -u) DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock   # solo con Docker rootless
tests/contenedor.sh
```

Levanta el compose en un proyecto aparte (puertos 18080/18443, volúmenes propios), espera al healthcheck, ejecuta las pruebas de `tests/` dentro del contenedor, `tests/test_contenedor.py` desde fuera (por Caddy, HTTPS: `/salud`, páginas, API protegida, interruptor de pedidos y el ciclo alta con permiso → ficha con prueba → baja confirmada), comprueba que el volumen conserva los datos tras `docker compose restart` y lo borra todo al acabar (`CONSERVAR=1` lo deja levantado).

### Prueba de punta a punta con navegador (E2E)

```
tests/e2e.sh
```

Levanta el compose en un proyecto aparte (`cartae2e`, puertos 19080/19443, `WALLET_MODO=prueba`, `CORREO_MODO=prueba`, enlace de reseña de PRUEBA puesto solo en el volumen) y lanza Playwright contra Caddy, a 360 px (móvil) y 1280 px (escritorio): 6 móviles y 1 escritorio pidiendo a la vez, cocina, reseña, tarjeta de sellos, las 10 pestañas del backoffice (sin scroll horizontal), cambio de precio visible en la carta, cerrar/abrir pedidos, promoción por correo simulado y baja confirmada. Falla ante cualquier error de consola, de JS o de red. Capturas en `tests/e2e/salida/` (ignorada por git). Al acabar hace `down -v` (`CONSERVAR=1` lo deja levantado).

**Dependencia justificada:** Playwright (Python) y Chromium solo viven en `tests/e2e/Dockerfile`, una imagen de pruebas aparte (`carta-e2e:local`); nunca entran en la imagen de producción, que sigue siendo solo biblioteca estándar. Se usa una imagen propia y no la oficial de Playwright (~2 GB) para ocupar poco disco. No hay otra forma de comprobar el diseño y el comportamiento reales en un móvil sin un navegador.

Este E2E encontró un defecto real: el servidor aceptaba solo 5 conexiones en cola (`request_queue_size`) y, con varios móviles cargando las fotos a la vez, algunas quedaban colgadas decenas de segundos. Ahora la cola es de 256.

## Guion de aceptación (método QA)

Los tests de arriba usan modos de prueba; la aceptación recorre lo que vería una persona con un restaurante **recién instalado, sin credenciales**.

- `docs/GUION-ACEPTACION.md`: casos con ID estable (CA-01…) por actor (cliente en móvil, cocina en tablet, dueño en el backoffice), con pasos, resultado esperado y el aviso que debe verse sin credenciales.
- `tests/aceptacion/correr.sh BASE_URL CLAVE [--solo CA-01,CA-17]`: runner Playwright (imagen de `tests/e2e`) que ejecuta los casos automatizables contra **cualquier** dirección, a 360 y 1280 px, sin asumir modos de prueba: si un canal no existe comprueba el aviso, si existe comprueba que funciona. Un error de consola o una petición a otro host hacen fallar el caso. Si el sitio va detrás de usuario y contraseña HTTP: `QA_BASIC_USUARIO` y `QA_BASIC_CLAVE` (no se imprimen ni se guardan). Capturas y `resultado.json` en `tests/aceptacion/salida/` (ignorada por git); sale ≠ 0 si algún caso falla. No es destructivo: crea lo suyo («QA-agente») y deja como estaba el interruptor de pedidos y los precios.
- `tests/aceptacion.sh`: levanta el compose en un proyecto aparte (`aceptacion`, puertos 19180/19543) con un `.env` sin credenciales ni modos de prueba, corre el runner, repite con `CORREO_MODO=prueba` y `WALLET_MODO=prueba`, y hace `down -v`.
- `tests/lineas-rojas.sh`: ningún nombre ni dato de un local o empresa concretos en el contenido, los nombres de fichero ni los commits (los nombres a vigilar van en `tests/lineas-rojas.local`, fuera de git).

## Privacidad: qué sale a Internet y cuándo

Gastro 360 no lleva telemetría, analítica, comprobación de versiones ni «llamada a casa», y el navegador del cliente, de cocina o del backoffice **solo habla con el propio servidor**: las librerías están alojadas en `carta/vendor/` (hoy, el generador de QR `qrcode-generator`, licencia MIT, ver [THIRD-PARTY.md](../THIRD-PARTY.md)) y las tipografías (Inter y Noto Sans SC, licencia OFL) van en `carta/estatico/fuentes/` (ver [THIRD-PARTY.md](../THIRD-PARTY.md)). Sin CDN, sin `preconnect`, sin iframes ni imágenes remotas.

Cada respuesta HTML del servidor lleva `Content-Security-Policy` (`default-src 'self'`, `connect-src 'self'`, `img-src 'self' data:`, sin `unsafe-eval`; los `<script>` en línea se autorizan por su huella sha256, sin `unsafe-inline` en scripts), `Referrer-Policy: no-referrer` y `X-Content-Type-Options: nosniff`; con HTTPS (`URL_PUBLICA` https o `X-Forwarded-Proto` de un proxy de confianza) añade también `Strict-Transport-Security`, y la cookie de sesión sale con `Secure`. El servidor no anuncia su versión (`Server: Gastro`; Caddy lo quita). Los estilos en línea sí están permitidos (`style-src 'unsafe-inline'`): con imágenes, conexiones y fuentes limitadas a `self`, un estilo inyectado no puede ejecutar código ni sacar datos. La definición está en `carta/seguridad.py`.

**El servidor solo sale a Internet por canales que el dueño configura, y cada uno solo con su configuración:**

| Canal | Destino | Se activa solo si… | Qué envía |
|---|---|---|---|
| Correo de promociones | API de Brevo | hay `BREVO_API_KEY` y `BREVO_REMITENTE` en `.env` | el correo a quien dio su permiso |
| Google Wallet | API de Google Wallet | hay cuenta de servicio y `issuer_id` en `wallet/` | actualizaciones de la tarjeta de sellos |
| Apple Wallet | servicio de avisos de Apple (APNs) | hay certificados de Apple en `wallet/` | un aviso vacío a la tarjeta |
| Aviso de caída | API de Telegram | hay `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en `.env` | «caída» / «recuperada» |

Un restaurante recién instalado no tiene ninguno y no hace ninguna conexión saliente. Los enlaces «Añadir a Google Wallet» y la reseña de Google los abre el cliente con un clic: son navegación suya, no peticiones de la página. El comprobador de la IP local (`/api/red`) no envía nada: un `connect` UDP a una dirección reservada solo elige la interfaz.

**Comprobarlo:** `tests/privacidad.sh` levanta la app con un `.env` sin credenciales ni modos de prueba y recorre con Playwright la carta (360 px, haciendo un pedido), la cocina y el backoffice entero (1280 px), además de la tarjeta y la baja: falla si el navegador pide algo a otro host, si la consola muestra errores o violaciones de la CSP, o si falta una cabecera. `tests/privacidad.sh --negativa` mete un enlace externo en la portada y comprueba que el test falla.

## Un restaurante por carpeta

Lo común (código) está en `carta/`; todo lo propio de un local, en `restaurantes/<local>/` (`datos.json`, `fotos/`, `marca.json`, `marca/`, y la contraseña y los pedidos que se crean al usarlo). El activo se elige con la variable `RESTAURANTE` (por defecto `demo`):

```
RESTAURANTE=otrolocal python preparar_netlify.py && RESTAURANTE=otrolocal python servidor.py
```

### Restaurante nuevo desde la plantilla

```
cd carta
python nuevo_restaurante.py bar-pepe --nombre "Bar Pepe" --color "#2A6F4F"
RESTAURANTE=bar-pepe python preparar_netlify.py && RESTAURANTE=bar-pepe python servidor.py
```

Crea `restaurantes/bar-pepe/` con `marca.json`, un logo provisional (círculo liso del color elegido), `datos.json` con un plato y una ración de ejemplo (para que la carta no salga vacía; se cambian o borran en el backoffice) y `fotos/` vacía. Si la carpeta ya existe, no la toca.

### `marca.json`

La carta, el backoffice y la cocina leen del `marca.json` del restaurante activo su nombre, logo, colores y textos. Solo hacen falta `nombre` y `logo` (nombre de archivo dentro de `marca/`); lo demás tiene valor por defecto:

| Campo | Para qué |
|---|---|
| `nombre`, `nombre_corto` | Título completo y el corto (cocina, backoffice, icono del móvil) |
| `nombre_resalte` | Final de `nombre` que sale en el color de acento en las cabeceras (por defecto, la última palabra) |
| `descripcion`, `lema`, `intro` | Texto para buscadores y manifiesto, línea sobre el título y párrafo de la cabecera de la carta |
| `logo` | Archivo de `marca/` (también genera los iconos de la app) |
| `tipografia` | Opcional: `titulos`, `texto` y `mono`, listas de fuentes CSS. Por defecto, Inter alojada en el propio servidor, con chino (Noto Sans SC) sin CDN; una fuente propia debe estar en el servidor o ser del sistema (el navegador no carga nada de terceros) |
| `textos` | Opcional: `plato` y `platos` (en masculino), el nombre que la carta da a su producto principal (p. ej. «combinado»/«combinados»; por defecto «plato»/«platos») |
| `direccion`, `telefono`, `aviso_pie` | Opcional: líneas del pie de la carta |
| `colores` | `fondo`, `primario`, `primario_suave`, `acento`, `acento_suave`, `acento_texto` y, opcionales, `superficie`, `superficie_2`, `tinta` (`#RRGGBB`; los que falten usan la paleta neutra de la plantilla). El tema claro u oscuro sale del fondo y el contraste del texto se corrige solo (≥ 4,5:1) |
| `forma` | Opcional: `radio` (0–24 px) y `densidad` (`compacta`, `normal` o `amplia`) |
| `resena_url` o `google_place_id` | Reseña de Google: enlace directo (`https://…`) o el identificador de lugar (`ChIJ…`); si hay los dos manda `resena_url`. Sin ninguno, no sale el botón (ver «Reseña de Google») |
| `foto_referencia` | Opcional: foto de `fotos/` para la guía de subir fotos del backoffice |

El diseño sale de variables CSS (`--fondo`, `--primario`, `--r`, `--u`…) que `carta/tema.py` calcula desde `marca.json` y sirve como `/tema.css` (la carta estática la lleva generada). Cambiar `marca.json`, reiniciar la app (`docker compose restart app`) y recargar cambia el aspecto sin tocar código; los principios y tokens están en [docs/DISEÑO.md](DISEÑO.md). El CSS y el JS compartidos viven en `carta/estatico/`; cada página lleva solo lo suyo.

Las páginas llevan marcadores `{{nombre}}`, `{{logo}}`… que rellena `carta/restaurante.py` (el servidor para `/admin` y `/cocina`; `preparar_netlify.py` para la carta). La cookie de sesión y las claves del navegador llevan el nombre de la carpeta (`<restaurante>_sesion`, `<restaurante>_mesa`…).

### Pruebas automáticas

Desde la raíz del repositorio (usan carpetas temporales; no tocan `restaurantes/` ni `carta/web/`; necesitan Pillow, el mismo de `preparar_netlify.py`):

```
tests/unitarias.sh
```

`CARTA_RESTAURANTES` y `CARTA_WEB` (opcionales) cambian dónde buscan los restaurantes y dónde se genera `web/`; las usan las pruebas.

### Comprobar que un cambio no altera la carta

Antes y después del cambio (desde `carta/`), con el servidor en marcha en otro terminal (`python preparar_netlify.py && python servidor.py --puerto 18080`):

```
python comparar_respuestas.py 18080 antes.json      # antes del cambio
python comparar_respuestas.py 18080 despues.json    # después del cambio
python comparar_respuestas.py --comparar antes.json despues.json   # "19 de 19 rutas idénticas" = igual que antes
```

Compara `/`, `/admin`, `/cocina`, los datos servidos (`/datos.js`, `/fotos.js`), el service worker, el manifiesto, iconos y fotos.

## Reseña de Google

Cuando un pedido pasa a **Servido**, su tarjeta en la pantalla de estado del cliente muestra el botón «Dejar una reseña en Google» con el enlace del restaurante (`resena_url` o `google_place_id` en `marca.json`; con place_id se usa `https://search.google.com/local/writereview?placeid=…`). No sale en ningún otro estado ni si el restaurante no tiene enlace. **Es el mismo botón y el mismo enlace para todos los clientes**: no se pregunta si el pedido gustó, no se filtra ni se ofrece nada a cambio de reseñar (la política de Google lo prohíbe); no añadir nada de eso. Pruebas: `python3 -m unittest tests.test_resena -v` (genera una carta temporal y ejecuta con node el JavaScript que pinta cada pedido; se salta si falta node, como en la imagen Docker).

## Permiso de publicidad y clientes

Papeles de esta parte: [`docs/legal/`](legal/) (texto de la casilla con su historial de versiones). Es un borrador: **lo revisa un abogado antes de usarlo con clientes reales**. `python3 -m unittest tests.test_papeles` falla si el texto o la versión del documento dejan de coincidir con el código.

Al enviar el pedido, la carta ofrece (solo con servidor) un correo y una **casilla sin premarcar**: «Quiero que <restaurante> me envíe promociones y novedades por correo electrónico…». Sin casilla marcada no se guarda ningún correo. **Alta directa (por defecto)**: marcar la casilla basta, es lo que exige la LSSI art. 21 (decisión del titular, 25-oct-2026): `POST /api/pedido` registra el alta al instante con su prueba (fecha, canal `pedido-carta`, versión y texto exacto, idioma) —sin solicitud, token ni correo; si ya era apto no duplica— y responde `permiso: "alta"`. **Doble confirmación (opcional, `CONFIRMACION_DOBLE=1`)**: marcar la casilla NO da el alta; `POST /api/pedido` crea una solicitud pendiente y manda al propio correo un enlace de un solo uso (`/confirmar?t=TOKEN`: página con botón, y solo el clic —`POST /api/confirmar`— registra el alta con su prueba). El enlace se construye solo con `URL_PUBLICA` (nunca con la cabecera Host), como máximo un correo por hora y dirección, caduca a los 7 días y una baja invalida las solicitudes pendientes. Un token inventado, usado o caducado da 404. Sin canal de correo (sin Brevo y sin `CORREO_MODO=prueba`) o sin `URL_PUBLICA`, el cliente queda «pendiente de confirmar» y no recibe publicidad (con doble confirmación, la respuesta del pedido lleva `permiso`: `confirmar` o `sin_canal`). El texto y su versión los pone el servidor (`GET /api/permiso`, `carta/clientes.py`); si la carta manda una versión que ya no es la vigente, el pedido se rechaza para no guardar un permiso sobre un texto que la persona no vio. **Si se cambia una palabra del texto, hay que subir `TEXTO_VERSION`.**

- **Base de datos**: `restaurantes/<local>/clientes.db` (SQLite de la biblioteca estándar, fuera de git, en el volumen en Docker). `clientes` (correo en minúsculas, token propio de baja) y `permisos`: cada alta y cada baja es una fila nueva que no se edita ni se borra, con la acción, fecha y hora (con zona), canal (`pedido-carta` en alta directa, `pedido-carta+enlace-confirmacion` con doble confirmación, `enlace-baja`) y, en las altas, el **texto exacto** y su versión. «Apto para marketing» = el último movimiento del cliente es un alta.
- **Baja con confirmación**: cada cliente tiene un token; el enlace `/baja?t=TOKEN` (lo lleva cada mensaje) muestra una página que pide confirmar y solo entonces `POST /api/baja` registra la baja con fecha. Abrir el enlace no da de baja. Si luego vuelve a marcar la casilla en otro pedido, se registra un alta nueva.
- **Ficha**: `GET /api/clientes` (con sesión del backoffice) devuelve cada cliente con `apto_marketing`, `pendiente` (fecha de la solicitud sin confirmar) y todas sus pruebas (los que aún no tienen ninguna no salen en la lista); el backoffice los lista en la pestaña Promociones («Clientes con permiso y bajas»). El texto vigente es la versión 2 y menciona también el aviso en la tarjeta de Wallet. El pedido guarda el id del cliente (`cliente`) pero la cocina y el cliente no lo ven.
- No se guardan IP ni otros datos: solo correo y prueba.

## Tarjeta de sellos y Wallet

Fidelización sin datos personales: el cliente guarda una **tarjeta anónima** (no lleva correo ni nombre; el permiso de publicidad sigue siendo cosa de la casilla de arriba). Se crea desde la carta («Guardar mi tarjeta de sellos», bajo los pedidos enviados) o en `/tarjeta`; el cliente la ve en `/tarjeta?t=<código>` con su QR y, si hay canal, los botones «Añadir a Apple Wallet» / «Añadir a Google Wallet».

- **Reglas**: al marcar un pedido como **Servido** con tarjeta vinculada suma **1 sello como máximo por pedido** (`pedido_id` es único en la base de datos: volver a «servido» tras deshacer no duplica), solo si el total llega al **importe mínimo**. **Tope en el servidor**: al llegar a `sellos_meta` no se suman más sellos, ni a mano ni al servir un pedido, hasta canjear (409 «Premio disponible: canjéalo antes de seguir sellando»; el pedido servido en ese momento no deja sello). La caja también puede sellar a mano (`origen=caja`) y **canjear** el premio (resta `sellos_meta` sellos; 409 si faltan). Cada sello y canje es una fila que no se edita (`sellos.db`, SQLite, fuera de git).
- **Lo propio de cada restaurante** (`restaurantes/<local>/sellos.json`, editable en el backoffice → pestaña **Sellos**): `activo`, `sellos_meta`, `premio` (en castellano) y `premio_i18n` (`{"en","ca","zh"}`: el premio en cada idioma; vacío, cae a castellano; el premio de fábrica trae su traducción en los ficheros de idioma), `importe_minimo`. Sin archivo, valores por defecto. La parte `wallet` del mismo archivo guarda identificadores no secretos (`apple.pass_type_id`, `apple.team_id`, `google.issuer_id`).
- **Caja** (backoffice → Sellos): la lista «Últimas tarjetas» (código, sellos, último uso; sin correo ni teléfono; buscador por parte del código; `GET /api/sellos/tarjetas`, solo con sesión) abre una tarjeta sin teclear; también se puede escribir o escanear el código (lector USB; cámara con `BarcodeDetector`; si el navegador no la tiene, un aviso lo dice). Sin tarjetas, la lista explica cómo la consigue el cliente. La caja «Wallet del móvil» dice qué cuenta falta y quién la consigue. Ve la ficha y pulsa «Canjear premio» o «Sellar en caja».
- **Apple Wallet**: `GET /tarjeta/<id>.pkpass` genera un `.pkpass` (zip con `pass.json`, imágenes, `manifest.json` con SHA-1 y `signature` PKCS#7 firmada con `openssl smime`). Servicio web de PassKit en `/wallet/apple/v1/…` (registro y baja del móvil, lista de cambios con `passesUpdatedSince`, descarga con `If-Modified-Since`/304, `log`), autenticado con el `authenticationToken` de cada pase. Tras cada sello se envía un push vacío al APNs para que el móvil se actualice.
- **Google Wallet**: `GET /tarjeta/<id>/google` redirige a `https://pay.google.com/gp/v/save/<JWT RS256>` con la clase y el objeto de fidelización; tras cada sello se actualiza el objeto por la API REST.
- **Modos**: con credenciales reales en `restaurantes/<local>/wallet/` (`apple/{pass.pem,pass.key,wwdr.pem}`, `google/service_account.json`; fuera de git, en el volumen) y los identificadores en `sellos.json` el canal es **real**. Con `WALLET_MODO=prueba` y sin credenciales, un certificado y una clave **de prueba autogenerados** (`wallet/prueba/`) y clientes **simulados** (APNs y Google anotan lo que enviarían; se ven en `GET /api/wallet/simulador`, solo con sesión): sirve para probar que el paquete se genera y la firma verifica, pero **ningún móvil lo acepta**. Sin credenciales ni modo prueba, el canal no está disponible y la tarjeta funciona solo como página web. Variables: `WALLET_MODO`, `MAX_PEDIDOS_IP` (freno de pedidos por IP, 10 por defecto; las pruebas lo suben), `URL_PUBLICA` (dirección con la que se generan los pases; si falta, la de los QR de las mesas o la de la petición).
- **Sin dependencias nuevas de Python**: la firma del pase y del JWT usa la CLI `openssl` que ya trae la imagen (en lugar de `cryptography`); el push real a Apple (HTTP/2) usa `curl`, que se añade a la imagen. Las llamadas reales a Apple y Google **no están probadas** (hacen falta cuentas de Apple Developer y Google Wallet).
- **Pruebas**: `python3 -m unittest tests.test_sellos -v` (reglas, canje, `.pkpass` firmado y manipulado, JWT, push simulado) y la clase `Sellos` de `tests/test_contenedor.py` (todo el recorrido por HTTP contra el contenedor: servido → sello, sin duplicados, canje, firma verificada con `openssl` fuera de nuestro código, registro de dispositivo, push, pase actualizado y 304, enlace de Google).

## Promociones

Backoffice → pestaña **Promociones**: se redacta un título (3–60 letras) y un mensaje (5–300), se elige el canal (correo, aviso en la tarjeta de Wallet o los dos), se ve cuántos recibirían la promoción y, tras una confirmación, se envía. Una promoción solo se envía una vez; para otra, se escribe otra.

- **Solo a quien dio permiso (LSSI art. 21)**: el destinatario es el cliente cuyo último movimiento es un **alta** y cuyo texto cubría ese canal (`clientes.CUBRE`). Quien dio permiso con el texto v1 (solo correo) recibe correos pero no avisos en Wallet; el texto vigente (v2) cubre las dos cosas. La baja se vuelve a comprobar **justo antes de cada envío**, así que una baja que llega mientras se envía se respeta. Una tarjeta de sellos solo recibe avisos si está vinculada a un cliente con permiso (se vincula al pedir con tarjeta y casilla marcada); la tarjeta anónima nunca recibe nada.
- **Cada mensaje identifica y da de baja**: el asunto empieza por «Publicidad:» (LSSI art. 20), el pie dice por qué lo recibe (fecha del permiso) y lleva el enlace de baja propio de ese cliente (`/baja?t=…`, con confirmación), más la cabecera `List-Unsubscribe`. En Wallet, el aviso lleva el enlace de baja en el reverso del pase (Apple, con notificación por `changeMessage`) y en el mensaje y los enlaces del objeto (Google, `addMessage` con notificación).
- **Registro** (`restaurantes/<local>/promociones.db`, fuera de git): tabla `envios` con promoción, canal, cliente/tarjeta, destino, fecha y resultado (`enviado`, `fallido`, `omitido_limite`, `sin_destino`). Cada (promoción, canal, destino) es único: un reintento o una reanudación tras una caída no duplica. Se ve en el backoffice (botón «Registro») y en `GET /api/promociones/registro?id=`.
- **Límite de Wallet**: como mucho 3 avisos por tarjeta cada 24 h (`LIMITE_WALLET`, tope de Google para avisos con notificación); el resto queda como `omitido_limite`.
- **Correo (Brevo)**: API transaccional `POST /v3/smtp/email` con la biblioteca estándar (`carta/correo.py`). Variables: `BREVO_API_KEY`, `BREVO_REMITENTE` (remitente validado en Brevo) → modo real; `CORREO_MODO=prueba` → simulador que anota lo que enviaría (`GET /api/promociones/simulador`, solo con sesión y en ese modo). Sin ninguna, el canal de correo no está disponible y no se puede elegir; si tampoco hay canal de Wallet, la pestaña Promociones lo explica nada más abrirla (qué variables poner en el `.env` y cómo probar con `CORREO_MODO=prueba`) y «Enviar promoción» queda desactivado con el motivo. Nada se simula si no se pide en el `.env`. **`Brevo` no está probado contra la API real** (hace falta una cuenta de Brevo).
- **Rutas** (todas con sesión del backoffice): `GET /api/promociones`, `POST /api/promociones` (crear), `POST /api/promociones/enviar {id}` (202; 409 si ya se envió), `DELETE /api/promociones?id=` (solo borradores).
- **Pruebas**: `python3 -m unittest tests.test_promociones -v` (con y sin permiso, sin tarjeta, texto antiguo, baja antes y durante el envío, registro, no repetir, límite de Wallet) y la clase `Promociones` de `tests/test_contenedor.py` (recorrido completo por HTTP contra el contenedor con `CORREO_MODO=prueba`).

## Alérgenos

La carta puede enseñar los 14 alérgenos de declaración obligatoria (Reglamento UE 1169/2011, anexo II): cereales con gluten, crustáceos, huevos, pescado, cacahuetes, soja, leche, frutos de cáscara, apio, mostaza, sésamo, sulfitos, altramuces y moluscos. La lista es cerrada y vive en `carta/alergenos.json` (id estable en inglés y nombre en castellano; los iconos SVG, propios y locales, en `carta/iconos_alergenos/`). El servidor rechaza cualquier valor que no sea uno de los 14.

Cada plato o ración está en **una de tres situaciones**, y la carta las distingue:

| Situación | Se guarda | La carta enseña |
|---|---|---|
| Alérgenos marcados | lista con al menos un id | iconos **con** su nombre |
| Sin alérgenos declarados | `"alergenos": []` | «Sin alérgenos declarados» |
| Todavía sin revisar (por defecto) | sin el campo | «Consulta al personal» |

- En el backoffice, el editor obliga a decidir entre las tres antes de guardar un plato o ración nuevo; los existentes sin revisar se cuentan en la pestaña principal (⚠ n) y un botón filtra solo esos.
- El aviso «Información facilitada por el restaurante; consulta al personal» es fijo (no sale de `marca.json`) y está en la carta, en el resumen del pedido y en el diálogo de envío.
- El pedido guarda los alérgenos de cada línea y la pantalla de cocina los enseña en la tarjeta.

**Límite honesto:** el producto solo muestra lo que declara el restaurante; la exactitud de esos datos es responsabilidad del restaurante. Los extras que añade el cliente o los ingredientes que quita no cambian los alérgenos declarados del plato: ante cualquier duda, el cliente debe consultar al personal.

## Idiomas

La interfaz (carta, cocina, backoffice, correos y tarjeta de sellos) sale en ocho idiomas: castellano, inglés, catalán, chino simplificado, francés, alemán, italiano y portugués (de Portugal).

- **Elegir idioma**: selector arriba en cada pantalla (Castellano / English / Català / 中文 / Français / Deutsch / Italiano / Português). La primera visita arranca con el idioma del navegador (`Accept-Language`) y, si no es uno de los ocho, en castellano; la elección se recuerda.
- **Textos de la interfaz**: `carta/i18n/{es,en,ca,zh,fr,de,it,pt}.json` (claves planas; el castellano es la fuente y lo que falta en otro idioma cae a castellano). Fechas, meses e importes salen de tablas propias, sin depender del idioma del equipo.
- **Datos del local por idioma**: en `datos.json`, el nombre (`n`), la descripción (`d`) y la sección (`sec`) de platos, raciones e ingredientes son un texto (solo castellano) o un objeto `{"es": …, "en": …, "ca": …, "zh": …, "fr": …, "de": …, "it": …, "pt": …}`. En `marca.json`, `lema`, `intro`, `descripcion`, `aviso_pie` y `textos` admiten lo mismo. Un idioma vacío cae a castellano. Los nombres de los grupos de extras salen del diccionario.
- **Sin traductor en línea**: los textos de cada idioma van en el propio programa; nada se traduce al vuelo ni se llama a servicios externos. El chino es provisional hasta que lo revise un nativo ([`docs/REVISION-CHINO.md`](REVISION-CHINO.md)); el francés, el alemán, el italiano y el portugués, también, hasta su revisión nativa. Añadir un idioma: su `carta/i18n/<idioma>.json`, el código en `IDIOMAS` de `carta/idiomas.py` y `carta/idiomas.js` (con sus meses, días y formato de números) y sus campos en los datos de la demo.
- **Pruebas**: `python3 -m unittest tests.test_i18n -v` (claves, marcadores, caída a castellano, fechas, `Accept-Language` y datos de la demo).

## Qué hace la carta

- Escritorio en tres columnas (carta, plato, ingredientes), cada una con su propio desplazamiento. Móvil tipo app: cabecera que se recoge, carta deslizable, ingredientes y pedido en paneles inferiores.
- Despiece por capas con fotos y plato completo. Si el cliente lo personaliza, se monta con las fotos de cada capa.
- Quitar ingredientes no cambia el precio; los extras suman. Pa amb tomàquet incluido en los platos que lo llevan (se puede quitar).
- Pedido con líneas editables: tocar una línea la abre para cambiarla. Al añadir un plato, la pantalla vuelve a la receta, así el siguiente se personaliza aparte (uno con queso y otro sin).
- **Enviar a cocina**: con el número de mesa (lo pone el QR con `?mesa=5`; si no, el cliente elige su mesa) y una nota opcional. Después el cliente ve el estado de su pedido: recibido, en preparación, listo, servido.
- Sin servidor (la carta publicada como demostración) el envío se simula y se avisa de que es una demostración.
- Instalable como app (PWA) y funciona sin conexión cuando se sirve por `https://`.

## Cifras (backoffice)

Pestaña **Cifras**: cuatro números del mes (selector de mes; por defecto el actual) junto al mes anterior (`GET /api/kpis?mes=AAAA-MM`, solo con sesión; código en `carta/kpis.py`):

1. **Pedidos desde el QR**: % de pedidos del mes hechos con la carta abierta desde el QR de la mesa (`?mesa=N`) frente a los que eligieron la mesa a mano. La carta lo declara en cada pedido (`via`: `qr` o `manual`; lo guarda el servidor). Los pedidos anteriores a medirse no tienen `via` y no entran en el porcentaje (se avisa de cuántos son).
2. **Tarjetas de sellos guardadas**: tarjetas creadas en el mes (y el total).
3. **Reseñas**: Google no deja leer cuántas reseñas llegan, así que se mide lo medible: **clics al botón «Dejar una reseña en Google»** de la carta (uno por pedido, anónimo, en `kpis.db`; no cambia lo que ve ni se le ofrece al cliente). No cuenta quien llega al enlace desde la tarjeta de Wallet.
4. **Clientes que repiten**: tarjetas con 2 o más sellos dados en el mes (y las de siempre).

Cada cifra lleva debajo una ayuda corta de qué cuenta y cuándo sube («repetir» = 2 o más sellos en el mes; las tarjetas suben cuando un cliente guarda la suya, no con los pedidos solos). Sin datos, la pestaña dice «Todavía no hay datos» y que no hay nada que configurar para que cuenten, en vez de ceros a secas. El mes sale con nombre («octubre de 2026»): los nombres de los meses van en el propio backoffice, sin depender del idioma del contenedor ni del navegador.

**Enlace de reseñas**: sin `resena_url` ni `google_place_id` en `marca.json`, la carta no enseña el botón y «Clics a la reseña» no puede contar; Cifras lo avisa en esa cifra. Se pone en la propia pestaña, en «Ajustes de reseñas» (`POST /api/resena`, con sesión): acepta un enlace `https://…` sin espacios o el identificador de lugar (`ChIJ…`), valida antes de escribir `marca.json`, y vacío lo quita. La portada ya generada se actualiza en el acto, sin reiniciar.

Pedidos de `pedidos.json` y `historial/`; sellos y tarjetas de `sellos.db`. Pruebas con datos sembrados y el endpoint por HTTP: `python3 -m unittest tests.test_kpis -v`.

## Exportar pedidos (backoffice)

Pestaña **Exportar**: el dueño elige «desde» y «hasta» (ambos días incluidos; por defecto, del día 1 del mes en curso a hoy; máximo 366 días) y descarga **CSV** o **Excel (.xlsx)**. Es un listado de pedidos para llevar a un gestor o a una hoja de cálculo: **el producto no cobra, no imprime tickets y no factura**, y por eso el aviso «Este documento no es una factura» va en ambos formatos (primera línea del CSV; celda A1 y nombre de la hoja en el Excel) y en la ayuda de la pestaña. No lleva NIF, serie, desglose de impuestos ni nada parecido, y no se debe añadir.

- **Una fila por línea de pedido**, con: fecha y hora, nº de pedido, mesa, zona, estado, producto, extras, cantidad, precio unitario, subtotal de la línea y total del pedido (este solo en la primera línea de cada pedido, para poder sumar la columna). Entran los pedidos de todos los estados, los de hoy y los del `historial/`; el día es el de servicio (hasta las 5 de la mañana cuenta como el anterior).
- **Sin datos personales por defecto**: ni nombre, ni correo, ni teléfono, ni la nota del cliente, ni la tarjeta o el permiso de publicidad. Si algún día hiciera falta algo de eso, sería una decisión nueva y explícita del dueño; hoy no hay interruptor.
- **CSV**: UTF-8 con BOM, separador «;», decimales con coma (`6,50`), comillas y saltos de línea escapados, y las celdas de texto que empiezan por `=`, `+`, `-`, `@`, tabulación o retorno llevan delante una comilla simple (inyección de fórmulas). **Excel**: generado con la biblioteca estándar (`zipfile` + XML a mano), sin dependencias; los textos van como cadenas, nunca como fórmulas, y los importes y la fecha llevan formato de número.
- Nombres de fichero neutros: `pedidos_2026-10-01_a_2026-10-31.csv` / `.xlsx`. Textos del fichero y de la pestaña en los ocho idiomas (el fichero sale en el idioma elegido en el backoffice).
- API (con sesión; sin ella, 401): `GET /api/exportar?desde=AAAA-MM-DD&hasta=AAAA-MM-DD` devuelve el resumen (pedidos, líneas, total); con `&formato=csv|xlsx` descarga. Fechas mal formadas, «desde» posterior a «hasta» o más de 366 días dan 400 con un mensaje que explica qué cambiar.
- Pruebas: `python3 -m unittest tests.test_exportar -v` (rango vacío, sin sesión, fechas inválidas, escape de fórmulas, totales que cuadran, Excel releído con `zipfile` + `xml`) y el caso CA-32 de `tests/aceptacion.sh`.

## Qué hace el backoffice

- **Platos**: nombre, precio, sección (desplegable o sección nueva), descripción (automática a partir de los ingredientes), ingredientes en orden, reordenar, crear, borrar.
- **Para picar**: nombre, precio, orden, crear, borrar.
- **Ingredientes**: nombre, grupo, extra y precio (a 0 € no muestra precio), dibujo si no hay foto, subir foto.
- **Visible / Oculto** en todo: lo oculto no sale en la carta. Un ingrediente oculto sale «Agotado» en sus recetas.
- **Subir foto**: guía para crearla con ChatGPT (referencia + texto ya escrito), recorte automático del fondo y vista previa dentro de un plato.
- **Mesas y QR**: alta de mesas (una a una o «de la 1 a la 10») con zona opcional (Salón, Terraza…), dirección de la carta e impresión de los QR en A4 (6 por hoja, una mesa o todas). Con mesas dadas de alta, la carta y el servidor solo aceptan esas mesas; sin QR, el cliente elige su mesa de una lista. La cocina muestra la zona. Con Docker el servidor no conoce la dirección del ordenador en la wifi (solo ve la interna del contenedor, 172.x), así que no la ofrece: la escribe quien instala (la del ordenador o el dominio con https).
- Corrector ortográfico en español, copia de seguridad en cada guardado (`copias/`) y aviso si dos personas guardan a la vez.

## Pedidos y cocina

- La carta envía el pedido a `servidor.py`, que comprueba los productos y **calcula los precios él mismo** (no se fía del móvil). Los productos iguales se juntan («2× Clásico»). Si un extra se ha agotado mientras tanto, avisa al cliente.
- **Pantalla de cocina** (`/cocina`, misma contraseña que el backoffice, con «Recordar este dispositivo 30 días»): columnas Nuevos, En preparación y Listos para servir; botones grandes para pasar de una a otra y «↩» o «Deshacer» si te equivocas. Sonido al llegar un pedido (hay que pulsar el botón de sonido una vez al abrirla), minutos de espera en amarillo a los 10 y en rojo a los 20, y la pantalla no se apaga sola.
- **En preparación** cada plato muestra sus ingredientes numerados en el orden en que se montan (1 = lo primero sobre el pan de abajo). Es el orden de la receta en el backoffice; lo quitado sale tachado y los extras van al final. El botón «Ingredientes» de arriba la muestra u oculta (se recuerda en cada dispositivo).
- «En preparación» se ensancha una columna por mesa; cuando no caben más, las siguientes pasan debajo.
- Los pedidos se numeran desde el 1 cada día de servicio, que empieza a las 5 de la mañana (lo de después de medianoche cuenta como el día anterior). Se guardan en `pedidos.json`; los entregados de días anteriores pasan a `historial/pedidos-AAAA-MM.jsonl`.
- Freno contra abusos: como mucho 10 pedidos cada 10 minutos desde el mismo dispositivo.

## Pedidos online: a domicilio y para recoger

Sin pasarela de pago: **el cliente paga al recibir, con el ticket de la caja del restaurante** (su TPV o programa de facturación). Gastro 360 no registra ningún cobro, no tiene estado «cobrado» y la hoja de reparto no lleva importes.

- **Página pública** `/pedir`: la misma carta y la misma cesta, sin mesa. El cliente elige a domicilio (dirección y código postal dentro de la zona) o para recoger, «lo antes posible» o una hora dentro del horario, deja nombre y teléfono y dice **cómo prefiere pagar al recibir** (tarjeta o efectivo, con una nota libre para el cambio: es una nota para que el repartidor lleve datáfono o cambio, no un pago). Antes de enviar ve los precios, los gastos de envío y el **importe estimado** (lo exige la ley de consumidores en la venta a distancia).
- **Seguimiento** `/seguir?t=…`: «Resumen de tu pedido», con el aviso fijo «No es factura ni ticket. El ticket te lo da el restaurante al entregar o recoger.», el estado, la hora estimada y el motivo si se rechaza o cancela. El enlace lleva un token aleatorio largo (no el número ni el id del pedido) y no muestra teléfono ni dirección.
- **Estados**: `recibido` → `aceptado` (la sala fija en cuántos minutos estará; con hora programada, la estimada es la pedida) o `rechazado` (con motivo) → `preparando` → `listo` → `en_reparto` (solo domicilio) → `entregado`; `cancelado` con motivo en cualquier momento antes de entregar. Un pedido que nadie acepta pasa solo a `cancelado` (motivo «sin aceptar») al llegar su hora programada o, si era «lo antes posible», al acabar su día de servicio, y se archiva con los demás terminados. Los de mesa siguen igual (`nuevo` → `preparando` → `listo` → `entregado`). La **cocina solo ve los online desde «aceptado»**; a domicilio, de «Listo» los saca la sala. Al llegar a «entregado» se da el sello de fidelidad igual que en mesa.
- **Backoffice → Pedidos online**: aceptar (minutos), rechazar (motivo), cancelar, «Sale a repartir», «Entregado» y la **hoja de reparto** imprimible (`/admin/reparto?id=…`, con sesión): nombre, teléfono, dirección, platos, preferencia de pago y «Cobrar con el ticket de caja». **Sin importe.**
- **Ajustes del dueño** (misma pestaña, `pedidos_online.json` del restaurante, fuera de git): activar domicilio y recoger por separado, días y tramos horarios, pedido mínimo, gastos de envío fijos, **zona por lista de códigos postales** (sin mapas ni servicios de terceros), tiempo de preparación por defecto y «Pausa: no aceptamos pedidos online ahora». Por defecto **todo desactivado**; la demo trae `restaurantes/demo/pedidos_online.defecto.json` con todo activado para poder probarlo. El interruptor general «Pedidos: abiertos/CERRADOS» también los cierra.
- **Abusos**: el mismo freno por IP que los pedidos de mesa (`MAX_PEDIDOS_IP`) y, con `CONFIRMACION_DOBLE=1`, la misma doble confirmación de la casilla de publicidad. La sala acepta o rechaza cada pedido: sin pago que disuada, es el filtro contra pedidos falsos.
- **Exportar**: los pedidos online salen con su columna «Tipo» (Mesa, Domicilio, Recoger) y la de «Envío»; el «Total del pedido» incluye los gastos de envío (lo que vio el cliente; los sellos se siguen calculando sobre los productos), sin nombre, dirección ni teléfono, y con el mismo aviso «no es una factura». Los rechazados y cancelados no cuentan ni en la exportación ni en Cifras.
- **Pruebas**: `python3 -m unittest tests.test_pedidos_online -v` (zona, horario, mínimo, pausa, flujo de estados, token de seguimiento, hoja sin importes, freno por IP y que mesa sigue igual).

## Reservas de mesa

- **Página pública** `/reservar`: fecha → horas libres (los tramos completos salen como «completo») → comensales → nombre y teléfono (correo opcional) → nota, con el aviso fijo «No escribas datos de salud; los alérgenos se consultan en la carta y con el personal». La casilla de permiso de publicidad es la misma del pedido, aparte y sin marcar.
- **Aforo**: máximo de comensales por tramo (cada 15, 20, 30 o 60 min; por defecto 30), horario de llegadas por día de la semana (el último tramo empieza antes del cierre de la franja), días cerrados, antelación mínima (minutos) y máxima (días) y máximo de comensales por reserva. Ocupan aforo las solicitadas, confirmadas y sentadas. Sin plano de mesas.
- **Modo**: `automatico` (se confirma sola si cabe) o `manual` (queda `solicitada` hasta que la sala acepta o rechaza).
- **Estados**: `solicitada` → `confirmada` | `rechazada` (motivo) → `sentada` (mesa opcional) | `no_presentada`; `cancelada` por el cliente o por la sala (motivo). Solas: una solicitada sin respuesta pasa a `rechazada` («sin respuesta») al llegar su hora; una confirmada sin sentar pasa a `no_presentada` X min después (por defecto 20). La sala puede deshacer «sentada» y «no presentada» mientras dure la cortesía (luego solo «Sentar»); «no presentada» se marca a partir de la hora de la reserva, y volver a un estado que ocupa aforo comprueba que el tramo aún tenga sitio.
- **Cliente**: `/reserva?t=TOKEN` (token aleatorio largo, comparado en tiempo constante; el enlace solo se da al reservar) con estado, motivo y botón para cancelar mientras no haya llegado la hora. No enseña teléfono ni correo.
- **Backoffice → Reservas** (con sesión): el día elegido por hora, comensales por tramo frente al aforo, aceptar, rechazar, sentar, no presentada y cancelar, y los ajustes en la misma pestaña (`reservas.json` del restaurante, fuera de git). Por defecto **desactivado**; la demo trae `restaurantes/demo/reservas.defecto.json` activado en modo automático. Las reservas se guardan en `reservas_datos.json` (fuera de git).
- **Abusos**: freno por IP propio (`MAX_RESERVAS_IP`, 10 reservas cada 10 minutos por defecto), aparte del de los pedidos: reservar no gasta el cupo de pedir ni al revés. Y la misma `CONFIRMACION_DOBLE` de la casilla (canal `reserva`).
- **Pruebas**: `python3 -m unittest tests.test_reservas -v` (aforo lleno, modo manual y automático, caducidad, no presentada, cancelación con token, rutas de sala sin sesión, freno por IP y XSS).

## Archivos

| Archivo | Para qué sirve |
|---|---|
| `carta/index.html` | La carta |
| `carta/admin.html` | El backoffice |
| `carta/cocina.html` | La pantalla de cocina |
| `carta/pedidos_online.py`, `carta/seguir.html` | Pedidos a domicilio y para recoger: ajustes, validación, estados, hoja de reparto y página de seguimiento |
| `carta/reservas.py`, `carta/reservar.html`, `carta/reserva.html` | Reservas: ajustes, aforo por tramos, estados y páginas del cliente |
| `carta/servidor.py` | Sirve la carta y el backoffice, guarda cambios y fotos |
| `carta/tema.py`, `carta/estatico/` | Tokens de diseño desde `marca.json` (`/tema.css`) y CSS, JS y fuentes compartidos |
| `carta/restaurante.py` | Elige el restaurante activo (variable `RESTAURANTE`), lee su `marca.json` y rellena los marcadores de las páginas |
| `carta/nuevo_restaurante.py` | Crea un restaurante nuevo en `restaurantes/<slug>/` |
| `tests/test_plantilla.py` | Pruebas automáticas (unittest) de la plantilla de restaurante |
| `tests/test_resena.py` | Pruebas del botón de reseña (aparece solo en «servido», igual para todos) |
| `carta/clientes.py`, `tests/test_clientes.py` | Clientes con permiso de publicidad y su prueba (SQLite) y sus pruebas |
| `carta/sellos.py`, `carta/tarjeta_web.py`, `carta/wallet.py`, `carta/wallet_apple.py`, `carta/wallet_google.py`, `tests/test_sellos.py` | Tarjeta de sellos (SQLite), sus rutas HTTP y los canales Apple/Google Wallet, con sus pruebas |
| `carta/promociones.py`, `carta/promociones_web.py`, `carta/correo.py`, `tests/test_promociones.py` | Promociones: redacción, envío por correo (Brevo) y Wallet solo a quien dio permiso, registro y sus pruebas |
| `docs/legal/`, `tests/test_papeles.py` | Plantillas legales por restaurante (texto de la casilla con su versión; borrador para el abogado) y la prueba de que el texto coincide con `carta/clientes.py` |
| `tests/test_contenedor.py`, `tests/contenedor.sh` | Batería contra el contenedor Docker (ver «En producción con Docker») |
| `tests/privacidad.sh`, `tests/privacidad/`, `tests/test_seguridad.py`, `carta/seguridad.py`, `carta/vendor/`, `THIRD-PARTY.md` | Privacidad: cabeceras CSP, librerías alojadas y la prueba de que el navegador solo habla con el servidor (ver «Privacidad») |
| `docs/GUION-ACEPTACION.md`, `tests/aceptacion.sh`, `tests/aceptacion/`, `tests/lineas-rojas.sh` | Método QA: guion de aceptación, su runner y la comprobación de nombres (ver «Guion de aceptación») |
| `tests/e2e.sh`, `tests/e2e/` | E2E con Playwright a 360 y 1280 px contra el contenedor (imagen de pruebas aparte; ver «Prueba de punta a punta») |
| `instalar.sh`, `docs/INSTALAR-AVANZADO.md` | Instalador de un comando (construye la imagen en local) e instalación sin Docker |
| `Dockerfile`, `docker-compose.yml`, `docker/`, `.env.example` | Imagen de la app, app + Caddy (HTTPS), entrada que prepara el volumen, y la configuración de ejemplo |
| `carta/comparar_respuestas.py` | Huella de lo que sirve el servidor, para comprobar que un cambio no altera la carta |
| `restaurantes/demo/datos.json` | Platos, raciones e ingredientes con sus precios (lo edita el backoffice) |
| `restaurantes/demo/datos.js`, `fotos.js` | Copias para la carta; se regeneran solas al guardar |
| `restaurantes/demo/fotos/` | Fotos recortadas (WebP con transparencia) |
| `restaurantes/demo/marca.json`, `marca/` | Nombre, color y logo del restaurante |
| `carta/fotos_marcadoras.py` | Genera fotos marcadoras (degradados con un icono) para ver una carta completa sin fotos reales; las de la demo salen de aquí |
| `carta/producto.json` | Nombre del producto |
| `carta/recorte.py` | Recorta fotos de capas: quita el fondo y separa las capas |
| `carta/preparar_netlify.py` | Prepara `web/`: la carta como app instalable |

No están en el repositorio (se crean dentro de `restaurantes/<local>/`): la contraseña (`config.json`, `clave_inicial.txt`), las sesiones abiertas (`sesiones.json`), los sellos (`sellos.db`) y las credenciales de Wallet (`wallet/`), los pedidos (`pedidos.json`, `historial/`), las copias de seguridad (`copias/`) y las fotos originales del generador (`fotos_raw/`, ~200 MB: guardarlas aparte). Tampoco `carta/web/` (se regenera).

## Contribuir y licencia

Las reglas para colaborar están en [CONTRIBUTING.md](../CONTRIBUTING.md). El proyecto se distribuye bajo [EUPL-1.2](../LICENSE) ([English](../LICENSE.en)), sin garantía.

## Publicar

- **Solo la carta (sin backoffice)**: subir el contenido de `carta/web/` a un alojamiento estático (Cloudflare Pages, Netlify, GitHub Pages).
- **Carta + backoffice**: con Docker en un servidor con dominio (ver «En producción con Docker»), o `servidor.py` funcionando en un servidor casero publicado con Cloudflare Tunnel (da `https://`, necesario para instalar la carta como app).

Los precios de la demo son ficticios.

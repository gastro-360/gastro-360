# Guion de aceptación

Para comprobar que Gastro 360 funciona **como lo vería una persona con un restaurante recién instalado**: sin Brevo, sin Wallet, sin enlace de reseña y sin ningún modo de prueba. No hace falta saber programar: cada caso dice qué hacer, qué debe pasar y qué debe ver si falta algo.

## Cómo usarlo

- **A mano**: abre la dirección del local en el móvil (o en el navegador, estrechando la ventana a 360 px de ancho) para lo del cliente; en una tablet para la cocina; y en el ordenador (1280 px) para el backoffice. Sigue los pasos de cada caso.
- **Automático**: `bash tests/aceptacion.sh` levanta una instalación local limpia y recorre los casos automatizables dos veces (sin credenciales ni modos de prueba; y con `CORREO_MODO=prueba` y `WALLET_MODO=prueba`). Contra otra dirección (por ejemplo el entorno de pruebas): `tests/aceptacion/correr.sh BASE_URL CLAVE [--solo CA-01,CA-17]`. Si el sitio va detrás de usuario y contraseña HTTP, se pasan en `QA_BASIC_USUARIO` y `QA_BASIC_CLAVE`.
- El resultado sale en una tabla y en `resultado.json` (`id`, `estado` = `pasa` / `falla` / `manual`, `detalle`, `captura`), con capturas a 360 y 1280 px. Nunca borra datos ajenos: crea lo suyo con el nombre «QA-agente», deja los pedidos en «Servido» y devuelve a su sitio lo que toca (precios, interruptor de pedidos).
- **Reglas para todos los casos**: sin errores en la consola del navegador; sin barra de desplazamiento horizontal a 360 px; ninguna petición del navegador a una dirección distinta de la del propio local; nada en pantalla vacío, a cero o desactivado sin explicar por qué y cómo se activa.
- **Idiomas**: cada caso describe el resultado, no el texto exacto. Los textos esperados viven en un solo sitio del runner (`TEXTOS` en `tests/aceptacion/correr.py`).

Aviso de lo que se espera SIN credenciales aparece en cada caso como «Sin credenciales».

---

## Cliente en el móvil (360 px)

### CA-01 · Carta: se abre y enseña la mesa
1. Abre `/?mesa=1` (el QR de la mesa 1).
2. **Esperado**: se ven los platos con foto y precio, y «Mesa 1» en la cabecera. Nada de `{{…}}` sin rellenar. Sin desplazamiento lateral. El selector de idioma de la cabecera se lee entero («Castellano», «English», «Català», «中文») a 360 y 1280 px, y el nombre del local no se reduce a «V…» por su culpa.
3. **Sin credenciales**: igual; la carta no depende de ningún servicio externo.

### CA-02 · Pedido: montar un plato y enviarlo a cocina
1. Pulsa un plato, quita un ingrediente (el plato pasa a «Personalizado»), pulsa «Añadir» y después «Enviar a cocina».
2. En el diálogo escribe una nota y confirma.
3. **Esperado**: el cliente ve su pedido «Recibido» con su mesa; el pedido llega a cocina con la nota.

### CA-03 · Casilla de permiso: sin marcar y legible
1. En el diálogo de enviar, escribe un correo y **no** marques la casilla.
2. **Esperado**: la casilla viene sin marcar, el texto se lee entero (menciona la baja) y cabe en pantalla. Sin marcarla, el correo no se guarda como cliente.

### CA-04 · Permiso dado: queda la prueba
1. Repite con un correo y marca la casilla.
2. **Esperado (por defecto, alta directa)**: el aviso dice que el permiso queda registrado y puedes darte de baja con el enlace de cada mensaje; el cliente **ya es apto**, sin correo de confirmación, y su permiso guarda texto, versión del texto, fecha y canal (`pedido-carta`).
   **Con `CONFIRMACION_DOBLE=1`**: el aviso dice que se ha mandado un correo para confirmar; el cliente **todavía no es apto** y no sale con permiso. Abre el enlace del correo (en modo prueba, en el simulador de Promociones), pulsa el botón «Sí, confirmo»: ahora el cliente aparece como apto y su permiso guarda texto, versión del texto, fecha y canal. Un enlace inventado, ya usado o caducado (7 días) da «no válido» (404 en la API); sin canal de correo (ni Brevo ni modo prueba) el cliente queda pendiente de confirmar y no recibe publicidad.

### CA-05 · Estado del pedido en vivo
1. Con un pedido enviado, la cocina lo pasa a «En preparación» y luego a «Listo».
2. **Esperado**: el cliente ve cada cambio sin recargar y sale el aviso «¡Pedido listo!».

### CA-06 · Reseña de Google
1. Cuando la cocina pasa el pedido a «Servido»:
2. **Esperado**: antes de servirlo no hay botón de reseña. Si el local tiene enlace de reseña, sale el mismo botón para todos, sin preguntar si ha gustado ni ofrecer nada a cambio. **Sin credenciales** (sin enlace): no sale el botón, y el aviso al dueño es el de CA-28.

### CA-07 · Guardar la tarjeta de sellos
1. En el pedido servido pulsa «Guardar mi tarjeta de sellos».
2. **Esperado**: se abre la tarjeta con su QR y su código escrito, sin ningún correo a la vista. Apple Wallet y Google Wallet se ofrecen solo si el canal existe. **Sin credenciales**: no se ofrecen y la tarjeta funciona igualmente como página web.

### CA-08 · Baja con un enlace que no vale
1. Abre `/baja?t=enlace-que-no-existe`.
2. **Esperado**: dice con claridad que el enlace no es válido; no da de baja a nadie.

### CA-09 · Baja completa
1. Envía una promoción por correo a un cliente con permiso, abre el enlace de baja del correo.
2. **Esperado**: abrir el enlace no da de baja; confirmar sí, y queda apuntada la baja como prueba.
3. **Sin credenciales**: manual. Solo se puede leer el correo con `CORREO_MODO=prueba`.

## Cocina (tablet)

### CA-10 · Entrar y ver pedidos
1. Abre `/cocina`, prueba una contraseña mala y luego la buena.
2. **Esperado**: con la mala, aviso claro; con la buena, los pedidos nuevos con mesa, productos, cambios y nota.

### CA-11 · Pasar a «Servido»
1. Pulsa «En preparación», «Listo» y «Servido» en un pedido.
2. **Esperado**: botones grandes (≥ 40 px de alto); el servidor refleja cada estado.

## Dueño en el backoffice (1280 px)

### CA-12 · Entrar y las diez pestañas
1. Abre `/admin`, contraseña mala y luego la buena.
2. **Esperado**: aviso con la mala; con la buena, diez pestañas (Platos, Para picar, Ingredientes, Mesas y QR, Sellos, Promociones, Cifras, Exportar, Pedidos online, Reservas), sin desplazamiento lateral.

### CA-13 · Platos, picar, ingredientes y precios
1. Abre las tres pestañas, cambia el precio de un plato, guarda y mira la carta.
2. **Esperado**: el precio nuevo sale en la carta. Al acabar, se devuelve el precio anterior.

### CA-14 · Mesas y QR
1. Abre «Mesas y QR».
2. **Esperado**: explica qué hace, pide la dirección de la carta (la que llevan los QR) y deja añadir mesas.
3. Con Docker, mira junto al campo de dirección. **Esperado**: no hay botón con una dirección interna del contenedor (172.16–31.x); si el servidor no puede conocer la del ordenador, un aviso lo explica y pide escribirla a mano. Si se escribe una 172.x a mano, el aviso dice que es interna de Docker y que los móviles no la abrirán.

### CA-15 · Interruptor «Aceptar pedidos»
1. Pulsa «Pedidos: abiertos» para cerrarlos y mira la carta y la cocina. Vuelve a abrirlos.
2. **Esperado**: cerrados, la carta avisa de que no se aceptan pedidos, «Enviar a cocina» no deja enviar, el servidor rechaza un pedido (503) y la cocina lo marca. Al acabar, el interruptor queda como estaba.

### CA-16 · Sellos: ajustes y caja
1. Abre «Sellos»; busca un código falso; busca el de una tarjeta; sella en caja.
2. **Esperado**: ajustes (programa activo, sellos para el premio, premio, importe mínimo) y caja. Código falso: «No encuentro esa tarjeta». Código bueno: «N de M sellos»; sellar suma uno.

### CA-17 · Sellos: lista de tarjetas
1. En «Sellos», mira bajo la caja.
2. **Esperado**: lista de «Últimas tarjetas» con código, sellos y fecha. **Sin credenciales** y sin tarjetas: una pista de cómo consigue el cliente la suya («Guardar mi tarjeta de sellos» tras el pedido).

### CA-18 · Sellos: con tope
1. Sella a mano una tarjeta más veces que su objetivo.
2. **Esperado**: no pasa del objetivo (nunca «9 de 8») hasta canjear. Lo impone el servidor.

### CA-19 · Sellos: navegador sin cámara
1. Abre «Sellos» en un navegador sin `BarcodeDetector` (Firefox, Safari).
2. **Esperado**: aviso «tu navegador no puede leer el código con la cámara; escríbelo a mano o usa Chrome» en vez de esconder el botón.

### CA-20 · Wallet: qué falta y quién lo consigue
1. En «Sellos», mira la caja «Wallet del móvil».
2. **Esperado**: nombra Apple Wallet y Google Wallet y dice su estado. **Sin credenciales**: qué cuenta falta (Apple Developer, Google Wallet) y quién la consigue (el dueño o quien instale), sin remitir a ficheros del repositorio. Además dice el paso para activarlo: carpeta `wallet/apple` o `wallet/google`, `sellos.json` y `URL_PUBLICA`.

### CA-21 · Formularios: casillas del backoffice
1. Abre «Sellos» y «Promociones» a 360 y 1280 px.
2. **Esperado**: toda casilla («Programa activo», «Por correo», «En la tarjeta de Wallet»…) sale en la misma fila que su etiqueta y pegada a ella, no centrada ni lejos.

### CA-22 · Avisos vacíos
1. Abre «Sellos» y «Promociones».
2. **Esperado**: ninguna barra de aviso de color sin texto (p. ej. bajo «Buscar»).

### CA-23 · Promociones: enviar
1. Abre «Promociones», escribe título y texto y mira «Enviar promoción».
2. **Sin credenciales**: al abrir la pestaña, sin pulsar nada, un aviso nombra qué falta (`BREVO_API_KEY` y `BREVO_REMITENTE` en el `.env`, o conectar Wallet, con remisión a «Wallet del móvil» en Sellos para los pasos) y cómo probar sin cuenta (`CORREO_MODO=prueba`: los envíos se simulan); «Enviar promoción» desactivado con el motivo visible.
3. **Con canal** (modo prueba): se puede elegir «Por correo» y enviar (se acepta el aviso de confirmación); en «Registro» sale «Enviado (simulado)» y solo recibe quien dio permiso.

### CA-24 · Clientes con permiso y bajas
1. Abre «Promociones» y baja a «Clientes con permiso y bajas».
2. **Esperado**: quien dio permiso (y lo confirmó por el enlace del correo) sale «Con permiso» con su fecha; quien se dio de baja, como baja.

### CA-25 · Cifras
1. Abre «Cifras».
2. **Esperado**: las cuatro cifras (pedidos por QR, tarjetas guardadas, clics a la reseña, clientes que repiten) con la comparación con el mes anterior.

### CA-26 · Cifras: explicadas
1. En «Cifras», mira cada cifra.
2. **Esperado**: cada una dice «cuenta cuando…». Si todo está a cero, lo explica («todavía no hay datos…»).

### CA-27 · Cifras: mes con nombre
1. Mira el título de «Cifras».
2. **Esperado**: «octubre de 2026» (mes con nombre), no «2026-10».

### CA-28 · Reseña sin enlace de Google
1. Con un local sin `google_place_id` ni enlace de reseña, abre «Cifras».
2. **Esperado**: «Clics a la reseña» dice que no puede contar hasta tener el enlace de reseña y dónde ponerlo (abajo, en «Ajustes de reseñas», que valida y guarda). Con enlace, ese aviso no sale.

### CA-29 · `.env.example` completo
1. Abre `.env.example`.
2. **Esperado**: todas las variables (incluidas `CORREO_MODO`, `WALLET_MODO`, `BREVO_API_KEY`, `BREVO_REMITENTE`) con un comentario en castellano llano encima. El runner lo comprueba si el repo está a mano (`QA_REPO`); si no, es manual.

### CA-30 · Alérgenos
1. En el backoffice, abre un plato nuevo y pulsa «Guardar cambios» sin decidir sus alérgenos. **Esperado**: no guarda y explica «Falta decidir los alérgenos de «…»: marca los que lleva, «Sin alérgenos declarados» o «Todavía sin revisar»».
2. Guarda tres platos: uno con dos alérgenos marcados, otro con «Sin alérgenos declarados» y otro con «Todavía sin revisar».
3. La pestaña principal enseña un contador «⚠ n» de platos sin revisar; el aviso de arriba tiene un botón que filtra solo esos.
4. En la carta (a 360 y a 1280 px): el primero enseña iconos **con** su nombre; el segundo «Sin alérgenos declarados»; el tercero «Consulta al personal». En la carta, en la tarjeta Pedido y al enviar, aparece «Información facilitada por el restaurante; consulta al personal», y el dueño no puede quitarlo ni cambiarlo.
5. Envía un pedido con cada uno: la tarjeta de cocina enseña los mismos alérgenos en cada línea.
6. **Esperado**: el servidor rechaza (HTTP 400) un alérgeno que no sea uno de los 14 del anexo II. El runner lo automatiza (carta, cocina, pestaña y API) y devuelve el plato a como estaba.

### CA-31 · Idiomas
1. Abre la carta con el navegador en castellano, inglés, catalán, chino, francés, alemán, italiano y portugués (o con `Accept-Language` equivalente). **Esperado**: arranca en ese idioma; con un idioma que no es ninguno de los ocho (p. ej. neerlandés), en castellano.
2. En cada pantalla (carta, cocina, backoffice) cambia con el selector «Castellano / English / Català / 中文 / Français / Deutsch / Italiano / Português» y recarga. **Esperado**: se recuerda el idioma elegido y no queda texto en castellano pegado, ni en los avisos, ni en los correos, ni en la tarjeta.
3. En el backoffice, deja vacío el inglés de un plato y abre la carta en inglés. **Esperado**: ese campo sale en castellano; el resto, en inglés.
4. Con el programa de sellos activo, abre la carta o la tarjeta en cada idioma distinto del castellano tras un pedido servido. **Esperado**: el premio sale en ese idioma (el de fábrica viene traducido). En Sellos del backoffice, «Premio» tiene una casilla por idioma (en, ca, zh, fr, de, it, pt); vacía, cae a castellano.
5. El runner automatiza el primer paso, los diccionarios servidos, que los platos de la carta tienen castellano y el premio de la tarjeta por idioma.
6. **Manual (nativo)**: que el chino esté bien escrito. Sigue `docs/REVISION-CHINO.md`. Mientras no lo firme una persona nativa, el chino es provisional. Lo mismo para francés, alemán, italiano y portugués (traducción inicial sin revisión nativa).

### CA-32 · Exportar pedidos
1. Con la sesión del dueño, haz tres pedidos y sírvelos. Abre la pestaña «Exportar».
2. **Esperado**: «desde» y «hasta» vienen con el mes en curso (hasta hoy), la ayuda dice «Este documento no es una factura» y debajo sale cuántos pedidos y líneas hay y su total.
3. Pulsa «Descargar CSV» y «Descargar Excel». **Esperado**: ficheros `pedidos_AAAA-MM-DD_a_AAAA-MM-DD.csv` y `.xlsx`; el CSV abre en Excel con tildes y columnas bien (BOM, «;», coma decimal); la primera línea del CSV y la celda A1 y el nombre de la hoja del Excel dicen «no es una factura»; la suma de «Total del pedido» coincide con el total de la pantalla; no hay nombres, correos ni notas de clientes.
4. Elige un rango sin pedidos. **Esperado**: «No hay pedidos entre el … y el …»; el fichero, si se descarga, lleva solo el aviso y la cabecera.
5. Pon «desde» después de «hasta», o un rango de más de 366 días. **Esperado**: mensaje en castellano llano que dice qué cambiar, sin descarga.
6. Sin sesión, `/api/exportar` responde 401. El runner lo automatiza todo menos abrir el fichero en Excel/LibreOffice.

### CA-33 · Pedidos online: domicilio y recoger
1. En el backoffice, pestaña «Pedidos online»: activa domicilio y recoger, pon horario, pedido mínimo, gastos de envío y al menos un código postal. **Esperado**: sin códigos postales no deja activar el domicilio; recién instalado (sin la demo) todo sale desactivado.
2. Abre `/pedir` a 360 px, añade platos y pulsa enviar. **Esperado**: no pide mesa; pide tipo, nombre, teléfono, dirección y código postal (solo domicilio), hora («lo antes posible» o a una hora) y cómo prefiere pagar al recibir (tarjeta o efectivo, con nota para el cambio); enseña productos, gastos de envío e «Importe estimado» antes de enviar.
3. Prueba un código postal fuera de zona, una hora fuera de horario y un pedido por debajo del mínimo. **Esperado**: mensaje claro, sin pedido.
4. Envía. **Esperado**: va a `/seguir?t=…` con «Resumen de tu pedido», «No es factura ni ticket. El ticket te lo da el restaurante al entregar o recoger.» y el estado «Recibido». La cocina **no** lo ve todavía.
5. En el backoffice, «Aceptar» (minutos) → la cocina lo ve como nuevo; «Empezar» y «Listo» en cocina; a domicilio, la cocina dice «Espera al repartidor». «Hoja de reparto»: nombre, teléfono, dirección, platos, preferencia de pago y «Cobrar con el ticket de caja», **sin ningún importe**. «Sale a repartir» → el cliente ve «En camino»; «Entregado» → «Entregado».
6. Otro pedido: «Rechazar» con motivo. **Esperado**: el cliente ve «Rechazado» y el motivo; no cuenta en Exportar ni en Cifras. Un enlace de seguimiento con el token cambiado o con el id del pedido da 404.
7. Exportar. **Esperado**: columnas «Tipo» (Mesa, Domicilio, Recoger) y «Envío», y el total del pedido con el envío incluido, sin nombre, dirección ni teléfono, con el aviso «no es una factura». En ninguna pantalla aparece «cobrado», «cuenta» ni «factura» salvo en los avisos de «no es factura». El runner no lo automatiza todavía; `tests/test_pedidos_online.py` cubre la API.

### CA-34 · Reservas
1. En el backoffice, pestaña «Reservas»: ajustes con modo automático, aforo por tramo, horario por día y días cerrados. **Esperado**: recién instalado (sin la demo) sale desactivado y `/reservar` lo dice.
2. Abre `/reservar` a 360 px: fecha, una hora libre, comensales, nombre y teléfono (correo opcional) y nota. **Esperado**: bajo la nota, «No escribas datos de salud; los alérgenos se consultan en la carta y con el personal»; la casilla de publicidad, aparte y sin marcar; sin desplazamiento lateral.
3. Envía. **Esperado**: va a `/reserva?t=…` con «Confirmada», fecha, hora y comensales, sin teléfono, y botón «Cancelar la reserva».
4. Llena un tramo hasta el aforo. **Esperado**: en `/reservar` esa hora sale «completo»; si se llena mientras alguien rellena el formulario, al enviar dice «Esa hora ya está completa. Elige otra.» y no crea la reserva.
5. En «Reservas» (1280 px), el día: reservas por hora y «comensales por tramo frente al aforo». «Sentar» (mesa opcional) → el cliente ve «Ya estás en tu mesa». Otra, ya pasada su hora: «No presentada» (antes de la hora no sale el botón); si se deshace y el tramo ya está lleno, dice «No cabe: …» con los comensales y no la cambia. Pasada la hora más la cortesía no sale «Deshacer» (volver a confirmada), solo «Sentar». Otra: «Cancelar» con motivo → el cliente lo ve.
6. Modo manual: la reserva nace «Solicitada»; «Aceptar» la confirma y «Rechazar» pide motivo. Una solicitada sin respuesta pasa sola a rechazada al llegar su hora; una confirmada sin sentar, a «No presentada» a los minutos de cortesía.
7. Cancela desde el enlace del cliente; un enlace con el token cambiado o con el id da 404. Las rutas de sala sin sesión dan 401. El runner no lo automatiza todavía; `tests/test_reservas.py` cubre la API.

## Transversales

### CA-40 · `/salud`
1. Abre `/salud`.
2. **Esperado**: JSON con `ok: true` y `version` (la versión desplegada; vacía si no se arrancó con `GIT_SHA`).

### CA-41 · Recorrido completo
1. Recorre carta, cocina, `/tarjeta` y las diez pestañas del backoffice a 360 y 1280 px.
2. **Esperado**: sin errores en consola, sin desplazamiento lateral, sin peticiones a otros hosts y con la librería de QR servida desde el propio local.

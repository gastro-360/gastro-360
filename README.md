# Gastro 360

**Carta digital para restaurantes y bares, con pedidos desde la mesa y pantalla de cocina.** Software libre ([EUPL-1.2](LICENSE)), autoalojado y sin telemetría.

[English](README.en.md)

El cliente escanea el QR de su mesa, ve cada plato con foto y despiece por capas, quita ingredientes, añade extras y envía el pedido. La cocina lo recibe al momento en su propia pantalla y el cliente sigue el estado desde el móvil. El dueño lo gestiona todo desde un backoffice en el navegador.

## Qué hace

- **Carta y pedidos desde la mesa**: QR por mesa, pedido con notas, precios calculados siempre por el servidor y estado en vivo (recibido, en preparación, listo, servido). Funciona como app instalable (PWA).
- **Pantalla de cocina**: columnas por estado, botones grandes, aviso sonoro y minutos de espera.
- **Alérgenos**: los 14 de declaración obligatoria (Reglamento UE 1169/2011), con iconos y nombre, y distinguiendo «sin alérgenos declarados» de «sin revisar».
- **Tarjeta de sellos**: fidelización anónima, en la web o en Apple Wallet y Google Wallet.
- **Promociones solo con permiso**: casilla sin premarcar, prueba del consentimiento guardada, baja en cada mensaje (LSSI arts. 20 y 21). Envío por correo (Brevo) o aviso en la tarjeta de Wallet.
- **Reservas de mesa**: aforo por tramos, modo automático o manual, enlace para que el cliente consulte o cancele.
- **Pedidos para llevar y a domicilio**: zona por códigos postales, horarios, pedido mínimo y gastos de envío; el cliente paga al recibir.
- **Backoffice**: platos, raciones, ingredientes y fotos, mesas y QR imprimibles, cifras del mes y exportación de pedidos a CSV o Excel.
- **Ocho idiomas**: castellano, inglés, catalán, chino simplificado, francés, alemán, italiano y portugués, incluidos en el programa (sin traductor en línea).
- **Marca blanca**: nombre, logo, colores y textos de cada local en su propia carpeta (`restaurantes/<local>/marca.json`).

**Qué no hace:** no cobra (no hay pasarela de pago), no imprime tickets y no emite facturas. El cobro sigue en la caja del restaurante.

**Privacidad:** el navegador solo habla con tu servidor. El servidor solo sale a Internet por los canales que configures tú (Brevo, Apple/Google Wallet, Telegram); recién instalado no hace ninguna conexión saliente.

## Instalar

Solo hace falta Docker con Compose:

```
git clone https://github.com/gastro-360/gastro-360.git && cd gastro-360
./instalar.sh                # prueba local con un restaurante de demostración
./instalar.sh --produccion   # servidor real, con tu dominio y HTTPS automático
```

Al terminar, el instalador muestra las direcciones de la carta, la cocina (`/cocina`) y el backoffice (`/admin`), y la contraseña del backoffice (una sola vez). En modo prueba, el correo y Wallet se simulan y nada sale a Internet.

- Sin Docker (Python 3.10+): [docs/INSTALAR-AVANZADO.md](docs/INSTALAR-AVANZADO.md).
- Configuración: [`.env.example`](.env.example) documenta todas las variables.
- Todo lo demás (Docker en producción, datos, Wallet, promociones, reservas, pedidos online, exportación): [docs/MANUAL.md](docs/MANUAL.md).

## Pruebas

```
tests/unitarias.sh                        # unitarias (cada módulo en su proceso)
tests/contenedor.sh                       # contra el contenedor Docker
tests/e2e.sh                              # navegador (Playwright) a 360 y 1280 px
tests/privacidad.sh                       # el navegador no pide nada a otros hosts
```

## Estructura

| Carpeta | Contenido |
|---|---|
| `carta/` | Servidor (Python, biblioteca estándar), páginas de carta, cocina, backoffice, reservas y pedidos online |
| `restaurantes/demo/` | Restaurante ficticio de demostración (platos, fotos y marca) |
| `docker/`, `Dockerfile`, `docker-compose.yml` | Imagen de la app y Caddy para HTTPS |
| `tests/` | Pruebas unitarias, de contenedor, E2E, privacidad y seguridad |
| `docs/` | Manual técnico, instalación avanzada, guion de aceptación, diseño y textos legales de plantilla |

## Licencia y garantía

[EUPL-1.2](LICENSE) ([English](LICENSE.en)). Se ofrece **sin garantía** de ningún tipo ([SUPPORT.md](SUPPORT.md)). Componentes de terceros en [THIRD-PARTY.md](THIRD-PARTY.md). Los textos legales de `docs/legal/` son plantillas: revísalos con un profesional antes de usarlos.

Contribuciones: [CONTRIBUTING.md](CONTRIBUTING.md). Seguridad: [SECURITY.md](SECURITY.md).

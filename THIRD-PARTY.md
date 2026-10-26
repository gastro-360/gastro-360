# Componentes de terceros

Todo lo que carga el navegador se sirve desde la propia aplicación (`carta/vendor/`); no se pide nada a servidores ajenos.

## qrcode-generator 1.4.4

- Uso: dibujar los códigos QR de las mesas (backoffice) y de la tarjeta de sellos.
- Autoría: Kazuhiko Arase.
- Licencia: MIT. Texto completo en `carta/vendor/qrcode-generator/LICENSE`, que debe acompañar a cualquier copia del fichero `qrcode.min.js`.

## Tipografías

- Inter (variable, latín y latín extendido) y Noto Sans SC (variable, subconjunto de 20 trozos con los ideogramas que usa la interfaz en chino). Licencia SIL OFL 1.1; texto y autorías en `carta/estatico/fuentes/LICENCIAS.md`, que debe acompañar a los `.woff2`.
- Se sirven desde `carta/estatico/fuentes/`; el navegador no pide fuentes a ningún servidor ajeno. Un ideograma fuera del subconjunto cae a la fuente CJK del sistema.

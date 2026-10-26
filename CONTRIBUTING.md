# Contribuir

Gracias por querer mejorar Gastro 360.

- **Licencia**: toda contribución se publica bajo [EUPL-1.2](LICENSE). Al enviarla aceptas que se distribuya con esa licencia. Los ficheros de código llevan la cabecera `SPDX-License-Identifier: EUPL-1.2`.
- **Flujo**: haz un *fork*, trabaja en una rama propia con commits pequeños y abre un *pull request* contra `main`. Para cambios grandes, abre antes un *issue* y lo hablamos.
- **Antes de enviar**: ejecuta las pruebas (`tests/unitarias.sh`; `tests/contenedor.sh` si tocas el servidor o Docker, y `tests/e2e.sh` si tocas las páginas) y actualiza `README.md` o `docs/MANUAL.md` si el cambio los afecta.
- **Alcance**: el producto no cobra, no imprime tickets ni factura, y el navegador no carga recursos de terceros ni telemetría. Las propuestas que lo cambien se discuten antes en un *issue*.
- **Sin secretos**: nunca subas `.env`, claves, contraseñas ni datos de clientes.
- **Un local concreto no es parte del código**: lo propio de un restaurante va en `restaurantes/<local>/`, no en `carta/`.
- **Seguridad**: los fallos de seguridad no se cuentan en un *issue* público; mira [SECURITY.md](SECURITY.md).

# Seguridad

## Versiones con soporte

Solo se corrige la última versión de la rama `main`.

## Cómo avisar de una vulnerabilidad

**No abras un *issue* público.** Usa el aviso privado de GitHub: pestaña **Security → Report a vulnerability** de este repositorio.

Cuenta qué versión usas (lo dice `/salud`), los pasos para reproducirlo y qué impacto crees que tiene. No incluyas datos reales de clientes ni contraseñas.

Gastro 360 se ofrece sin garantía ni compromiso de plazo (ver [SUPPORT.md](SUPPORT.md)), pero los avisos de seguridad se miran antes que el resto.

## Lo que ya cubre el diseño

- El navegador solo habla con el propio servidor (CSP `default-src 'self'`, sin CDN ni telemetría).
- Los precios los calcula siempre el servidor; los frenos por IP solo leen la IP real de proxies de confianza (`PROXY_CONFIABLE`).
- Secretos (`.env`, contraseñas, credenciales de Wallet) y datos personales (`*.db`, pedidos, reservas) quedan fuera de git.
- Las pruebas de regresión de seguridad están en [`tests/pentest/`](tests/pentest/).

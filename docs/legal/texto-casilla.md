# Texto de la casilla de permiso (plantilla)

> **Borrador: debe revisarlo un abogado antes de usarse con clientes reales.** No es asesoramiento legal.

Este es el texto que ve el cliente junto a la casilla, al enviar un pedido. Es el mismo que usa el código
(`texto_permiso()` en `carta/clientes.py`); `{nombre}` se sustituye por el nombre del restaurante (`marca.json` → `nombre`).

## Versión vigente: 2

<!-- TEXTO-CASILLA:INICIO -->
Quiero que {nombre} me envíe promociones y novedades por correo electrónico y, si tengo su tarjeta de sellos en el móvil, como aviso en esa tarjeta. Puedo darme de baja cuando quiera con el enlace que llevará cada mensaje.
<!-- TEXTO-CASILLA:FIN -->

- Cubre dos canales: **correo** (versiones 1 y 2) y **aviso en la tarjeta de Wallet** (solo versión 2). En el código, `CUBRE` en `carta/clientes.py`.
- La casilla **nunca va premarcada**. Sin marcarla no se guarda ningún correo (LSSI art. 21: permiso expreso).
- Junto a la casilla se pide el correo ("Tu correo (solo si quieres promociones)"): solo se usa para promociones.
- **Alta directa (por defecto)**: marcar la casilla basta para la LSSI art. 21. Se guarda al instante la **prueba**: texto exacto, versión, fecha y hora, idioma y canal (`pedido-carta`), sin correo de confirmación. Riesgo aceptado: quien conozca un correo ajeno puede darlo de alta; cada mensaje lleva baja.
- **Doble confirmación (opcional, `CONFIRMACION_DOBLE=1`)**: el alta se da solo tras confirmar: al enviar el pedido se manda un correo con un enlace de un solo uso (máximo uno por hora y dirección, caduca a los 7 días, lo invalida una baja) y solo el clic del titular registra el alta. De cada alta se guarda en el servidor la **prueba**: texto exacto (el que vio al marcar la casilla), versión, fecha y hora de la confirmación, y canal (`pedido-carta+enlace-confirmacion`). De cada baja, fecha y canal (`enlace-baja`). Las filas no se editan ni se borran.
- **Baja en cada mensaje**: enlace propio que pide confirmación y solo entonces registra la baja. Los envíos llevan «Publicidad:» en el asunto (LSSI art. 20).
- Sin relación comercial previa no hay excepción del art. 21.2: solo se envía a quien marcó la casilla.

## Historial de versiones

| Versión | Texto | Cubre |
|---|---|---|
| 1 | Quiero que {nombre} me envíe promociones y novedades por correo electrónico. Puedo darme de baja cuando quiera con el enlace que llevará cada mensaje. | correo |
| **2** | (el de arriba) | correo y aviso en Wallet |

## Si hay que cambiar el texto

1. Cambiar el texto en `texto_permiso()` **y en este documento**.
2. Subir `TEXTO_VERSION` en `carta/clientes.py` y añadir la fila al historial de arriba.
3. Decidir qué canales cubre la versión nueva (`CUBRE`). Quien dio permiso con una versión que no cubre un canal no recibe nada por él.
4. Ejecutar `python3 -m unittest tests.test_papeles -v`: falla si este documento y el código no coinciden.

## Pendiente de revisión legal

- Falta enlazar desde la casilla la **política de privacidad** del restaurante (responsable, finalidad, derechos, conservación). Si el enlace entra en el texto de la casilla, es una versión nueva.
- Revisar el texto del correo de confirmación (`correo.confirmacion.*` en `carta/i18n/`, solo con `CONFIRMACION_DOBLE=1`) y decidir qué hacer con los clientes con alta anterior a la doble confirmación (no se han tocado).

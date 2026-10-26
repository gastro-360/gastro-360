# Revisión del chino (para una persona nativa)

Gracias por ayudar. No hace falta saber de informática. Esta guía explica cómo ver el programa en chino y cómo apuntar lo que haya que corregir.

**Importante: el chino que hay ahora es provisional.** Lo ha redactado una persona sin ser nativa y sin traductor automático. Hasta que alguien nativo lo revise y lo dé por bueno, no se debe presentar como validado a ningún cliente.

## 1. Cómo ver el programa en chino

1. Abre la dirección de la carta (te la dará quien te pida la revisión) en el navegador.
2. Arriba, en cada pantalla, hay un selector de idioma: **Castellano / English / Català / 中文 / Français / Deutsch / Italiano / Português**. Pulsa **中文**. La elección se recuerda.
3. Otra forma: pon el navegador en chino (Ajustes del navegador → Idiomas → 中文 el primero de la lista) y abre la carta en una ventana nueva. Arranca ya en chino.
4. Para volver a otro idioma, usa el mismo selector.

## 2. Qué pantallas mirar

Marca cada una cuando la hayas revisado.

**Carta (la ven los clientes)**
- [ ] Lista de platos (secciones, nombres, precios, botones)
- [ ] Un plato abierto (descripción, ingredientes, quitar y añadir extras, alérgenos)
- [ ] El pedido (mesa, notas, enviar)
- [ ] El resumen y el estado del pedido (avisos y mensajes de error, por ejemplo con un pedido vacío)

**Cocina**
- [ ] Pantalla de entrada con la clave
- [ ] Tablero de pedidos (nuevo, en preparación, listo, servido; avisos de espera)

**Backoffice (el dueño)**: entra con la clave que te den y recorre cada pestaña
- [ ] Todas las pestañas, una a una, con sus botones, avisos y mensajes de error (guarda algo mal a propósito para ver el error)
- [ ] La pestaña de cifras (nombres de meses y números)

**Mensajes que salen del programa**
- [ ] Correo de promoción (en modo de prueba te lo enseñan)
- [ ] Página de baja de las promociones (el enlace del pie del correo)
- [ ] Página de la tarjeta de sellos (`/tarjeta`)
- [ ] Textos de la tarjeta de Wallet (Apple Wallet y Google Wallet)

## 3. Dónde están los textos (por si quieres corregirlos tú)

| Qué | Fichero |
|---|---|
| Todos los textos del programa (botones, avisos, errores, correos…) | `carta/i18n/zh.json` |
| Platos, secciones e ingredientes de la carta de ejemplo | `restaurantes/demo/datos.json` (campos `"zh"`) |
| Lema, presentación y aviso del pie | `restaurantes/demo/marca.json` (campos `"zh"`) |

En `zh.json` cada línea es `"clave": "texto en chino"`. La clave (lo de la izquierda) **no se toca**; solo el texto de la derecha. Unos textos llevan marcas entre llaves, como `{n}` o `{nombre}`: son huecos que el programa rellena (un número, un nombre…). **Déjalas tal cual**, en el sitio de la frase donde suenen bien. Para ver qué dice el original, mira la misma clave en `carta/i18n/es.json`.

Para localizar un texto que ves en pantalla: busca en `zh.json` ese texto en chino con la función de buscar del editor; la clave de esa línea te dice la pantalla (`carta.…`, `cocina.…`, `admin.…`, etc.).

## 4. Cómo apuntar las correcciones

Si no quieres tocar ficheros, rellena una tabla como esta y envíala:

| Pantalla | Texto actual (chino) | Propuesta | Comentario |
|---|---|---|---|
| Carta · pedido | (copia lo que sale) | (cómo debería decir) | (p. ej. «suena poco natural», «demasiado largo», «en China se dice…») |

Si sabes editar ficheros, corrige directamente `zh.json` (y los datos de la demo) y devuelve el fichero. Cosas útiles de señalar:
- Frases que suenan a traducción literal.
- Palabras de cocina o de hostelería que no se usan así.
- Textos demasiado largos para un botón.
- Tratamiento (您 / 你): ¿cuál suena mejor en una carta de restaurante?
- Caracteres tradicionales por error (aquí es **chino simplificado**).

## 5. Al terminar

Quien coordina incorpora tus cambios (por ejemplo, con un *pull request*). Hasta ese momento el chino se considera **provisional, sin revisar por un nativo**.

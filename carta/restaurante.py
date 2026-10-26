# SPDX-License-Identifier: EUPL-1.2
"""Restaurante activo: todo lo propio de un local (datos, fotos, marca, contraseña, pedidos) vive en
restaurantes/<RESTAURANTE>/ y el código común no lo conoce. Se elige con la variable de entorno RESTAURANTE (por defecto demo).

CARTA_RESTAURANTES y CARTA_WEB (opcionales) cambian dónde están las carpetas de restaurantes y la carpeta web/ generada;
sirven para las pruebas automáticas y para Docker."""
import html, json, os, re

import alergenos
import idiomas

BASE = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.environ.get("CARTA_RESTAURANTES") or os.path.join(os.path.dirname(BASE), "restaurantes")
WEB = os.environ.get("CARTA_WEB") or os.path.join(BASE, "web")
NOMBRE = os.environ.get("RESTAURANTE", "demo")
if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", NOMBRE):
    raise SystemExit(f"RESTAURANTE no válido: {NOMBRE!r} (solo minúsculas, números, guiones)")
DIR = os.path.join(RAIZ, NOMBRE)
if not os.path.isdir(DIR):
    raise SystemExit(f"No existe el restaurante {NOMBRE!r}: falta la carpeta {DIR}")
MARCA_DIR = os.path.join(DIR, "marca")

# Nombre del producto: se define solo en producto.json y todo lo demás lo lee de ahí.
with open(os.path.join(BASE, "producto.json"), encoding="utf-8") as _f:
    PRODUCTO = json.load(_f)["nombre"]

# Lo que no esté en marca.json sale de aquí (un marca.json mínimo con nombre y logo basta). Tema neutro: cada local pone el suyo.
COLORES = {"fondo": "#111315", "primario": "#8FB8C9", "primario_suave": "#1B262C",
           "acento": "#E0A458", "acento_suave": "#2B2216", "acento_texto": "#EDBF7E"}
# Forma: radio de las esquinas (px) y densidad del espaciado.
FORMA = {"radio": 8, "densidad": "normal"}
DENSIDAD = {"compacta": 3, "normal": 4, "amplia": 5}
# Familias tipográficas (CSS font-family). Inter va en local (carta/estatico/fuentes); nada se pide a servidores de terceros.
TIPOGRAFIA = {"titulos": 'Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif',
              "texto": 'Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif',
              "mono": 'ui-monospace,Consolas,"DejaVu Sans Mono",monospace'}
# Cómo llama el local a lo que se monta en la carta (en masculino singular y plural: «Tu plato», «Nuevo plato»).
TEXTOS = {"plato": "plato", "platos": "platos"}
# Textos de marca.json que se pueden dar por idioma: un texto (solo castellano) o {"es": …, "en": …, "ca": …, "zh": …, "fr": …, "de": …, "it": …, "pt": …}
CAMPOS_IDIOMA = ("lema", "intro", "descripcion", "aviso_pie")
POR_DEFECTO = {
    "lema": {i: idiomas.t("marca.lema_defecto", i) for i in idiomas.IDIOMAS},
    "intro": {i: idiomas.t("marca.intro_defecto", i) for i in idiomas.IDIOMAS},
}
# Respaldo para los ideogramas chinos en cada familia tipográfica (fuentes del sistema; nada se pide fuera)
RESPALDO_CJK = ',"Noto Sans SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC","Source Han Sans SC","WenQuanYi Micro Hei","WenQuanYi Zen Hei"'
_FUENTE = re.compile(r'[A-Za-z0-9 ,"\'_-]{1,200}')
_PROHIBIDO = re.compile(r"[\x00-\x1f`\\]|\$\{|\{\{")   # romperían una página o una plantilla de JavaScript


def cargar_marca(carpeta):
    """Lee y completa el marca.json de una carpeta de restaurante. Lanza ValueError si no es válido."""
    with open(os.path.join(carpeta, "marca.json"), encoding="utf-8") as f:
        return completar_marca(json.load(f))


def _texto_idiomas(k, v):
    """Un texto de marca.json: un texto (castellano) o {idioma: texto} con el castellano relleno."""
    piezas = [v] if isinstance(v, str) else list(v.values()) if isinstance(v, dict) else None
    if piezas is None or (isinstance(v, dict) and (not v.get("es") or any(i not in idiomas.IDIOMAS for i in v))):
        raise ValueError(f"marca.json: «{k}» tiene que ser un texto o un objeto con los idiomas ({', '.join(idiomas.IDIOMAS)}) y el castellano relleno")
    for x in piezas:
        if not isinstance(x, str) or not x.strip() or _PROHIBIDO.search(x):
            raise ValueError(f"marca.json: «{k}» no es un texto válido")


def completar_marca(m):
    for campo in ("nombre", "logo"):
        if not isinstance(m.get(campo), str) or not m[campo].strip():
            raise ValueError(f"marca.json: falta «{campo}»")
    m = {**POR_DEFECTO, **m}
    m.setdefault("nombre_corto", m["nombre"])
    m["colores"] = {**COLORES, **(m.get("colores") or {})}
    m["tipografia"] = {**TIPOGRAFIA, **(m.get("tipografia") or {})}
    m["textos"] = {**TEXTOS, **(m.get("textos") or {})}
    m.setdefault("nombre_resalte", m["nombre"].rsplit(" ", 1)[-1])
    m.setdefault("descripcion", {i: idiomas.t("marca.descripcion_defecto", i, nombre=m["nombre"]) for i in idiomas.IDIOMAS})
    m.setdefault("color_fondo", m["colores"]["fondo"])
    if not m["nombre"].endswith(m["nombre_resalte"]):
        raise ValueError("marca.json: «nombre_resalte» tiene que ser el final de «nombre»")
    for k, v in m["tipografia"].items():
        if not isinstance(v, str) or not v.strip() or _PROHIBIDO.search(v):
            raise ValueError(f"marca.json: «{k}» no es un texto válido")
    for k, v in m["textos"].items():
        _texto_idiomas(f"{k} (textos)", v)
    for k in CAMPOS_IDIOMA:
        if k in m:
            _texto_idiomas(k, m[k])
    for k, v in m["tipografia"].items():
        if k not in TIPOGRAFIA or not _FUENTE.fullmatch(v):
            raise ValueError(f"marca.json: tipografía «{k}» no válida (titulos, texto o mono; solo letras, comas y comillas)")
    for k in m["textos"]:
        if k not in TEXTOS:
            raise ValueError(f"marca.json: texto «{k}» desconocido (plato, platos)")
    for k, v in m.items():
        if isinstance(v, str) and k not in CAMPOS_IDIOMA and _PROHIBIDO.search(v):
            raise ValueError(f"marca.json: «{k}» lleva caracteres no permitidos (` \\ ${{ {{{{ o de control)")
    for k, v in m["colores"].items():
        if not isinstance(v, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
            raise ValueError(f"marca.json: color «{k}» no válido (formato #RRGGBB)")
    f = m.get("forma", {})
    if not isinstance(f, dict) or any(k not in FORMA for k in f):
        raise ValueError("marca.json: «forma» admite solo «radio» y «densidad»")
    if "radio" in f and (isinstance(f["radio"], bool) or not isinstance(f["radio"], int) or not 0 <= f["radio"] <= 24):
        raise ValueError("marca.json: «forma.radio» es un número entero de 0 a 24 (píxeles)")
    if "densidad" in f and f["densidad"] not in DENSIDAD:
        raise ValueError("marca.json: «forma.densidad» es compacta, normal o amplia")
    if os.path.basename(m["logo"]) != m["logo"]:
        raise ValueError("marca.json: «logo» es un nombre de archivo dentro de marca/")
    if m.get("resena_url") and not re.fullmatch(r"https://[^\s\"'<>]+", m["resena_url"]):
        raise ValueError("marca.json: «resena_url» tiene que ser un enlace https:// sin espacios")
    if m.get("google_place_id") and not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", m["google_place_id"]):
        raise ValueError("marca.json: «google_place_id» no es un identificador de lugar de Google válido")
    return m


def resena_url(m):
    """Enlace para dejar una reseña en Google: el mismo para todos los clientes. Vacío si el restaurante aún no lo tiene."""
    if m.get("resena_url"):
        return m["resena_url"]
    if m.get("google_place_id"):
        return "https://search.google.com/local/writereview?placeid=" + m["google_place_id"]
    return ""


def guardar_resena(texto):
    """Pone (o quita, si va vacío) el enlace de reseñas de Google en marca.json: un https:// completo o el identificador de lugar.
    Valida antes de escribir y deja el archivo como estaba si no es válido. Devuelve el enlace resultante (vacío si se quitó)."""
    if not isinstance(texto, str):
        raise ValueError("Escribe el enlace o el identificador de lugar")
    texto = texto.strip()
    ruta = os.path.join(DIR, "marca.json")
    with open(ruta, encoding="utf-8") as f:
        m = json.load(f)
    m.pop("resena_url", None)
    m.pop("google_place_id", None)
    if texto.lower().startswith("http"):
        m["resena_url"] = texto
    elif texto:
        m["google_place_id"] = texto
    try:
        completar_marca(m)
    except ValueError:
        raise ValueError("Pon un enlace que empiece por https:// (sin espacios) o el identificador de lugar de Google, que empieza por ChIJ")
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, ruta)
    _repintar_portada(resena_url(m))
    return resena_url(m)


def _repintar_portada(url):
    """La portada de web/ se genera al arrancar; aquí solo se cambia su enlace de reseña para que se vea sin reiniciar."""
    ruta = os.path.join(WEB, "index.html")
    if not os.path.isfile(ruta):
        return
    with open(ruta, encoding="utf-8") as f:
        pagina = f.read()
    valor = json.dumps(url, ensure_ascii=False).replace("<", "\\u003c")
    nueva, n = re.subn(r'const RESENA=(?:"(?:[^"\\]|\\.)*"|null);', lambda _: f"const RESENA={valor};", pagina, count=1)
    if n:
        with open(ruta + ".tmp", "w", encoding="utf-8") as f:
            f.write(nueva)
        os.replace(ruta + ".tmp", ruta)


def marca():
    try:
        return cargar_marca(DIR)
    except (ValueError, OSError) as e:
        raise SystemExit(f"Restaurante {NOMBRE!r}: {e}")


def _mayuscula(t):
    return t[:1].upper() + t[1:]


def _mayuscula_idiomas(v):
    return {k: _mayuscula(x) for k, x in v.items()} if isinstance(v, dict) else _mayuscula(v)


def _por_idioma(v):
    return v if isinstance(v, dict) else {"es": v}


def plantilla(texto):
    """Rellena los {{marcadores}} de las páginas con la marca del restaurante activo.
    {{x}} va escapado para HTML; {{js:x}} es un valor de JavaScript (texto entre comillas, u objeto si es {{js:textos}});
    {{x_css}} es una familia tipográfica ya validada y {{pie_html}} el pie de página ya escapado."""
    m = marca()
    c = m["colores"]
    t = m["textos"]
    es = lambda v: idiomas.tr(v, "es")
    pie = [f'<span class="sel">{html.escape(m[k], quote=True)}</span>' for k in ("direccion", "telefono") if m.get(k)]
    if m.get("aviso_pie"):
        pie.append(f'<span data-marca="aviso_pie">{html.escape(es(m["aviso_pie"]), quote=True)}</span>')
    textos_idioma = {**{k: _por_idioma(v) for k, v in t.items()},
                     "plato_cap": _mayuscula_idiomas(_por_idioma(t["plato"])), "platos_cap": _mayuscula_idiomas(_por_idioma(t["platos"]))}
    marca_idioma = {k: _por_idioma(m[k]) for k in CAMPOS_IDIOMA if k in m}
    valores = {
        "producto": PRODUCTO,
        "nombre": m["nombre"], "nombre_corto": m["nombre_corto"], "nombre_resalte": m["nombre_resalte"],
        "nombre_inicio": m["nombre"][:len(m["nombre"]) - len(m["nombre_resalte"])],
        "lema": es(m["lema"]), "intro": es(m["intro"]), "logo": m["logo"], "slug": NOMBRE,
        "resena_url": resena_url(m),
        "aviso_alergenos": alergenos.AVISO,   # fijo: no sale de marca.json
        "plato": es(t["plato"]), "platos": es(t["platos"]), "plato_cap": _mayuscula(es(t["plato"])), "platos_cap": _mayuscula(es(t["platos"])),
        "textos": textos_idioma,   # {plato: {es, en…}, platos, plato_cap, platos_cap}: en la página, I18N.tr(TXT.plato)
        "marca_i18n": marca_idioma,   # lema, intro, descripcion y aviso_pie por idioma: window.MARCA_I18N
        "c_fondo": c["fondo"], "c_primario": c["primario"], "c_primario_suave": c["primario_suave"],
        "c_acento": c["acento"], "c_acento_suave": c["acento_suave"], "c_acento_texto": c["acento_texto"],
        "f_titulos_css": m["tipografia"]["titulos"] + RESPALDO_CJK, "f_texto_css": m["tipografia"]["texto"] + RESPALDO_CJK,
        "f_mono_css": m["tipografia"]["mono"] + RESPALDO_CJK,
        "pie_html": "".join(pie),
    }

    def sustituye(mo):
        js, clave = mo.group(1), mo.group(2)
        if clave not in valores:
            raise KeyError(f"marcador desconocido: {{{{{mo.group(0)[2:-2]}}}}}")
        v = valores[clave]
        if js:
            return json.dumps(v, ensure_ascii=False).replace("<", "\\u003c")
        if clave.endswith(("_css", "_html")):
            return v
        return html.escape(v, quote=True)

    return re.sub(r"\{\{(js:)?([a-z0-9_]+)\}\}", sustituye, texto)

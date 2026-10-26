# SPDX-License-Identifier: EUPL-1.2
"""Servidor de la carta de un restaurante (el de la variable RESTAURANTE): sirve la carta (carpeta web/), el backoffice (/admin),
la pantalla de cocina (/cocina), recibe los pedidos de las mesas y guarda los cambios en datos.json. Usa la biblioteca estándar de Python; para subir fotos desde el
backoffice hacen falta además Pillow, numpy y scipy (los mismos que recorte.py).

Uso:
  python servidor.py                 arranca en el puerto 8080 (accesible desde la red local)
  python servidor.py --puerto 9000   otro puerto
  python servidor.py --clave NUEVA   cambia la contraseña del backoffice y sale

La primera vez crea una contraseña al azar, la muestra en pantalla y la guarda en clave_inicial.txt.
Cada vez que se guardan cambios se hace una copia de seguridad en copias/.
"""
import argparse, datetime, hashlib, hmac, http.server, ipaddress, json, os, re, secrets, shutil, socket, socketserver, sys, threading, time
from urllib.parse import urlparse, parse_qs

import alergenos
import clientes, correo
import exportar, idiomas, tema
import kpis
import pedidos_online
import promociones, promociones_web
import reservas
import restaurante
import seguridad
import sellos
import tarjeta_web
import wallet

BASE = os.path.dirname(os.path.abspath(__file__))
RDIR = restaurante.DIR   # carpeta del restaurante activo (variable RESTAURANTE, por defecto demo)
WEB = restaurante.WEB
DATOS = os.path.join(RDIR, "datos.json")
ADMIN = os.path.join(BASE, "admin.html")
CONFIG = os.path.join(RDIR, "config.json")
COPIAS = os.path.join(RDIR, "copias")
FOTOS_JSON = os.path.join(RDIR, "fotos.json")
COCINA = os.path.join(BASE, "cocina.html")
SEGUIR = os.path.join(BASE, "seguir.html")   # seguimiento de un pedido online (/seguir?t=TOKEN)
RESERVAR = os.path.join(BASE, "reservar.html")   # pedir mesa (/reservar)
RESERVA = os.path.join(BASE, "reserva.html")     # la reserva del cliente (/reserva?t=TOKEN)
PEDIDOS = os.path.join(RDIR, "pedidos.json")
HISTORIAL = os.path.join(RDIR, "historial")
SESIONES = os.path.join(RDIR, "sesiones.json")
AJUSTES = os.path.join(RDIR, "ajustes.json")          # interruptor «Aceptar pedidos»
COPIAS_PEDIDOS = os.path.join(RDIR, "copias_pedidos")
COPIA_HORAS = float(os.environ.get("COPIA_HORAS", "6"))   # cada cuántas horas se copian los pedidos (0 = nunca)
COPIAS_PEDIDOS_MAX = 60
# Proxies de los que nos fiamos para leer la IP real (X-Forwarded-For / CF-Connecting-IP) y el protocolo (X-Forwarded-Proto): lista separada
# por comas de IP, redes CIDR o nombres de host (en Docker, «caddy»). Vacío (por defecto) = no nos fiamos de nadie: se usa la IP del socket.
PROXY_CONFIABLE = [x.strip() for x in os.environ.get("PROXY_CONFIABLE", "").split(",") if x.strip()]
INICIO = time.time()
COOKIE = restaurante.NOMBRE + "_sesion"   # una cookie distinta por restaurante
SESION_HORAS = 12
RECORDAR_DIAS = 30     # «recordar este dispositivo» (la tablet de cocina)
ESTADOS = ["nuevo", "preparando", "listo", "entregado"]
MAX_MESA = 200
CAMBIO_DIA = 5         # hora a la que empieza un día nuevo de servicio (vuelve el pedido 1): el local está cerrado
GRUPOS = ["carnes", "embutidos", "quesos", "verduras", "salsas"]
NOMBRES_GRUPO = {"carnes": "Carnes", "embutidos": "Embutidos y pescado", "quesos": "Quesos", "verduras": "Verduras", "salsas": "Salsas"}
FORMAS = ["meat", "strands", "bacon", "balls", "sausage", "slab", "ham", "coins", "smear", "tuna",
          "cheeseFlat", "cheese", "leaf", "tomato", "onion", "sticks", "pepper", "olives", "sauce"]

MAX_PEDIDOS_IP = int(os.environ.get("MAX_PEDIDOS_IP", "10"))   # pedidos por IP cada 10 minutos
MAX_RESERVAS_IP = int(os.environ.get("MAX_RESERVAS_IP", "10"))   # reservas por IP cada 10 minutos (cupo aparte del de pedidos)
RUTAS_TARJETA = ("/tarjeta", "/wallet/", "/api/tarjeta", "/api/sellos", "/api/wallet")
RUTAS_PROMOCIONES = "/api/promociones"
bloqueo = threading.Lock()
sesiones = {}          # sha256(token) -> caduca (epoch). Se guardan en sesiones.json para sobrevivir a un reinicio
intentos = {}          # ip -> [epoch de intentos fallidos]
envios = {}            # ip -> [epoch de pedidos enviados]
envios_reservas = {}   # ip -> [epoch de reservas enviadas] (no comparte cupo con los pedidos)
clics = {}             # ip -> [epoch de clics a la reseña]


MARCADOR_IDIOMA = b'<meta name="gastro-idioma" content="">'


def log(msg):
    print(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}", flush=True)


def huella(token):
    return hashlib.sha256(token.encode()).hexdigest()


def cargar_sesiones():
    try:
        ahora = time.time()
        sesiones.update({k: v for k, v in json.load(open(SESIONES)).items() if v > ahora})
    except (OSError, ValueError, AttributeError):
        pass


def guardar_sesiones():
    ahora = time.time()
    for k in [k for k, v in sesiones.items() if v <= ahora]:
        del sesiones[k]
    tmp = SESIONES + ".tmp"
    json.dump(sesiones, open(tmp, "w"))
    os.replace(tmp, SESIONES)


# ---------- páginas con la marca del restaurante ----------
def pagina(ruta):
    with open(ruta, encoding="utf-8") as f:
        return restaurante.plantilla(f.read()).encode("utf-8")


# ---------- baja de publicidad ----------
# ---------- contraseña ----------
def hash_clave(clave, sal):
    return hashlib.pbkdf2_hmac("sha256", clave.encode(), bytes.fromhex(sal), 200_000).hex()


def guardar_clave(clave):
    sal = secrets.token_hex(16)
    json.dump({"sal": sal, "hash": hash_clave(clave, sal)}, open(CONFIG, "w"))


def comprobar_clave(clave):
    c = json.load(open(CONFIG))
    return hmac.compare_digest(hash_clave(clave, c["sal"]), c["hash"])


# ---------- datos ----------
def leer_datos():
    with open(DATOS, encoding="utf-8") as f:
        return json.load(f)


def num(v, campo):
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0 or v > 999:
        raise idiomas.Msg("srv.val.precio", campo=campo)
    return round(float(v), 2)


def texto(v, campo, maximo=120, vacio=False):
    if not isinstance(v, str) or len(v.strip()) > maximo or (not vacio and not v.strip()):
        raise idiomas.Msg("srv.val.texto", campo=campo)
    return v.strip()


def color(v, campo):
    if not isinstance(v, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
        raise idiomas.Msg("srv.val.color", campo=campo)
    return v


def ident(v, campo):
    if not isinstance(v, str) or not re.fullmatch(r"[a-z0-9_]{1,40}", v):
        raise idiomas.Msg("srv.val.ident", campo=campo)
    return v


def validar(d, idioma=idiomas.FUENTE):
    """Comprueba la estructura y devuelve una copia limpia. Lanza idiomas.Msg (un ValueError) con un mensaje claro;
    las etiquetas de los campos salen ya en el idioma de quien edita."""
    T = lambda clave, **p: idiomas.t(clave, idioma, **p)
    if not isinstance(d, dict):
        raise idiomas.Msg("srv.val.formato")
    ing = {}
    for k, g in (d.get("ingredientes") or {}).items():
        ident(k, T("srv.etq.ingrediente"))
        nombre_g = idiomas.limpiar_campo(g.get("n"), T("srv.etq.ingrediente_id", id=k), 120)
        n = idiomas.tr(nombre_g, idioma)
        if g.get("cat") not in GRUPOS:
            raise idiomas.Msg("srv.val.grupo", n=n)
        if g.get("s") not in FORMAS:
            raise idiomas.Msg("srv.val.forma", n=n)
        limpio = {"n": nombre_g, "cat": g["cat"], "p": None if g.get("p") is None else num(g["p"], n),
                  "s": g["s"], "h": max(2, min(30, int(g.get("h") or 8))), "c": color(g.get("c"), n)}
        for extra in ("fl", "bl", "norind", "oculto"):   # oculto: no visible en la carta (agotado o para más adelante)
            if g.get(extra):
                limpio[extra] = 1
        if g.get("d"):
            limpio["d"] = color(g["d"], n)
        ing[k] = limpio
    vistos = set()
    boc = []
    for b in d.get("platos") or []:
        bid = ident(b.get("id"), T("srv.etq.plato"))
        nombre_b = idiomas.limpiar_campo(b.get("n"), T("srv.etq.plato_id", id=bid), 120)
        n = idiomas.tr(nombre_b, idioma)
        if bid in vistos:
            raise idiomas.Msg("srv.val.repetido", n=n)
        vistos.add(bid)
        capas = b.get("i") or []
        if not isinstance(capas, list) or not capas:
            raise idiomas.Msg("srv.val.sin_ingredientes", n=n)
        for x in capas:
            if x not in ing:
                raise idiomas.Msg("srv.val.ingrediente_inexistente", n=n, id=x)
        bo = {"id": bid, "sec": idiomas.limpiar_campo(b.get("sec"), T("srv.etq.seccion", n=n), 40), "pan": "barra", "p": num(b.get("p"), n),
              "i": capas, "n": nombre_b, "d": idiomas.limpiar_campo(b.get("d", ""), T("srv.etq.descripcion", n=n), 300, vacio=True)}
        if b.get("oculto"):
            bo["oculto"] = 1
        alg = alergenos.limpiar(b.get("alergenos"), n)
        if alg is not None:
            bo["alergenos"] = alg
        boc.append(bo)
    pic = []
    for p in d.get("picar") or []:
        pid = ident(p.get("id"), T("srv.etq.racion"))
        nombre_p = idiomas.limpiar_campo(p.get("n"), T("srv.etq.racion_id", id=pid), 120)
        n = idiomas.tr(nombre_p, idioma)
        if pid in vistos:
            raise idiomas.Msg("srv.val.repetido", n=n)
        vistos.add(pid)
        r = {"id": pid, "n": nombre_p, "p": num(p.get("p"), n), "c": color(p.get("c", "#D9A040"), n)}
        if p.get("salsa"):
            r["salsa"] = color(p["salsa"], n)
        if p.get("oculto"):
            r["oculto"] = 1
        alg = alergenos.limpiar(p.get("alergenos"), n)
        if alg is not None:
            r["alergenos"] = alg
        pic.append(r)
    # Mesas del local (n número, z zona opcional). Si no hay ninguna, se acepta cualquier mesa de 1 a MAX_MESA
    mesas, numeros = [], set()
    for m in d.get("mesas") or []:
        n = m.get("n") if isinstance(m, dict) else None
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_MESA:
            raise idiomas.Msg("srv.val.mesas_numero", max=MAX_MESA)
        if n in numeros:
            raise idiomas.Msg("srv.val.mesa_repetida", n=n)
        numeros.add(n)
        me = {"n": n}
        if (m.get("z") or "").strip():
            me["z"] = texto(m["z"], T("srv.etq.mesa_zona", n=n), 30)
        mesas.append(me)
    mesas.sort(key=lambda m: m["n"])
    url = texto(d.get("urlQR") or "", T("srv.etq.url_qr"), 200, vacio=True)
    if url and not re.fullmatch(r"https?://[^\s/?#]+(/[^\s?#]*)?", url):
        raise idiomas.Msg("srv.val.url_qr")
    grupos = [[g, NOMBRES_GRUPO[g]] for g in GRUPOS if any(x["cat"] == g and x["p"] is not None and not x.get("oculto") for x in ing.values())]
    return {"version": d.get("version", 0), "gruposExtra": grupos, "ingredientes": ing, "platos": boc, "picar": pic,
            "mesas": mesas, "urlQR": url.rstrip("/")}


def guardar_datos(nuevos):
    os.makedirs(COPIAS, exist_ok=True)
    marca = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy(DATOS, os.path.join(COPIAS, f"datos-{marca}.json"))
    for viejo in sorted(os.listdir(COPIAS))[:-50]:   # se guardan las 50 últimas copias
        os.remove(os.path.join(COPIAS, viejo))
    tmp = DATOS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(nuevos, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DATOS)
    escribir_datos_js(nuevos)


def escribir_datos_js(d):
    """Copias fijas de los datos (carta abierta como archivo o en un alojamiento estático): siempre iguales a datos.json."""
    texto_js = "window.DATOS = " + json.dumps(d, ensure_ascii=False) + ";\n"
    for carpeta in (RDIR, WEB):
        if os.path.isdir(carpeta):
            with open(os.path.join(carpeta, "datos.js"), "w", encoding="utf-8") as f:
                f.write(texto_js)


# ---------- fotos subidas desde el backoffice ----------
def escribir_fotos(fotos):
    with open(FOTOS_JSON, "w", encoding="utf-8") as f:
        json.dump(fotos, f, indent=1)
    texto_js = "window.FOTOS = " + json.dumps(fotos, indent=1) + ";\n"
    for carpeta in (RDIR, WEB):
        if os.path.isdir(carpeta):
            with open(os.path.join(carpeta, "fotos.js"), "w", encoding="utf-8") as f:
                f.write(texto_js)


def procesar_foto(datos, ing_id, idioma=idiomas.FUENTE):
    """Quita el fondo claro, recorta y guarda fotos/<ing_id>.webp. Devuelve (entrada, avisos); los avisos salen en el idioma pedido."""
    import io
    try:
        import numpy as np
        from PIL import Image, ImageOps
        import recorte
    except ImportError:
        raise idiomas.Msg("srv.foto.dependencias")
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(datos)))
        img.load()
    except Exception:
        raise idiomas.Msg("srv.foto.no_imagen")
    avisos = []
    if max(img.size) > 3000:
        img.thumbnail((3000, 3000))
    rgba = img.convert("RGBA")
    alfa = np.asarray(rgba.getchannel("A"))
    borde = np.concatenate([alfa[0], alfa[-1], alfa[:, 0], alfa[:, -1]])
    if (borde < 20).mean() > 0.5:
        limpia = rgba      # ya viene sin fondo (PNG transparente)
    else:
        rgb = np.asarray(img.convert("RGB")).astype(int)
        bordes = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
        claro = np.median(bordes.min(axis=1))
        if claro < 200:
            avisos.append(idiomas.t("srv.foto.fondo", idioma))
            limpia = rgba
        else:
            limpia = recorte.quitar_fondo(img, aros=False, blanco=claro >= 248, sombra=True)   # quita también la sombra gris de ChatGPT
    bb = limpia.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    if not bb:
        raise idiomas.Msg("srv.foto.vacia")
    limpia = limpia.crop(bb)
    if limpia.width < 300:
        avisos.append(idiomas.t("srv.foto.pequena", idioma))
    r = limpia.height / limpia.width
    if r > 0.45:
        avisos.append(idiomas.t("srv.foto.poco_alargada", idioma))
    alto = max(1, round(limpia.height * 1000 / limpia.width))
    limpia = limpia.resize((1000, alto), Image.LANCZOS)
    nombre = f"{ing_id}.webp"
    for carpeta in (RDIR, WEB):
        d = os.path.join(carpeta, "fotos")
        if os.path.isdir(carpeta):
            os.makedirs(d, exist_ok=True)
            limpia.save(os.path.join(d, nombre), "WEBP", quality=88, method=6)
    # La consulta ?v= obliga a los móviles a descargar la foto nueva aunque tengan la anterior guardada
    return {"src": f"fotos/{nombre}?v={int(time.time())}", "r": round(alto / 1000, 4), "subida": 1}, avisos


# ---------- interruptor «Aceptar pedidos» ----------
def aceptando():
    """Por defecto se aceptan pedidos; el local los cierra desde el backoffice o la cocina."""
    try:
        with open(AJUSTES, encoding="utf-8") as f:
            return json.load(f).get("aceptar_pedidos", True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def guardar_aceptando(valor):
    tmp = AJUSTES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"aceptar_pedidos": bool(valor)}, f)
    os.replace(tmp, AJUSTES)


def mensaje_cerrado(idioma=idiomas.FUENTE):
    return idiomas.t("srv.cerrado", idioma)


# ---------- copias periódicas de pedidos ----------
def copiar_pedidos():
    """Copia pedidos.json y el historial a copias_pedidos/pedidos-AAAAmmdd-HHMMSS.json. Devuelve el nombre o None."""
    with bloqueo:
        pedidos = leer_pedidos()
        meses = {}
        if os.path.isdir(HISTORIAL):
            for n in sorted(os.listdir(HISTORIAL)):
                with open(os.path.join(HISTORIAL, n), encoding="utf-8") as f:
                    meses[n] = f.read()
    if not pedidos and not meses:
        return None
    os.makedirs(COPIAS_PEDIDOS, exist_ok=True)
    nombre = datetime.datetime.now().strftime("pedidos-%Y%m%d-%H%M%S.json")
    tmp = os.path.join(COPIAS_PEDIDOS, nombre + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"pedidos": pedidos, "historial": meses}, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(COPIAS_PEDIDOS, nombre))
    for viejo in sorted(n for n in os.listdir(COPIAS_PEDIDOS) if n.endswith(".json"))[:-COPIAS_PEDIDOS_MAX]:
        os.remove(os.path.join(COPIAS_PEDIDOS, viejo))
    return nombre


def bucle_copias():
    while True:
        time.sleep(COPIA_HORAS * 3600)
        try:
            n = copiar_pedidos()
            log(f"copia de pedidos: {n or 'sin pedidos que copiar'}")
        except Exception as e:
            log(f"ERROR copia de pedidos: {e!r}")


def salud():
    """Estado para el healthcheck: lee datos.json y comprueba que la carpeta del restaurante se puede escribir."""
    problemas = []
    try:
        with bloqueo:
            leer_datos()
    except Exception as e:
        problemas.append(f"datos.json: {e.__class__.__name__}")
    if not os.access(RDIR, os.W_OK):
        problemas.append("carpeta del restaurante sin permiso de escritura")
    return {"ok": not problemas, "restaurante": restaurante.NOMBRE, "aceptar_pedidos": aceptando(),
            "segundos_activo": int(time.time() - INICIO), "problemas": problemas,
            "producto": restaurante.PRODUCTO, "git_sha": os.environ.get("GIT_SHA", ""),
            "version": os.environ.get("GIT_SHA", "")}


# ---------- pedidos ----------
def dia_servicio():
    """Día de servicio: hasta las 5 de la mañana todavía cuenta como el día anterior (cenas que pasan de medianoche)."""
    return (datetime.datetime.now() - datetime.timedelta(hours=CAMBIO_DIA)).date().isoformat()


def leer_pedidos():
    if not os.path.exists(PEDIDOS):
        return []
    with open(PEDIDOS, encoding="utf-8") as f:
        pedidos = json.load(f)
    # Online sin aceptar pasada su hora (o su día de servicio): cancelados solos. Se ve al leer y queda guardado en la próxima escritura
    pedidos_online.caducar(pedidos, datetime.datetime.now(), CAMBIO_DIA)
    return pedidos


def guardar_pedidos(pedidos):
    """Los pedidos terminados (entregados, rechazados o cancelados) de días anteriores pasan a historial/pedidos-AAAA-MM.jsonl (una línea por pedido)."""
    hoy = dia_servicio()
    pedidos_online.caducar(pedidos, datetime.datetime.now(), CAMBIO_DIA)
    quedan, viejos = [], []
    for p in pedidos:
        (viejos if p["estado"] in pedidos_online.FINALES and p["fecha"] < hoy else quedan).append(p)
    if viejos:
        os.makedirs(HISTORIAL, exist_ok=True)
        for p in viejos:
            with open(os.path.join(HISTORIAL, f"pedidos-{p['fecha'][:7]}.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
    tmp = PEDIDOS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(quedan, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PEDIDOS)


def leer_reservas(a=None):
    """Reservas guardadas, con los cambios solos aplicados (solicitadas sin respuesta y no presentadas). Llamar con `bloqueo`."""
    lista = reservas.leer()
    if reservas.caducar(lista, datetime.datetime.now(), a or reservas.leer_ajustes()):
        reservas.guardar(lista)
    return lista


def lista_ids(v, campo):
    """campo: «cambios» o «extras» (la clave del mensaje de error)."""
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > 40 or not all(isinstance(x, str) for x in v):
        raise idiomas.Msg(f"srv.pedido.{campo}_no_valido")
    return list(dict.fromkeys(v))   # sin repetidos, en el mismo orden


def preparar_pedido(cuerpo, datos, idioma=idiomas.FUENTE, online=False):
    """Comprueba el pedido contra la carta actual y calcula los precios aquí (nunca se fía del navegador).
    Las líneas iguales se juntan («2× Plato de ejemplo»). Lanza idiomas.Msg (un ValueError) con un mensaje para el cliente.
    online=True: pedido a domicilio o para recoger, sin mesa (sus datos de entrega los valida pedidos_online)."""
    if not isinstance(cuerpo, dict):
        raise idiomas.Msg("srv.pedido.no_valido")
    mesas = {m["n"]: m for m in datos.get("mesas") or []}
    mesa = None
    if not online:
        mesa = cuerpo.get("mesa")
        if isinstance(mesa, str) and mesa.strip().isdigit():
            mesa = int(mesa)
        if not isinstance(mesa, int) or isinstance(mesa, bool) or not 1 <= mesa <= MAX_MESA:
            raise idiomas.Msg("srv.pedido.indica_mesa")
        if mesas and mesa not in mesas:
            raise idiomas.Msg("srv.pedido.mesa_no_existe", mesa=mesa)
    lineas = cuerpo.get("lineas")
    if not isinstance(lineas, list) or not lineas:
        raise idiomas.Msg("srv.pedido.vacio")
    if len(lineas) > 40:
        raise idiomas.Msg("srv.pedido.largo")
    ing = datos["ingredientes"]
    productos = {b["id"]: (b, False) for b in datos["platos"]}
    productos.update({p["id"]: (p, True) for p in datos["picar"]})
    nombre = lambda i: ing[i]["n"]   # texto o {es, en, ca, zh, fr, de, it, pt}: la cocina lo muestra en su idioma
    juntas = {}
    for l in lineas:
        if not isinstance(l, dict):
            raise idiomas.Msg("srv.pedido.no_valido")
        x, picar = productos.get(l.get("pid"), (None, False))
        if not x or x.get("oculto"):
            raise idiomas.Msg("srv.pedido.producto_fuera")
        receta = [i for i in x.get("i", []) if i in ing]
        rm = [i for i in lista_ids(l.get("rm"), "cambios") if i in receta]
        ex = lista_ids(l.get("ex"), "extras")
        for e in ex:
            if e not in ing or ing[e].get("p") is None or e in receta:
                raise idiomas.Msg("srv.pedido.extra_no_valido", plato=x["n"])
            if ing[e].get("oculto"):
                raise idiomas.Msg("srv.pedido.agotado", ingrediente=ing[e]["n"], plato=x["n"])
        agotado = [i for i in receta if ing[i].get("oculto") and i not in rm]
        rm = [i for i in rm if not ing[i].get("oculto")]
        clave = (x["id"], tuple(sorted(rm)), tuple(sorted(ex)))
        if clave in juntas:
            juntas[clave]["cant"] += 1
            continue
        juntas[clave] = {"pid": x["id"], "n": x["n"], "cant": 1, "picar": picar, "alergenos": x.get("alergenos"),
                         "sin": [nombre(i) for i in rm], "agotado": [nombre(i) for i in agotado],
                         "extra": [nombre(i) for i in ex],
                         # Orden de montaje para la cocina, de abajo arriba: la receta tal como está ordenada
                         # en el backoffice (con lo quitado y lo agotado marcado) y los extras encima
                         "montaje": [{"n": ing[i]["n"], "e": "sin" if i in rm else "agotado" if i in agotado else ""} for i in receta]
                                    + [{"n": ing[e]["n"], "e": "extra"} for e in ex],
                         "precio": round(x["p"] + sum(ing[e]["p"] for e in ex), 2)}
    salida = list(juntas.values())
    nota = cuerpo.get("nota") or ""
    if not isinstance(nota, str) or len(nota.strip()) > 200:
        raise idiomas.Msg("srv.pedido.nota_larga")
    nuevo = {"tipo": "mesa", "mesa": mesa, "zona": (mesas.get(mesa) or {}).get("z", "") if mesa else "", "lineas": salida, "nota": nota.strip(),
             "total": round(sum(l["precio"] * l["cant"] for l in salida), 2)}
    nuevo["idioma"] = idioma   # el que tenía el cliente al pedir: en él salen sus correos y su tarjeta
    nuevo["via"] = "online" if online else "qr" if cuerpo.get("via") == "qr" else "manual"   # lo declara la carta: con ?mesa=N del QR o eligiendo la mesa a mano
    tarjeta = cuerpo.get("tarjeta")
    if sellos.id_valido(tarjeta) and sellos.estado(tarjeta):   # una tarjeta que no existe se ignora: el pedido sigue adelante
        nuevo["tarjeta"] = tarjeta
    return nuevo


_resueltos = {}   # nombre de host -> (caduca, {ips})


def proxy_confiable(ip):
    """¿Es `ip` uno de los PROXY_CONFIABLE (IP, red CIDR o nombre de host, resuelto con 30 s de caché)?"""
    try:
        direccion = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for e in PROXY_CONFIABLE:
        try:
            if direccion in ipaddress.ip_network(e, strict=False):
                return True
            continue
        except ValueError:
            pass
        ahora = time.time()
        if e not in _resueltos or _resueltos[e][0] < ahora:
            try:
                ips = {ipaddress.ip_address(i[4][0]) for i in socket.getaddrinfo(e, None)}
            except (OSError, ValueError):
                ips = set()
            _resueltos[e] = (ahora + 30, ips)
        if direccion in _resueltos[e][1]:
            return True
    return False


def para_cliente(p):
    return {k: p[k] for k in ("id", "numero", "mesa", "estado", "lineas", "total", "nota", "creado")}


# ---------- servidor ----------
class Manejador(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=WEB, **k)

    def version_string(self):
        return "Gastro"   # sin la versión de Python ni de http.server

    def log_message(self, fmt, *args):
        # A stdout (docker logs). /salud, que consulta el healthcheck cada pocos segundos, no se apunta
        if (self.path or "").split("?")[0] != "/salud":
            log(f"{self.ip() if hasattr(self, 'headers') else '-'}  {fmt % args}")

    def end_headers(self):
        ruta = urlparse(self.path).path
        if ruta in ("/", "/index.html", "/datos.js", "/fotos.js", "/sw.js", "/idiomas.js", "/tema.css") or ruta.startswith(("/admin", "/cocina", "/pedir", "/seguir", "/reserva", "/baja", "/confirmar", "/api/", "/i18n/")):
            self.send_header("Cache-Control", "no-cache")
        for k, v in seguridad.CABECERAS_FIJAS:
            self.send_header(k, v)
        if self.es_https():
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if getattr(self, "_html", False):
            self.send_header("Content-Security-Policy", seguridad.csp(getattr(self, "_html_texto", "")))
        super().end_headers()

    def send_header(self, k, v):
        if k.lower() == "content-type" and str(v).startswith("text/html"):
            self._html = True
        super().send_header(k, v)

    def send_response(self, *a, **kw):
        self._html, self._html_texto = False, ""
        super().send_response(*a, **kw)

    # utilidades
    def idioma(self):
        return idiomas.de_peticion(self.headers)

    def error(self, codigo, clave, **p):
        """Respuesta de error con el mensaje en el idioma de la petición."""
        return self.responder(codigo, {"error": idiomas.t(clave, self.idioma(), **p)})

    def error_de(self, e, clave):
        """400 con el mensaje de un error de validación (idiomas.Msg, en el idioma de la petición); cualquier otro fallo, el genérico."""
        if isinstance(e, ValueError) and not isinstance(e, json.JSONDecodeError) and str(e):
            return self.responder(400, {"error": idiomas.mensaje(e, self.idioma())})
        return self.error(400, clave)

    def responder(self, codigo, cuerpo, tipo="application/json; charset=utf-8", cabeceras=()):
        datos = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo, ensure_ascii=False).encode()
        if tipo.startswith("text/html"):   # idioma de la primera visita (Accept-Language); lo lee idiomas.js
            inicial = idiomas.desde_cabecera(self.headers.get("Accept-Language"))
            datos = datos.replace(MARCADOR_IDIOMA, f'<meta name="gastro-idioma" content="{inicial}">'.encode(), 1)
        self.send_response(codigo)
        if tipo.startswith("text/html"):
            self._html_texto = datos.decode("utf-8", "replace")
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        for k, v in cabeceras:
            self.send_header(k, v)
        self.end_headers()
        if not self._solo_cabeceras:
            self.wfile.write(datos)

    def exportar(self, q):
        """Sin «formato»: resumen en JSON (y el rango por defecto) para la pestaña; con csv o xlsx: la descarga."""
        v = lambda k: (q.get(k) or [""])[0]
        idioma = v("idioma") if v("idioma") in idiomas.IDIOMAS else self.idioma()
        formato = v("formato")
        try:
            if formato and formato not in exportar.FORMATOS:
                raise idiomas.Msg("srv.exportar.formato")
            desde, hasta = exportar.rango(v("desde"), v("hasta"), dia_servicio())
            with bloqueo:
                pedidos = exportar.pedidos_en(desde, hasta)
        except ValueError as e:
            return self.responder(400, {"error": idiomas.mensaje(e, idioma)})
        if not formato:
            return self.responder(200, {"desde": desde.isoformat(), "hasta": hasta.isoformat(), **exportar.resumen(pedidos)})
        log(f"Exportación de pedidos {desde} a {hasta} ({formato}): {len(pedidos)} pedidos")
        cuerpo = (exportar.a_csv if formato == "csv" else exportar.a_xlsx)(desde, hasta, pedidos, idioma)
        tipo = "text/csv; charset=utf-8" if formato == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return self.responder(200, cuerpo, tipo, [("Content-Disposition", f'attachment; filename="{exportar.nombre_fichero(desde, hasta, formato)}"')])

    def cuerpo_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2_000_000:
            raise idiomas.Msg("srv.demasiado_grande")
        return json.loads(self.rfile.read(n) or b"{}")

    def autenticado(self):
        m = re.search(re.escape(COOKIE) + r"=([A-Za-z0-9_\-]+)", self.headers.get("Cookie") or "")
        if not m:
            return False
        caduca = sesiones.get(huella(m.group(1)))
        return bool(caduca and caduca > time.time())

    def desde_proxy(self):
        """True si quien conecta es uno de los PROXY_CONFIABLE: solo entonces valen sus cabeceras X-Forwarded-*."""
        return proxy_confiable(self.client_address[0])

    def ip(self):
        # Solo si la petición llega de un proxy de confianza se lee la IP real: la última de X-Forwarded-For (la añade Caddy) o,
        # únicamente con CONFIAR_CF=1 (delante hay Cloudflare y el proxy solo es accesible por él; túnel: Caddy reescribe
        # X-Forwarded-For con la IP de cloudflared, igual para todos), CF-Connecting-IP. Sin CONFIAR_CF esa cabecera la puede
        # inventar cualquiera. Si no es proxy de confianza, la del socket: una cabecera del cliente no se cree.
        if self.desde_proxy():
            cf = (self.headers.get("CF-Connecting-IP") or "").strip() if os.environ.get("CONFIAR_CF") == "1" else ""
            try:
                return str(ipaddress.ip_address(cf))
            except ValueError:
                pass
            xff = (self.headers.get("X-Forwarded-For") or "").split(",")[-1].strip()
            if xff:
                return xff
        return self.client_address[0]

    def es_https(self):
        """La conexión del cliente es HTTPS: lo dice URL_PUBLICA o, desde un proxy de confianza, X-Forwarded-Proto."""
        return os.environ.get("URL_PUBLICA", "").strip().lower().startswith("https://") or \
            (self.desde_proxy() and (getattr(self, "headers", None) or {}).get("X-Forwarded-Proto", "").split(",")[0].strip().lower() == "https")

    # rutas
    _solo_cabeceras = False

    def do_HEAD(self):
        self._solo_cabeceras = True
        try:
            self.do_GET()
        finally:
            self._solo_cabeceras = False

    def do_GET(self):
        ruta = urlparse(self.path).path
        if ruta.startswith(RUTAS_TARJETA) and tarjeta_web.get(self, ruta):
            return
        if ruta.startswith(RUTAS_PROMOCIONES) and promociones_web.get(self, ruta):
            return
        if ruta == "/tema.css":
            return self.responder(200, tema.css().encode("utf-8"), "text/css; charset=utf-8")
        if ruta == "/datos.js":
            with bloqueo:
                d = leer_datos()
            # GASTRO_SERVIDOR: la carta sabe que hay servidor y que los pedidos van de verdad a la cocina
            # (las copias fijas de datos.js no lo llevan: la carta de demostración solo simula el envío)
            return self.responder(200, ("window.DATOS = " + json.dumps(d, ensure_ascii=False) + ";\nwindow.GASTRO_SERVIDOR = true;\n").encode(),
                                  "application/javascript; charset=utf-8")
        if ruta in ("/admin", "/admin/"):
            return self.responder(200, pagina(ADMIN), "text/html; charset=utf-8")
        if ruta == "/api/datos":
            if not self.autenticado():
                return self.error(401, "srv.sesion.iniciar")
            with bloqueo:
                return self.responder(200, leer_datos())
        if ruta == "/salud":
            r = salud()
            return self.responder(200 if r["ok"] else 503, r)
        if ruta == "/api/permiso":
            return self.responder(200, {"version": clientes.TEXTO_VERSION, "texto": clientes.texto_permiso(self.idioma())})
        if ruta == "/baja":
            token = (parse_qs(urlparse(self.path).query).get("t") or [""])[0]
            return self.responder(200, clientes.pagina_baja(token, self.headers, (parse_qs(urlparse(self.path).query).get("lang") or [""])[0]), "text/html; charset=utf-8")
        if ruta == "/confirmar":
            q = parse_qs(urlparse(self.path).query)
            return self.responder(200, clientes.pagina_confirmar((q.get("t") or [""])[0], self.headers, (q.get("lang") or [""])[0]), "text/html; charset=utf-8")
        if ruta == "/api/clientes":
            if not self.autenticado():
                return self.error(401, "srv.sesion.iniciar")
            return self.responder(200, {"clientes": clientes.listar()})
        if ruta == "/api/kpis":
            if not self.autenticado():
                return self.error(401, "srv.sesion.iniciar")
            try:
                with bloqueo:
                    return self.responder(200, kpis.calcular((parse_qs(urlparse(self.path).query).get("mes") or [None])[0], self.idioma()))
            except ValueError as e:
                return self.responder(400, {"error": idiomas.mensaje(e, self.idioma())})
        if ruta == "/api/exportar":
            if not self.autenticado():
                return self.error(401, "srv.sesion.iniciar")
            return self.exportar(parse_qs(urlparse(self.path).query))
        if ruta == "/api/estado":
            return self.responder(200, {"aceptar_pedidos": aceptando(), "mensaje": "" if aceptando() else mensaje_cerrado(self.idioma())})
        if ruta == "/api/sesion":
            return self.responder(200, {"ok": self.autenticado()})
        if ruta == "/api/red":
            if not self.autenticado():
                return self.error(401, "srv.sesion.iniciar")
            return self.responder(200, {**info_red(), "puerto": self.server.server_address[1]})
        if ruta in ("/cocina", "/cocina/"):
            return self.responder(200, pagina(COCINA), "text/html; charset=utf-8")
        if ruta in ("/seguir", "/seguir/"):
            return self.responder(200, pagina(SEGUIR), "text/html; charset=utf-8")
        if ruta in ("/reservar", "/reservar/"):
            return self.responder(200, pagina(RESERVAR), "text/html; charset=utf-8")
        if ruta in ("/reserva", "/reserva/"):
            return self.responder(200, pagina(RESERVA), "text/html; charset=utf-8")
        if ruta == "/api/reservar":   # ajustes públicos y, con ?fecha=, los tramos libres de ese día
            a, ahora = reservas.leer_ajustes(), datetime.datetime.now()
            fecha = (parse_qs(urlparse(self.path).query).get("fecha") or [""])[0]
            r = reservas.publico(a, ahora)
            if fecha and a["activo"]:
                try:
                    dia = datetime.date.fromisoformat(fecha)
                except ValueError:
                    return self.error(400, "srv.reservas.fecha")
                with bloqueo:
                    r["tramos"] = reservas.libres_del_dia(a, leer_reservas(a), dia, ahora)
            return self.responder(200, r)
        if ruta == "/api/reserva":   # la reserva del cliente, por su token aleatorio (no por id)
            t = (parse_qs(urlparse(self.path).query).get("t") or [""])[0]
            with bloqueo:
                r = next((r for r in leer_reservas() if len(t) >= 20 and hmac.compare_digest(r.get("token", ""), t)), None) if t else None
            if not r:
                return self.error(404, "srv.reservas.no_encontrada")
            return self.responder(200, reservas.para_cliente(r, datetime.datetime.now()))
        if ruta == "/api/reservas":   # sala: el día (?fecha=, por defecto hoy)
            if not self.autenticado():
                return self.error(401, "srv.sesion.iniciar")
            fecha = (parse_qs(urlparse(self.path).query).get("fecha") or [""])[0]
            try:
                dia = datetime.date.fromisoformat(fecha) if fecha else datetime.date.today()
            except ValueError:
                return self.error(400, "srv.reservas.fecha")
            a = reservas.leer_ajustes()
            with bloqueo:
                lista = leer_reservas(a)
            return self.responder(200, reservas.vista_dia(a, lista, dia))
        if ruta == "/api/reservas/ajustes":
            if not self.autenticado():
                return self.error(401, "srv.sesion.iniciar")
            return self.responder(200, reservas.leer_ajustes())
        if ruta == "/api/online":   # ajustes públicos para la página de pedido online
            return self.responder(200, {**pedidos_online.publico(pedidos_online.leer_ajustes(), datetime.datetime.now()),
                                        "aceptar_pedidos": aceptando()})
        if ruta == "/api/online/ajustes":
            if not self.autenticado():
                return self.error(401, "srv.sesion.iniciar")
            return self.responder(200, pedidos_online.leer_ajustes())
        if ruta == "/api/seguir":   # seguimiento por token aleatorio (no por id ni número: nada que adivinar)
            t = (parse_qs(urlparse(self.path).query).get("t") or [""])[0]
            with bloqueo:
                p = next((p for p in leer_pedidos() if t and len(t) >= 20 and hmac.compare_digest(p.get("seguimiento", ""), t)), None) if t else None
            if not p:
                return self.error(404, "srv.pedido.no_encontrado")
            return self.responder(200, pedidos_online.para_seguimiento(p))
        if ruta == "/admin/reparto":
            if not self.autenticado():
                return self.responder(401, b"401", "text/plain; charset=utf-8")
            pid = (parse_qs(urlparse(self.path).query).get("id") or [""])[0]
            with bloqueo:
                p = next((p for p in leer_pedidos() if p["id"] == pid and pedidos_online.es_online(p)), None)
            if not p:
                return self.error(404, "srv.pedido.no_encontrado")
            return self.responder(200, pedidos_online.hoja_reparto(p, self.idioma()).encode("utf-8"), "text/html; charset=utf-8")
        if ruta == "/api/pedido":
            pid = (parse_qs(urlparse(self.path).query).get("id") or [""])[0]
            with bloqueo:
                p = next((p for p in leer_pedidos() if p["id"] == pid), None) if pid else None
            if not p:
                return self.error(404, "srv.pedido.no_encontrado")
            return self.responder(200, para_cliente(p))
        if ruta == "/api/pedidos":
            if not self.autenticado():
                return self.error(401, "srv.sesion.iniciar")
            ahora = time.time()
            vista = (parse_qs(urlparse(self.path).query).get("vista") or [""])[0]
            with bloqueo:
                todos = leer_pedidos()
            if vista == "sala":   # backoffice: todos los pedidos online del día (también los recibidos, rechazados y cancelados)
                return self.responder(200, {"ahora": ahora, "pedidos": [pedidos_online.para_sala(p) for p in todos if pedidos_online.es_online(p)]})
            # Cocina: pendientes y, para poder deshacer, los entregados de los últimos 30 minutos. Los online, solo desde «aceptado»
            lista = [pedidos_online.sin_secretos(p) for p in todos
                     if (p["estado"] != "entregado" or ahora - p["t"]["entregado"] < 1800)
                     and not (pedidos_online.es_online(p) and p["estado"] in pedidos_online.OCULTOS_COCINA)]
            return self.responder(200, {"ahora": ahora, "pedidos": lista, "aceptar_pedidos": aceptando()})
        if ruta in ("/", "/index.html", "/pedir"):   # la portada estática pasa por responder() para llevar su CSP; /pedir es la misma carta en modo pedido online
            try:
                with open(os.path.join(WEB, "index.html"), "rb") as f:
                    return self.responder(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                pass
        return super().do_HEAD() if self._solo_cabeceras else super().do_GET()

    def do_POST(self):
        ruta = urlparse(self.path).path
        if ruta.startswith(RUTAS_TARJETA) and tarjeta_web.post(self, ruta):
            return
        if ruta.startswith(RUTAS_PROMOCIONES) and promociones_web.post(self, ruta):
            return
        if ruta == "/api/login":
            ip = self.ip()
            ahora = time.time()
            recientes = [t for t in intentos.get(ip, []) if ahora - t < 600]
            if len(recientes) >= 8:
                return self.error(429, "srv.login.intentos")
            try:
                cuerpo = self.cuerpo_json()
                clave, recordar = cuerpo.get("clave", ""), bool(cuerpo.get("recordar"))
            except Exception:
                clave, recordar = "", False
            if not isinstance(clave, str) or not comprobar_clave(clave):
                intentos[ip] = recientes + [ahora]
                time.sleep(0.8)
                return self.error(401, "srv.login.incorrecta")
            intentos.pop(ip, None)
            token = secrets.token_urlsafe(32)
            dura = RECORDAR_DIAS * 86400 if recordar else SESION_HORAS * 3600
            with bloqueo:
                sesiones[huella(token)] = ahora + dura
                guardar_sesiones()
            cookie = f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={dura}" + ("; Secure" if self.es_https() else "")
            return self.responder(200, {"ok": True}, cabeceras=[("Set-Cookie", cookie)])
        if ruta == "/api/foto":
            if not self.autenticado():
                return self.error(401, "srv.sesion.caducada")
            ing_id = (parse_qs(urlparse(self.path).query).get("id") or [""])[0]
            with bloqueo:
                existe = ing_id in leer_datos().get("ingredientes", {})
            if not re.fullmatch(r"[a-z0-9_]{1,40}", ing_id) or not existe:
                return self.error(400, "srv.foto.guardar_primero")
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 15_000_000:
                return self.error(400, "srv.foto.tamano")
            datos = self.rfile.read(n)
            try:
                entrada, avisos = procesar_foto(datos, ing_id, self.idioma())
            except ValueError as e:
                return self.responder(400, {"error": idiomas.mensaje(e, self.idioma())})
            with bloqueo:
                fotos = json.load(open(FOTOS_JSON, encoding="utf-8")) if os.path.exists(FOTOS_JSON) else {}
                fotos[ing_id] = entrada
                escribir_fotos(fotos)
            return self.responder(200, {"ok": True, "foto": entrada, "avisos": avisos})
        if ruta == "/api/aceptar":
            if not self.autenticado():
                return self.error(401, "srv.sesion.caducada")
            try:
                valor = self.cuerpo_json().get("aceptar_pedidos")
            except Exception:
                valor = None
            if not isinstance(valor, bool):
                return self.error(400, "srv.valor_no_valido")
            with bloqueo:
                guardar_aceptando(valor)
            log(f"Pedidos {'ABIERTOS' if valor else 'CERRADOS'} desde el backoffice o la cocina")
            return self.responder(200, {"aceptar_pedidos": valor})
        if ruta == "/api/confirmar":
            try:
                token = self.cuerpo_json().get("token")
            except Exception:
                token = None
            if not clientes.confirmar(token):
                return self.error(404, "srv.confirmar.enlace_no_valido")
            log("Permiso de publicidad confirmado por el titular")
            return self.responder(200, {"ok": True})
        if ruta == "/api/baja":
            try:
                token = self.cuerpo_json().get("token")
            except Exception:
                token = None
            if not clientes.registrar_baja(token, idioma=self.idioma()):
                return self.error(404, "srv.baja.enlace_no_valido")
            log("Baja de publicidad registrada")
            return self.responder(200, {"ok": True})
        if ruta in ("/api/pedido", "/api/pedido/online"):
            online = ruta == "/api/pedido/online"
            if not aceptando():
                return self.responder(503, {"error": mensaje_cerrado(self.idioma()), "cerrado": True})
            ip, ahora = self.ip(), time.time()   # el mismo freno por IP para los pedidos de mesa y los online
            recientes = [t for t in envios.get(ip, []) if ahora - t < 600]
            if len(recientes) >= MAX_PEDIDOS_IP:
                return self.error(429, "srv.pedido.limite")
            try:
                cuerpo = self.cuerpo_json()
                email_permiso = clientes.validar_permiso(cuerpo["permiso"]) if cuerpo.get("permiso") else None
                with bloqueo:
                    nuevo = preparar_pedido(cuerpo, leer_datos(), self.idioma(), online=online)
                    inicial = "nuevo"
                    if online:   # datos de entrega, zona, horario, mínimo y preferencia de pago (nota logística, no un cobro)
                        nuevo.update(pedidos_online.validar_entrega(cuerpo, pedidos_online.leer_ajustes(), nuevo["total"], datetime.datetime.fromtimestamp(ahora)))
                        inicial = "recibido"
                    pedidos = leer_pedidos()
                    hoy = dia_servicio()
                    nuevo.update({"id": secrets.token_urlsafe(9), "fecha": hoy, "creado": ahora, "estado": inicial,
                                  "numero": 1 + max((p["numero"] for p in pedidos if p["fecha"] == hoy), default=0),
                                  "t": {inicial: ahora}, "token": secrets.token_urlsafe(16)})
                    doble = clientes.confirmacion_doble()
                    token_confirmar = None
                    if email_permiso and not doble:   # alta directa: marcar la casilla es el permiso (LSSI art. 21)
                        nuevo["cliente"] = clientes.alta_directa(email_permiso, idioma=nuevo["idioma"])
                    elif email_permiso:   # doble confirmación: solo una solicitud pendiente, el alta la da el clic del titular en el correo
                        nuevo["cliente"], token_confirmar = clientes.solicitar_alta(email_permiso, idioma=nuevo["idioma"])
                    if email_permiso:
                        if nuevo.get("tarjeta"):   # con permiso, la tarjeta puede recibir avisos de promociones
                            clientes.vincular_tarjeta(nuevo["cliente"], nuevo["tarjeta"])
                    pedidos.append(nuevo)
                    guardar_pedidos(pedidos)
            except (ValueError, TypeError, AttributeError, KeyError, json.JSONDecodeError) as e:
                return self.error_de(e, "srv.pedido.no_valido")
            envios[ip] = recientes + [ahora]
            respuesta = para_cliente(nuevo)
            respuesta["token"] = nuevo["token"]   # solo aquí: quien hizo el pedido lo guarda para poder vincularlo a su tarjeta
            if online:   # el enlace de seguimiento solo se da aquí, a quien hizo el pedido
                respuesta["seguimiento"] = nuevo["seguimiento"]
            if email_permiso and not doble:
                respuesta["permiso"] = "alta"
            elif email_permiso:   # fuera del bloqueo: el envío puede tardar. Sin canal de correo queda «pendiente de confirmar»
                con_canal = bool(correo.modo() and clientes.url_publica())
                if token_confirmar and not promociones.enviar_confirmacion(email_permiso, token_confirmar, nuevo["idioma"]):
                    con_canal = False
                respuesta["permiso"] = "confirmar" if con_canal else "sin_canal"
            log(f"Pedido {nuevo['numero']} · " + (f"online ({nuevo['tipo']})" if online else f"mesa {nuevo['mesa']}") + f" · {nuevo['total']:.2f} €" + ((" · con permiso de publicidad (alta directa)" if not doble else " · con permiso de publicidad pendiente de confirmar") if nuevo.get("cliente") else ""))
            return self.responder(200, respuesta)
        if ruta == "/api/reservar":
            ip, ahora = self.ip(), time.time()   # freno por IP propio: reservar no gasta el cupo de pedidos ni al revés
            recientes = [t for t in envios_reservas.get(ip, []) if ahora - t < 600]
            if len(recientes) >= MAX_RESERVAS_IP:
                return self.error(429, "srv.reservas.limite")
            try:
                cuerpo = self.cuerpo_json()
                email_permiso = clientes.validar_permiso(cuerpo["permiso"]) if cuerpo.get("permiso") else None
                idioma = idiomas.valido(cuerpo.get("idioma")) or self.idioma()
                with bloqueo:
                    a = reservas.leer_ajustes()
                    lista = leer_reservas(a)
                    nueva = reservas.validar(cuerpo, a, lista, datetime.datetime.fromtimestamp(ahora))
                    nueva["idioma"] = idioma
                    doble = clientes.confirmacion_doble()
                    token_confirmar = None
                    if email_permiso and not doble:   # la misma casilla que el pedido: alta directa o doble confirmación
                        nueva["cliente"] = clientes.alta_directa(email_permiso, canal=clientes.CANAL_RESERVA, idioma=idioma)
                    elif email_permiso:
                        nueva["cliente"], token_confirmar = clientes.solicitar_alta(email_permiso, canal=clientes.CANAL_RESERVA, idioma=idioma)
                    lista.append(nueva)
                    reservas.guardar(lista)
            except (ValueError, TypeError, AttributeError, KeyError, json.JSONDecodeError) as e:
                return self.error_de(e, "srv.reservas.no_valida")
            envios_reservas[ip] = recientes + [ahora]
            respuesta = {"estado": nueva["estado"], "token": nueva["token"]}   # el enlace de la reserva solo se da aquí
            if email_permiso and not doble:
                respuesta["permiso"] = "alta"
            elif email_permiso:
                con_canal = bool(correo.modo() and clientes.url_publica())
                if token_confirmar and not promociones.enviar_confirmacion(email_permiso, token_confirmar, idioma):
                    con_canal = False
                respuesta["permiso"] = "confirmar" if con_canal else "sin_canal"
            log(f"Reserva {nueva['fecha']} {nueva['hora']} · {nueva['comensales']} pers. · {nueva['estado']}")
            return self.responder(200, respuesta)
        if ruta == "/api/reserva/cancelar":   # el cliente, con su enlace
            try:
                t = self.cuerpo_json().get("t")
                with bloqueo:
                    lista = leer_reservas()
                    r = next((r for r in lista if isinstance(t, str) and len(t) >= 20 and hmac.compare_digest(r.get("token", ""), t)), None)
                    if not r:
                        return self.error(404, "srv.reservas.no_encontrada")
                    ahora = datetime.datetime.now()
                    reservas.cancelar_cliente(r, ahora)
                    reservas.guardar(lista)
            except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as e:
                return self.error_de(e, "srv.reservas.no_valida")
            log(f"Reserva {r['fecha']} {r['hora']} cancelada por el cliente")
            return self.responder(200, reservas.para_cliente(r, ahora))
        if ruta == "/api/reserva/estado":   # sala
            if not self.autenticado():
                return self.error(401, "srv.sesion.caducada")
            try:
                cuerpo = self.cuerpo_json()
                with bloqueo:
                    a = reservas.leer_ajustes()
                    lista = leer_reservas(a)
                    r = next((r for r in lista if r["id"] == cuerpo.get("id")), None)
                    if not r:
                        return self.error(404, "srv.reservas.no_encontrada")
                    ahora = datetime.datetime.now()
                    reservas.cambiar_estado(r, cuerpo.get("estado"), cuerpo, lista, a, ahora)
                    reservas.guardar(lista)
            except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as e:
                return self.error_de(e, "srv.reservas.no_valida")
            log(f"Reserva {r['fecha']} {r['hora']} -> {r['estado']}")
            return self.responder(200, {"ok": True, "reserva": reservas.para_sala(r, a, ahora)})
        if ruta == "/api/reservas/ajustes":
            if not self.autenticado():
                return self.error(401, "srv.sesion.caducada")
            try:
                with bloqueo:
                    a = reservas.guardar_ajustes(self.cuerpo_json())
            except (ValueError, AttributeError, json.JSONDecodeError) as e:
                return self.error_de(e, "srv.datos_no_validos")
            log("Ajustes de reservas cambiados desde el backoffice")
            return self.responder(200, {"ok": True, "ajustes": a})
        if ruta == "/api/online/ajustes":
            if not self.autenticado():
                return self.error(401, "srv.sesion.caducada")
            try:
                with bloqueo:
                    a = pedidos_online.guardar_ajustes(self.cuerpo_json())
            except (ValueError, AttributeError, json.JSONDecodeError) as e:
                return self.error_de(e, "srv.datos_no_validos")
            log("Ajustes de pedidos online cambiados desde el backoffice")
            return self.responder(200, {"ok": True, "ajustes": a})
        if ruta == "/api/resena":
            if not self.autenticado():
                return self.error(401, "srv.sesion.iniciar")
            try:
                with bloqueo:
                    enlace = restaurante.guardar_resena(self.cuerpo_json().get("enlace"))
            except (ValueError, AttributeError, json.JSONDecodeError) as e:
                return self.error_de(e, "srv.datos_no_validos")
            return self.responder(200, {"ok": True, "enlace": enlace})
        if ruta == "/api/resena/clic":
            # Solo cuenta el clic de un pedido que existe y está servido, y como mucho 20 por IP cada 10 minutos
            ip, ahora = self.ip(), time.time()
            recientes = [t for t in clics.get(ip, []) if ahora - t < 600]
            if len(recientes) >= 20:
                return self.responder(429, {"ok": False})
            clics[ip] = recientes + [ahora]
            try:
                pid = self.cuerpo_json().get("id")
                with bloqueo:
                    servido = any(p["id"] == pid and p["estado"] == "entregado" for p in leer_pedidos())
                ok = servido and kpis.registrar_clic_resena(pid)
            except Exception:   # noqa: BLE001
                ok = False
            return self.responder(200 if ok else 400, {"ok": ok})
        if ruta == "/api/pedido/tarjeta":
            try:
                cuerpo = self.cuerpo_json()
                pid, tarjeta, token = cuerpo.get("id"), cuerpo.get("tarjeta"), cuerpo.get("token")
            except Exception:   # noqa: BLE001
                pid = tarjeta = token = None
            if not sellos.id_valido(tarjeta) or not sellos.estado(tarjeta):
                return self.error(404, "srv.tarjeta.no_encontrada")
            with bloqueo:
                pedidos = leer_pedidos()
                p = next((p for p in pedidos if p["id"] == pid), None)
                if not p:
                    return self.error(404, "srv.pedido.no_encontrado")
                # El token del pedido solo lo tiene quien lo hizo: saber el id (que se ve en la pantalla de estado) no basta
                if not isinstance(token, str) or not p.get("token") or not hmac.compare_digest(p["token"], token):
                    return self.error(403, "srv.pedido.no_encontrado")
                if p.get("tarjeta") and p["tarjeta"] != tarjeta:
                    return self.error(409, "srv.pedido.otra_tarjeta")
                nueva = not p.get("tarjeta")
                p["tarjeta"] = tarjeta
                if p.get("cliente"):
                    clientes.vincular_tarjeta(p["cliente"], tarjeta)
                if nueva:
                    guardar_pedidos(pedidos)
            sello = None
            if nueva and p["estado"] == "entregado":   # ya estaba servido: el sello se da en el acto
                sello, _ = sellos.sellar(tarjeta, p["total"], "servido", pedido_id=p["id"])
                if sello == "sellado":
                    wallet.notificar_en_segundo_plano(tarjeta)
            return self.responder(200, {"ok": True, "sello": sello})
        if ruta == "/api/pedido/estado":
            if not self.autenticado():
                return self.error(401, "srv.sesion.caducada")
            try:
                cuerpo = self.cuerpo_json()
                pid, estado = cuerpo.get("id"), cuerpo.get("estado")
            except Exception:
                cuerpo, pid, estado = {}, None, None
            if estado not in ESTADOS and estado not in pedidos_online.ESTADOS:
                return self.error(400, "srv.estado_no_valido")
            with bloqueo:
                pedidos = leer_pedidos()
                p = next((p for p in pedidos if p["id"] == pid), None)
                if not p:
                    return self.error(404, "srv.pedido.no_encontrado")
                if pedidos_online.es_online(p):   # flujo propio: recibido → aceptado/rechazado → … → entregado
                    try:
                        pedidos_online.cambiar_estado(p, estado, cuerpo if isinstance(cuerpo, dict) else {}, datetime.datetime.now())
                    except ValueError as e:
                        return self.responder(400, {"error": idiomas.mensaje(e, self.idioma())})
                else:
                    if estado not in ESTADOS:
                        return self.error(400, "srv.estado_no_valido")
                    p["estado"] = estado
                    p["t"][estado] = time.time()
                guardar_pedidos(pedidos)
            log(f"Pedido {p['numero']} (" + (p.get("tipo") if pedidos_online.es_online(p) else f"mesa {p['mesa']}") + f") -> {estado}")
            sello = None
            if estado == "entregado" and p.get("tarjeta"):
                # Un sello por pedido como máximo (pedido_id único): volver a «servido» tras deshacer no lo duplica
                sello, tarjeta = sellos.sellar(p["tarjeta"], p["total"], "servido", pedido_id=p["id"])
                log(f"Pedido {p['numero']}: sello {sello}" + (f" ({tarjeta['sellos']}/{tarjeta['sellos_meta']})" if sello == "sellado" else ""))
                if sello == "sellado":
                    wallet.notificar_en_segundo_plano(p["tarjeta"])
            return self.responder(200, {"ok": True, "pedido": pedidos_online.sin_secretos(p), "sello": sello})
        if ruta == "/api/logout":
            m = re.search(re.escape(COOKIE) + r"=([A-Za-z0-9_\-]+)", self.headers.get("Cookie") or "")
            if m:
                with bloqueo:
                    sesiones.pop(huella(m.group(1)), None)
                    guardar_sesiones()
            return self.responder(200, {"ok": True}, cabeceras=[("Set-Cookie", f"{COOKIE}=; Path=/; Max-Age=0" + ("; Secure" if self.es_https() else ""))])
        return self.error(404, "srv.no_existe")

    def do_DELETE(self):
        u = urlparse(self.path)
        if u.path.startswith(RUTAS_TARJETA) and tarjeta_web.delete(self, u.path):
            return
        if u.path.startswith(RUTAS_PROMOCIONES) and promociones_web.delete(self, u.path):
            return
        if u.path != "/api/foto":
            return self.error(404, "srv.no_existe")
        if not self.autenticado():
            return self.error(401, "srv.sesion.caducada")
        ing_id = (parse_qs(u.query).get("id") or [""])[0]
        with bloqueo:
            fotos = json.load(open(FOTOS_JSON, encoding="utf-8"))
            f = fotos.get(ing_id)
            if not f or not f.get("subida"):
                return self.error(404, "srv.foto.sin_foto")
            del fotos[ing_id]
            escribir_fotos(fotos)
            for carpeta in (RDIR, WEB):
                ruta = os.path.join(carpeta, "fotos", f"{ing_id}.webp")
                if os.path.exists(ruta):
                    os.remove(ruta)
        return self.responder(200, {"ok": True})

    def do_PUT(self):
        if urlparse(self.path).path.startswith(RUTAS_TARJETA) and tarjeta_web.put(self, urlparse(self.path).path):
            return
        if urlparse(self.path).path != "/api/datos":
            return self.error(404, "srv.no_existe")
        if not self.autenticado():
            return self.error(401, "srv.sesion.caducada")
        try:
            nuevos = validar(self.cuerpo_json(), self.idioma())
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as e:
            return self.error_de(e, "srv.datos_no_validos")
        with bloqueo:
            actual = leer_datos()
            if nuevos["version"] != actual.get("version", 0):
                return self.error(409, "srv.datos.conflicto")
            nuevos["version"] = actual.get("version", 0) + 1
            guardar_datos(nuevos)
        return self.responder(200, {"ok": True, "version": nuevos["version"]})


class Servidor(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 256   # con el valor por defecto (5), varios móviles cargando las ~120 fotos a la vez dejaban conexiones colgadas decenas de segundos


def ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 80))   # dirección reservada para documentación: un connect UDP no envía nada, solo elige la interfaz
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def en_contenedor():
    return os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")


def info_red():
    """Dirección que se puede ofrecer para los QR. Dentro de un contenedor la IP que ve el proceso es la interna
    del contenedor (172.x): un móvil no la abre, y el servidor no puede saber la del ordenador anfitrión."""
    if en_contenedor():
        return {"ip": "", "contenedor": True}
    return {"ip": ip_local(), "contenedor": False}


def main():
    ap = argparse.ArgumentParser(description=f"Servidor de la carta de {restaurante.marca()['nombre']}")
    ap.add_argument("--puerto", type=int, default=int(os.environ.get("PUERTO", "8080")))
    ap.add_argument("--clave", help="cambia la contraseña del backoffice y sale")
    a = ap.parse_args()
    if a.clave:
        if len(a.clave) < 6:
            sys.exit("La contraseña debe tener al menos 6 caracteres.")
        guardar_clave(a.clave)
        print("Contraseña del backoffice cambiada.")
        return
    if not os.path.isdir(WEB):
        sys.exit("Falta la carpeta web/. Ejecuta antes:  python preparar_netlify.py")
    if not os.path.exists(CONFIG) and os.environ.get("CLAVE_BACKOFFICE"):
        if len(os.environ["CLAVE_BACKOFFICE"]) < 6:
            sys.exit("CLAVE_BACKOFFICE debe tener al menos 6 caracteres.")
        guardar_clave(os.environ["CLAVE_BACKOFFICE"])
        print("  Contraseña del backoffice creada desde CLAVE_BACKOFFICE.")
    if not os.path.exists(CONFIG):
        clave = "-".join(secrets.choice(["pollo", "bocata", "barra", "alioli", "brasa", "mesa", "salsa"]) for _ in range(2)) + "-" + str(secrets.randbelow(900) + 100)
        guardar_clave(clave)
        with open(os.path.join(RDIR, "clave_inicial.txt"), "w", encoding="utf-8") as f:
            f.write(f"Contraseña inicial del backoffice: {clave}\nCámbiala con:  python servidor.py --clave TU_CLAVE\n")
        print(f"\n  Contraseña inicial del backoffice: {clave}\n  (guardada en clave_inicial.txt; cámbiala con --clave)\n")
    cargar_sesiones()
    if COPIA_HORAS > 0:
        threading.Thread(target=bucle_copias, daemon=True).start()
    srv = Servidor((os.environ.get("ESCUCHAR", "0.0.0.0"), a.puerto), Manejador)
    ip = info_red()["ip"] or "IP-DEL-ORDENADOR"   # en Docker no se conoce la del anfitrión
    print(f"  Carta:       http://localhost:{a.puerto}/     (desde el móvil en tu wifi: http://{ip}:{a.puerto}/)")
    print(f"  Backoffice:  http://localhost:{a.puerto}/admin")
    print(f"  Cocina:      http://localhost:{a.puerto}/cocina")
    print(f"  Una mesa:    http://{ip}:{a.puerto}/?mesa=5   (así abrirá la carta el QR de cada mesa)")
    print("  Para pararlo: Ctrl+C\n", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

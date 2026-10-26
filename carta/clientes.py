# SPDX-License-Identifier: EUPL-1.2
"""Clientes que dan permiso para recibir publicidad (LSSI art. 21) y prueba de ese permiso. SQLite de la biblioteca estándar.

Solo se guarda a quien marca la casilla de permiso (sin premarcar): sin permiso no se guarda el email.
Por defecto, marcar la casilla (sin premarcar) da el alta directa (`alta_directa`): es lo que exige la LSSI art. 21. Con CONFIRMACION_DOBLE=1
hay doble confirmación: marcar la casilla NO da el alta, solo crea una solicitud pendiente y manda al propio correo un enlace de un solo uso
(máximo un correo por hora y dirección, caduca a los 7 días, una baja lo invalida). Solo el clic del titular (`confirmar`) registra el alta.
Cada alta y cada baja es una fila nueva de `permisos` (nunca se edita ni se borra): es la prueba, con el texto exacto
que vio la persona, su versión, la fecha y hora y el canal. «Apto para marketing» = el último movimiento del cliente es un alta.
Un enlace de baja (token propio de cada cliente) lleva a una página que pide confirmación antes de registrar la baja.
Cada canal de promoción (correo, aviso en la tarjeta de Wallet) solo vale si el texto que vio la persona lo cubría
(CUBRE): quien dio permiso con una versión que solo hablaba de correo no recibe avisos en Wallet."""
import contextlib, datetime, html, json, os, re, secrets, sqlite3

import idiomas, restaurante, sellos

DB = os.path.join(restaurante.DIR, "clientes.db")
TEXTO_VERSION = "2"
CUBRE = {"email": {"1", "2"}, "wallet": {"2"}}   # versiones del texto cuyo permiso cubre cada canal
CANAL_PEDIDO = "pedido-carta"
CANAL_RESERVA = "reserva"
ESPERA_CORREO = datetime.timedelta(hours=1)    # entre dos correos de confirmación a la misma dirección
CADUCIDAD = datetime.timedelta(days=7)         # vida del enlace de confirmación
EMAIL_RE = re.compile(r"^[^@\s{}<>\"'\\]{1,64}@[^@\s.{}<>\"'\\]+(\.[^@\s.{}<>\"'\\]+)+$")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    token_baja TEXT NOT NULL UNIQUE,
    creado TEXT NOT NULL,
    idioma TEXT NOT NULL DEFAULT 'es'
);
CREATE TABLE IF NOT EXISTS permisos (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    accion TEXT NOT NULL CHECK (accion IN ('alta', 'baja')),
    fecha TEXT NOT NULL,
    canal TEXT NOT NULL,
    texto_version TEXT,
    texto TEXT,
    idioma TEXT
);
CREATE INDEX IF NOT EXISTS permisos_cliente ON permisos(cliente_id, id);
CREATE TABLE IF NOT EXISTS solicitudes (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    token TEXT NOT NULL UNIQUE,
    creada TEXT NOT NULL,
    canal TEXT NOT NULL,
    texto_version TEXT NOT NULL,
    texto TEXT NOT NULL,
    idioma TEXT NOT NULL,
    cerrada TEXT
);
CREATE INDEX IF NOT EXISTS solicitudes_cliente ON solicitudes(cliente_id, id);
CREATE TABLE IF NOT EXISTS vinculos (
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    tarjeta_id TEXT NOT NULL,
    fecha TEXT NOT NULL,
    PRIMARY KEY (cliente_id, tarjeta_id)
);
"""


def texto_permiso(idioma=idiomas.FUENTE):
    """Texto exacto de la casilla del restaurante activo en ese idioma (todos dicen lo mismo). Si cambia su significado
    en algún idioma, hay que subir TEXTO_VERSION."""
    return idiomas.t("clientes.permiso.texto", idioma, nombre=restaurante.marca()["nombre"])


@contextlib.contextmanager
def conectar():
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(ESQUEMA)
        for tabla, columna in (("clientes", "idioma TEXT NOT NULL DEFAULT 'es'"), ("permisos", "idioma TEXT")):   # bases anteriores a los idiomas
            if not any(c["name"] == "idioma" for c in con.execute(f"PRAGMA table_info({tabla})")):
                con.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna}")
        with con:
            yield con
    finally:
        con.close()


def ahora():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")


def validar_email(v):
    if not isinstance(v, str) or len(v.strip()) > 120 or not EMAIL_RE.match(v.strip()):
        raise idiomas.Msg("clientes.error.email")
    return v.strip().lower()


def validar_permiso(permiso):
    """Comprueba lo que manda la carta (email, versión del texto que vio) sin guardar nada. Devuelve el email normalizado."""
    if not isinstance(permiso, dict):
        raise idiomas.Msg("clientes.error.permiso")
    if permiso.get("version") != TEXTO_VERSION:
        raise idiomas.Msg("clientes.error.version")
    return validar_email(permiso.get("email"))


def url_publica():
    """Dirección pública del local para construir enlaces de los correos: SOLO la configurada (URL_PUBLICA), nunca la cabecera Host."""
    u = os.environ.get("URL_PUBLICA", "").strip().rstrip("/")
    return u if re.match(r"https?://[^\s/]+", u) else None


def confirmacion_doble():
    """True si el local pide doble confirmación del permiso (CONFIRMACION_DOBLE=1); por defecto, alta directa."""
    return os.environ.get("CONFIRMACION_DOBLE", "").strip().lower() in ("1", "true", "si", "sí", "yes")


def alta_directa(email, canal=CANAL_PEDIDO, idioma=idiomas.FUENTE):
    """Registra el alta con la prueba (fecha, canal, versión y texto exacto que vio la persona) sin solicitud ni correo.
    Si ya es apto no duplica. Devuelve el id del cliente."""
    idioma = idiomas.valido(idioma) or idiomas.FUENTE
    with conectar() as con:
        fila = con.execute("SELECT id FROM clientes WHERE email=?", (email,)).fetchone()
        t = ahora()
        if fila:
            cid = fila["id"]
        else:
            cid = con.execute("INSERT INTO clientes(email, token_baja, creado, idioma) VALUES (?,?,?,?)",
                              (email, secrets.token_urlsafe(24), t, idioma)).lastrowid
        if not _apto(con, cid):
            con.execute("INSERT INTO permisos(cliente_id, accion, fecha, canal, texto_version, texto, idioma) VALUES (?,?,?,?,?,?,?)",
                        (cid, "alta", t, canal, TEXTO_VERSION, texto_permiso(idioma), idioma))
    return cid


def solicitar_alta(email, canal=CANAL_PEDIDO, idioma=idiomas.FUENTE):
    """Registra una solicitud de permiso PENDIENTE (no es un alta). Devuelve (id del cliente, token de confirmación o None).
    Token None = no hace falta mandar correo: ya tiene permiso vigente o ya se le mandó uno hace menos de ESPERA_CORREO.
    `idioma` es el que vio la persona (se guarda con el texto exacto mostrado para la prueba futura)."""
    idioma = idiomas.valido(idioma) or idiomas.FUENTE
    with conectar() as con:
        fila = con.execute("SELECT id FROM clientes WHERE email=?", (email,)).fetchone()
        t = ahora()
        if fila:
            cid = fila["id"]
        else:
            cid = con.execute("INSERT INTO clientes(email, token_baja, creado, idioma) VALUES (?,?,?,?)",
                              (email, secrets.token_urlsafe(24), t, idioma)).lastrowid
        if _apto(con, cid):
            return cid, None
        u = con.execute("SELECT creada FROM solicitudes WHERE cliente_id=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
        if u and datetime.datetime.fromisoformat(t) - datetime.datetime.fromisoformat(u["creada"]) < ESPERA_CORREO:
            return cid, None
        token = secrets.token_urlsafe(24)
        con.execute("INSERT INTO solicitudes(cliente_id, token, creada, canal, texto_version, texto, idioma) VALUES (?,?,?,?,?,?,?)",
                    (cid, token, t, canal, TEXTO_VERSION, texto_permiso(idioma), idioma))
    return cid, token


def registrar_alta(email, canal=CANAL_PEDIDO, idioma=idiomas.FUENTE):
    """Lo que ejecuta POST /api/pedido con permiso. Por defecto da el alta directa (ver `alta_directa`); con CONFIRMACION_DOBLE=1
    solo deja la solicitud pendiente de confirmar (ver `solicitar_alta`) y NO da el alta. Devuelve el id del cliente."""
    if not confirmacion_doble():
        return alta_directa(email, canal, idioma)
    return solicitar_alta(email, canal, idioma)[0]


def _solicitud_vigente(con, token):
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_\-]{20,64}", token):
        return None
    s = con.execute("SELECT s.*, c.email FROM solicitudes s JOIN clientes c ON c.id=s.cliente_id WHERE s.token=? AND s.cerrada IS NULL", (token,)).fetchone()
    if s and datetime.datetime.fromisoformat(ahora()) - datetime.datetime.fromisoformat(s["creada"]) < CADUCIDAD:
        return s
    return None


def solicitud_por_token(token):
    """Solicitud pendiente y no caducada con ese token (id del cliente, email, idioma), o None."""
    with conectar() as con:
        return _solicitud_vigente(con, token)


def confirmar(token, canal="enlace-confirmacion"):
    """El titular confirma: registra el alta con la prueba (texto, versión, fecha, canal) y gasta el token. Devuelve True si valía."""
    with conectar() as con:
        s = _solicitud_vigente(con, token)
        if not s:
            return False
        t = ahora()
        if con.execute("UPDATE solicitudes SET cerrada=? WHERE id=? AND cerrada IS NULL", (t, s["id"])).rowcount != 1:
            return False
        con.execute("INSERT INTO permisos(cliente_id, accion, fecha, canal, texto_version, texto, idioma) VALUES (?,?,?,?,?,?,?)",
                    (s["cliente_id"], "alta", t, f"{s['canal']}+{canal}", s["texto_version"], s["texto"], s["idioma"]))
    return True


def cliente_por_token(token):
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_\-]{20,64}", token):
        return None
    with conectar() as con:
        return con.execute("SELECT id, email, idioma FROM clientes WHERE token_baja=?", (token,)).fetchone()


def registrar_baja(token, canal="enlace-baja", idioma=idiomas.FUENTE):
    """Registra la baja con fecha (y el idioma de la página desde la que se pidió). Devuelve True si había un cliente con ese token."""
    c = cliente_por_token(token)
    if not c:
        return False
    with conectar() as con:
        t = ahora()
        if _apto(con, c["id"]):
            con.execute("INSERT INTO permisos(cliente_id, accion, fecha, canal, idioma) VALUES (?,?,?,?,?)",
                        (c["id"], "baja", t, canal, idiomas.valido(idioma) or idiomas.FUENTE))
        con.execute("UPDATE solicitudes SET cerrada=? WHERE cliente_id=? AND cerrada IS NULL", (t, c["id"]))   # una baja invalida lo pendiente
    return True


def _apto(con, cid):
    u = con.execute("SELECT accion FROM permisos WHERE cliente_id=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    return bool(u and u["accion"] == "alta")


def apto_marketing(email):
    with conectar() as con:
        c = con.execute("SELECT id FROM clientes WHERE email=?", (email.strip().lower(),)).fetchone()
        return bool(c and _apto(con, c["id"]))


def apto(cid, canal):
    """True si el último movimiento del cliente es un alta cuyo texto cubría ese canal («email» o «wallet»)."""
    with conectar() as con:
        u = con.execute("SELECT accion, texto_version FROM permisos WHERE cliente_id=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    if not u or u["accion"] != "alta":
        return False
    return u["texto_version"] in CUBRE[canal]


def vincular_tarjeta(cid, tid):
    """Une una tarjeta de sellos con un cliente que dio permiso (así los avisos de Wallet solo van a quien lo autorizó).
    La tarjeta pasa a salir en el idioma del cliente."""
    with conectar() as con:
        con.execute("INSERT OR IGNORE INTO vinculos(cliente_id, tarjeta_id, fecha) VALUES (?,?,?)", (cid, tid, ahora()))
        c = con.execute("SELECT idioma FROM clientes WHERE id=?", (cid,)).fetchone()
    if c:
        sellos.poner_idioma(tid, c["idioma"])


def destinatarios(canal):
    """Quién puede recibir una promoción por ese canal ahora mismo. «email»: [{cliente, email, token, idioma}].
    «wallet»: [{tarjeta, clientes, token, idioma}], solo tarjetas cuyos clientes vinculados están TODOS con permiso vigente para Wallet."""
    with conectar() as con:
        cl = {r["id"]: r for r in con.execute("SELECT id, email, token_baja, idioma FROM clientes ORDER BY id")}
        vinc = {}
        for v in con.execute("SELECT cliente_id, tarjeta_id FROM vinculos ORDER BY rowid"):
            vinc.setdefault(v["tarjeta_id"], []).append(v["cliente_id"])
    if canal == "email":
        return [{"cliente": c["id"], "email": c["email"], "token": c["token_baja"], "idioma": c["idioma"]} for c in cl.values() if apto(c["id"], "email")]
    return [{"tarjeta": t, "clientes": ids, "token": cl[ids[0]]["token_baja"], "idioma": cl[ids[0]]["idioma"]} for t, ids in vinc.items()
            if all(apto(i, "wallet") for i in ids)]


def datos_permiso(cid):
    """Fecha y canal del último alta del cliente (para decirle en cada mensaje por qué lo recibe)."""
    with conectar() as con:
        return con.execute("SELECT fecha, canal FROM permisos WHERE cliente_id=? AND accion='alta' ORDER BY id DESC LIMIT 1", (cid,)).fetchone()


def ficha(cid_o_email):
    """Ficha completa del cliente: datos, si es apto para marketing y todas las pruebas (altas y bajas, de la más antigua a la más nueva)."""
    with conectar() as con:
        c = con.execute("SELECT * FROM clientes WHERE id=? OR email=?", (cid_o_email, str(cid_o_email).strip().lower())).fetchone()
        if not c:
            return None
        pruebas = [dict(p) for p in con.execute(
            "SELECT accion, fecha, canal, texto_version, texto, idioma FROM permisos WHERE cliente_id=? ORDER BY id", (c["id"],))]
        pend = [x["creada"] for x in con.execute("SELECT creada, token FROM solicitudes WHERE cliente_id=? AND cerrada IS NULL ORDER BY id DESC", (c["id"],))
                if _solicitud_vigente(con, x["token"])]
        return {"id": c["id"], "email": c["email"], "idioma": c["idioma"], "creado": c["creado"], "apto_marketing": _apto(con, c["id"]),
                "pendiente": pend[0] if pend and not _apto(con, c["id"]) else None, "permisos": pruebas}


def listar():
    with conectar() as con:
        ids = [r["id"] for r in con.execute("SELECT id FROM clientes ORDER BY id")]
    return [f for f in (ficha(i) for i in ids) if f["permisos"] or f["pendiente"]]   # los pendientes de confirmar salen sin prueba (nunca como aptos)


def enlace_baja(token, base, idioma=None):
    """Enlace de baja del cliente. Con `idioma`, la página de baja sale en él (?lang=); sin él, en el del cliente guardado
    (los correos y avisos usan el enlace sin ?lang=: la página ya conoce el idioma del cliente por su token)."""
    return f"{base.rstrip('/')}/baja?t={token}" + (f"&lang={idioma}" if idiomas.valido(idioma) else "")


def enlace_confirmar(token, base, idioma=None):
    """Enlace de confirmación del permiso (página con botón: abrirlo no confirma nada)."""
    return f"{base.rstrip('/')}/confirmar?t={token}" + (f"&lang={idioma}" if idiomas.valido(idioma) else "")


# ---------- página de baja (se renderiza en servidor: no carga idiomas.js) ----------
PAGINA_BAJA = """<!doctype html><html lang="@@LANG@@"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>@@TITULO_PAGINA@@</title>
<link rel="stylesheet" href="/estatico/fuentes/fuentes.css"><link rel="stylesheet" href="/tema.css"><link rel="stylesheet" href="/estatico/base.css">
<style>body{display:grid;place-items:center;min-height:100vh;padding:var(--s-4)}
main{max-width:440px;display:grid;gap:var(--s-4)}p{margin:0}</style></head><body><main>
<h1>@@TITULO@@</h1>
<p id="msg">@@MENSAJE@@</p>
<button id="ok" @@OCULTO@@>@@BOTON@@</button>
</main><script>
const T=@@T@@,ok=document.getElementById('ok'),msg=document.getElementById('msg');
ok.addEventListener('click',async()=>{ok.disabled=true;
 try{const r=await fetch('@@API@@',{method:'POST',headers:{'Content-Type':'application/json','X-Idioma':'@@LANG@@'},body:JSON.stringify({token:@@TOKEN@@})});
  if(!r.ok)throw 0;msg.textContent=T.listo;ok.hidden=true}
 catch(_){msg.textContent=T.fallo;ok.disabled=false}});
</script></body></html>"""


def pagina_baja(token, headers=None, lang=None):
    """Página de baja ya rellena (bytes). Idioma: `lang` (?lang=) si es uno de los ocho; si no, el guardado del cliente; si no,
    el de la petición (`headers`: X-Idioma o Accept-Language); si no, castellano."""
    c = cliente_por_token(token)
    idioma = idiomas.valido(lang) or (c["idioma"] if c else None) or (idiomas.de_peticion(headers) if headers is not None else idiomas.FUENTE)
    nombre = restaurante.marca()["nombre"]
    esc = lambda txt: html.escape(txt, quote=False)
    js = json.dumps({"listo": idiomas.t("baja.listo", idioma, nombre=nombre), "fallo": idiomas.t("baja.fallo", idioma)},
                    ensure_ascii=False).replace("</", "<\\/")
    if c:
        mensaje, oculto, tok = esc(idiomas.t("baja.confirmar", idioma, email=c["email"], nombre=nombre)), "", json.dumps(token)
    else:
        mensaje, oculto, tok = esc(idiomas.t("baja.enlace_invalido", idioma)), "hidden", "null"
    pagina = (PAGINA_BAJA.replace("@@TITULO_PAGINA@@", esc(idiomas.t("baja.titulo_pagina", idioma, nombre=nombre)))
              .replace("@@TITULO@@", esc(idiomas.t("baja.titulo", idioma))).replace("@@BOTON@@", esc(idiomas.t("baja.boton", idioma)))
              .replace("@@MENSAJE@@", mensaje).replace("@@OCULTO@@", oculto).replace("@@TOKEN@@", tok)
              .replace("@@T@@", js).replace("@@LANG@@", idioma).replace("@@API@@", "/api/baja"))
    return restaurante.plantilla(pagina).encode("utf-8")


def pagina_confirmar(token, headers=None, lang=None):
    """Página de confirmación del permiso (bytes): muestra el correo y un botón; solo el clic (POST /api/confirmar) da el alta.
    Idioma: ?lang=, si no el de la solicitud, si no el de la petición."""
    c = solicitud_por_token(token)
    idioma = idiomas.valido(lang) or (c["idioma"] if c else None) or (idiomas.de_peticion(headers) if headers is not None else idiomas.FUENTE)
    nombre = restaurante.marca()["nombre"]
    esc = lambda txt: html.escape(txt, quote=False)
    js = json.dumps({"listo": idiomas.t("confirmar.listo", idioma, nombre=nombre), "fallo": idiomas.t("confirmar.fallo", idioma)},
                    ensure_ascii=False).replace("</", "<\\/")
    if c:
        mensaje, oculto, tok = esc(idiomas.t("confirmar.mensaje", idioma, email=c["email"], nombre=nombre)), "", json.dumps(token)
    else:
        mensaje, oculto, tok = esc(idiomas.t("confirmar.enlace_invalido", idioma)), "hidden", "null"
    pagina = (PAGINA_BAJA.replace("@@TITULO_PAGINA@@", esc(idiomas.t("confirmar.titulo_pagina", idioma, nombre=nombre)))
              .replace("@@TITULO@@", esc(idiomas.t("confirmar.titulo", idioma))).replace("@@BOTON@@", esc(idiomas.t("confirmar.boton", idioma)))
              .replace("@@MENSAJE@@", mensaje).replace("@@OCULTO@@", oculto).replace("@@TOKEN@@", tok)
              .replace("@@T@@", js).replace("@@LANG@@", idioma).replace("@@API@@", "/api/confirmar"))
    return restaurante.plantilla(pagina).encode("utf-8")

# SPDX-License-Identifier: EUPL-1.2
"""Promociones: redactar en el backoffice y enviarlas por correo (Brevo) y como aviso en la tarjeta de Wallet,
SOLO a quien dio permiso (LSSI art. 21; ver clientes.py). SQLite de la biblioteca estándar (promociones.db, fuera de git).

Reglas que cumple cada envío:
- Destinatarios = clientes cuyo último movimiento es un alta cuyo texto cubría ese canal (clientes.destinatarios). Se vuelve a
  comprobar justo antes de cada envío: una baja que llega mientras se envía se respeta.
- Cada mensaje lleva el enlace de baja del cliente (correo: pie y cabecera List-Unsubscribe; Wallet: enlace en el pase y en el
  mensaje) y el correo se identifica como publicidad al principio del asunto (LSSI art. 20).
- Registro de cada envío (`envios`): qué promoción, por qué canal, a quién, cuándo y con qué resultado. No se edita ni se borra.
  Una promoción solo se envía una vez, y cada (promoción, canal, destino) como mucho una vez (UNIQUE): un reintento no duplica.
- Límite de Wallet: como mucho LIMITE_WALLET avisos por tarjeta cada 24 h (el tope de Google para avisos con notificación)."""
import contextlib, datetime, html, json, re, sqlite3, threading, os

import clientes, correo, idiomas, restaurante, wallet, wallet_apple, wallet_google

DB = os.path.join(restaurante.DIR, "promociones.db")
CANALES = ("email", "wallet")
LIMITE_WALLET = 3
VENTANA_WALLET = 24 * 3600
REANUDAR_TRAS = 1800   # segundos: un envío «enviando» más viejo se considera caído y se puede reanudar

ESQUEMA = """
CREATE TABLE IF NOT EXISTS promociones (
    id INTEGER PRIMARY KEY,
    titulo TEXT NOT NULL,
    texto TEXT NOT NULL,
    canales TEXT NOT NULL,
    creada TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (estado IN ('borrador', 'enviando', 'enviada')),
    inicio TEXT,
    fin TEXT
);
CREATE TABLE IF NOT EXISTS envios (
    id INTEGER PRIMARY KEY,
    promocion_id INTEGER NOT NULL REFERENCES promociones(id),
    canal TEXT NOT NULL CHECK (canal IN ('email', 'wallet')),
    cliente_id INTEGER,
    tarjeta_id TEXT,
    destino TEXT NOT NULL,
    fecha TEXT NOT NULL,
    resultado TEXT NOT NULL,
    detalle TEXT,
    UNIQUE (promocion_id, canal, destino)
);
CREATE INDEX IF NOT EXISTS envios_tarjeta ON envios(tarjeta_id, fecha);
"""


@contextlib.contextmanager
def conectar():
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(ESQUEMA)
        with con:
            yield con
    finally:
        con.close()


def _ahora(delta=0):
    t = datetime.datetime.now(datetime.timezone.utc).astimezone() + datetime.timedelta(seconds=delta)
    return t.isoformat(timespec="seconds")


def canal_disponible(canal):
    if canal == "email":
        return correo.modo() is not None
    return wallet_apple.modo() is not None or wallet_google.modo() is not None


# ---------- redactar ----------
def validar(titulo, texto, canales):
    if not isinstance(titulo, str) or not 3 <= len(titulo.strip()) <= 60 or re.search(r"[\x00-\x1f]", titulo):
        raise idiomas.Msg("promo.error.titulo")
    if not isinstance(texto, str) or not 5 <= len(texto.strip()) <= 300 or re.search(r"[\x00-\x08\x0b-\x1f]", texto):
        raise idiomas.Msg("promo.error.mensaje")
    if (not isinstance(canales, list) or not canales or len(set(canales)) != len(canales)
            or any(c not in CANALES for c in canales)):
        raise idiomas.Msg("promo.error.canales")
    for c in canales:
        if not canal_disponible(c):
            raise idiomas.Msg("promo.error.canal_email" if c == "email" else "promo.error.canal_wallet")
    return titulo.strip(), texto.strip(), sorted(canales)


def crear(titulo, texto, canales):
    titulo, texto, canales = validar(titulo, texto, canales)
    with conectar() as con:
        return con.execute("INSERT INTO promociones(titulo, texto, canales, creada, estado) VALUES (?,?,?,?, 'borrador')",
                           (titulo, texto, json.dumps(canales), _ahora())).lastrowid


def borrar_borrador(pid):
    with conectar() as con:
        return con.execute("DELETE FROM promociones WHERE id=? AND estado='borrador'", (pid,)).rowcount == 1


def _fila(r, con):
    cuentas = {}
    for x in con.execute("SELECT canal, resultado, COUNT(*) n FROM envios WHERE promocion_id=? GROUP BY canal, resultado", (r["id"],)):
        cuentas.setdefault(x["canal"], {})[x["resultado"]] = x["n"]
    return {"id": r["id"], "titulo": r["titulo"], "texto": r["texto"], "canales": json.loads(r["canales"]), "creada": r["creada"],
            "estado": r["estado"], "inicio": r["inicio"], "fin": r["fin"], "resultados": cuentas}


def listar():
    with conectar() as con:
        return [_fila(r, con) for r in con.execute("SELECT * FROM promociones ORDER BY id DESC")]


def obtener(pid):
    with conectar() as con:
        r = con.execute("SELECT * FROM promociones WHERE id=?", (pid,)).fetchone()
        return _fila(r, con) if r else None


def registro(pid):
    """El registro de envíos de una promoción: a quién, por qué canal, cuándo y qué pasó."""
    with conectar() as con:
        return [dict(r) for r in con.execute(
            "SELECT canal, cliente_id, tarjeta_id, destino, fecha, resultado, detalle FROM envios WHERE promocion_id=? ORDER BY id", (pid,))]


def destinatarios():
    """Cuántos recibirían una promoción ahora mismo (para que la persona lo vea antes de enviar)."""
    total = len([f for f in clientes.listar() if f["permisos"]])   # los pendientes de confirmar no cuentan como «sin permiso»
    return {"email": len(clientes.destinatarios("email")), "wallet": len(clientes.destinatarios("wallet")), "clientes": total}


# ---------- enviar ----------
def _reclamar(pid):
    """Pasa la promoción de borrador a «enviando» de una vez (dos pulsaciones no la envían dos veces). Reanuda una caída."""
    with conectar() as con:
        n = con.execute("UPDATE promociones SET estado='enviando', inicio=? WHERE id=? AND (estado='borrador' OR (estado='enviando' AND inicio<?))",
                        (_ahora(), pid, _ahora(-REANUDAR_TRAS))).rowcount
    return n == 1


def _apuntar(con, pid, canal, destino, cliente_id=None, tarjeta_id=None):
    """Reserva el envío antes de hacerlo: si ya estaba, devuelve None (no se repite). Si no, el id de la fila."""
    try:
        return con.execute("INSERT INTO envios(promocion_id, canal, cliente_id, tarjeta_id, destino, fecha, resultado) VALUES (?,?,?,?,?,?, 'pendiente')",
                           (pid, canal, cliente_id, tarjeta_id, destino, _ahora())).lastrowid
    except sqlite3.IntegrityError:
        return None


def _cerrar(eid, resultado, detalle=""):
    with conectar() as con:
        con.execute("UPDATE envios SET resultado=?, detalle=?, fecha=? WHERE id=?", (resultado, detalle, _ahora(), eid))


def componer_correo(promo, dest, base, marca, idioma=idiomas.FUENTE):
    """Correo de una promoción en `idioma` (el del cliente: _enviar_email lo toma de dest["idioma"]). El título y el texto de la
    promoción son los que escribió el local; el resto (identificación como publicidad, motivo y baja) sale del idioma."""
    idioma = idiomas.valido(idioma) or idiomas.FUENTE
    nombre = marca["nombre"]
    baja = clientes.enlace_baja(dest["token"], base)
    p = clientes.datos_permiso(dest["cliente"])
    por_que = (idiomas.t("correo.pie.motivo_fecha", idioma, nombre=nombre, fecha=idiomas.fecha(datetime.date.fromisoformat(p["fecha"][:10]), idioma))
               if p else idiomas.t("correo.pie.motivo_generico", idioma, nombre=nombre))
    texto = f"{promo['texto']}\n\n--\n{por_que}\n{idiomas.t('correo.pie.baja_texto', idioma, enlace=baja)}\n"
    cuerpo = "".join(f"<p>{html.escape(l)}</p>" for l in promo["texto"].split("\n") if l.strip())
    html_ = (f"<!doctype html><html lang=\"{idioma}\"><body style=\"font-family:system-ui,sans-serif;max-width:560px\"><h2>{html.escape(promo['titulo'])}</h2>{cuerpo}"
             f"<hr><p style=\"font-size:13px;color:#555\">{html.escape(por_que)}<br><a href=\"{html.escape(baja)}\">{html.escape(idiomas.t('correo.pie.baja_enlace', idioma))}</a></p></body></html>")
    return {"para": dest["email"], "remitente": nombre, "asunto": idiomas.t("correo.asunto.publicidad", idioma, titulo=promo["titulo"]), "texto": texto, "html": html_,
            "cabeceras": {"List-Unsubscribe": f"<{baja}>"}}


def componer_confirmacion(email, token, base, marca, idioma=idiomas.FUENTE):
    """Correo de confirmación del permiso (NO es publicidad: no lleva «Publicidad:» ni baja). El enlace usa `base`, que viene de la
    configuración (clientes.url_publica), nunca de la petición."""
    idioma = idiomas.valido(idioma) or idiomas.FUENTE
    nombre = marca["nombre"]
    enlace = clientes.enlace_confirmar(token, base, idioma)
    dias = clientes.CADUCIDAD.days
    texto = idiomas.t("correo.confirmacion.texto", idioma, nombre=nombre, enlace=enlace, dias=dias)
    cuerpo = "".join(f"<p>{html.escape(l)}</p>" for l in idiomas.t("correo.confirmacion.cuerpo", idioma, nombre=nombre, dias=dias).split("\n") if l.strip())
    html_ = (f"<!doctype html><html lang=\"{idioma}\"><body style=\"font-family:system-ui,sans-serif;max-width:560px\">{cuerpo}"
             f"<p><a href=\"{html.escape(enlace)}\">{html.escape(idiomas.t('correo.confirmacion.enlace', idioma))}</a></p></body></html>")
    return {"para": email, "remitente": nombre, "asunto": idiomas.t("correo.asunto.confirmacion", idioma, nombre=nombre), "texto": texto, "html": html_,
            "cabeceras": {}}


def enviar_confirmacion(email, token, idioma=idiomas.FUENTE):
    """Manda al propio correo el enlace de confirmación. Devuelve True si salió (o quedó en el simulador); False si no hay canal de
    correo, no hay URL_PUBLICA o falló el envío: entonces el cliente queda pendiente y no recibe publicidad."""
    base = clientes.url_publica()
    if correo.modo() is None or not base:
        return False
    return correo.enviar(componer_confirmacion(email, token, base, restaurante.marca(), idioma))[0]


def _enviar_email(pid, promo, base, marca):
    for d in clientes.destinatarios("email"):
        if not clientes.apto(d["cliente"], "email"):   # baja llegada mientras se enviaba
            continue
        with conectar() as con:
            eid = _apuntar(con, pid, "email", d["email"], cliente_id=d["cliente"])
        if eid is None:
            continue
        try:
            ok, detalle = correo.enviar(componer_correo(promo, d, base, marca, idioma=d.get("idioma") or idiomas.FUENTE))
        except Exception as e:   # noqa: BLE001
            ok, detalle = False, repr(e)[:200]
        _cerrar(eid, "enviado" if ok else "fallido", detalle)


def _avisos_recientes(tid):
    with conectar() as con:
        return con.execute("SELECT COUNT(*) FROM envios WHERE canal='wallet' AND tarjeta_id=? AND resultado='enviado' AND fecha>?",
                           (tid, _ahora(-VENTANA_WALLET))).fetchone()[0]


def _enviar_wallet(pid, promo, base):
    for d in clientes.destinatarios("wallet"):
        if not all(clientes.apto(i, "wallet") for i in d["clientes"]):
            continue
        with conectar() as con:
            eid = _apuntar(con, pid, "wallet", d["tarjeta"], cliente_id=d["clientes"][0], tarjeta_id=d["tarjeta"])
        if eid is None:
            continue
        if _avisos_recientes(d["tarjeta"]) >= LIMITE_WALLET:
            _cerrar(eid, "omitido_limite", f"tope de avisos: ya tiene {LIMITE_WALLET} en 24 h")
            continue
        try:
            llego, detalle = wallet.avisar(d["tarjeta"], promo["titulo"], promo["texto"], clientes.enlace_baja(d["token"], base), idioma=d.get("idioma"))
        except Exception as e:   # noqa: BLE001
            llego, detalle = None, repr(e)[:200]
        _cerrar(eid, "fallido" if llego is None else "enviado" if llego else "sin_destino", detalle)


def _hacer(pid, promo, base):
    marca = restaurante.marca()
    try:
        if "email" in promo["canales"] and canal_disponible("email"):
            _enviar_email(pid, promo, base, marca)
        if "wallet" in promo["canales"] and canal_disponible("wallet"):
            _enviar_wallet(pid, promo, base)
    finally:
        with conectar() as con:
            con.execute("UPDATE promociones SET estado='enviada', fin=? WHERE id=?", (_ahora(), pid))


def ejecutar(pid, base, segundo_plano=False):
    """Empieza el envío de una promoción en borrador (o caída). False si no existe o ya se envió / se está enviando.
    La reserva se hace aquí, antes de devolver: dos pulsaciones seguidas no la envían dos veces."""
    promo = obtener(pid)
    if not promo or not _reclamar(pid):
        return False
    if segundo_plano:
        threading.Thread(target=_hacer, args=(pid, promo, base), daemon=True).start()
    else:
        _hacer(pid, promo, base)
    return True

# SPDX-License-Identifier: EUPL-1.2
"""Tarjeta de sellos de fidelidad. SQLite de la biblioteca estándar (sellos.db, fuera de git).

Reglas: un sello por pedido como máximo (la columna pedido_id es única), solo si el total llega al importe mínimo,
y el premio se canjea restando `sellos_meta` sellos. Cada sello y cada canje es una fila de `movimientos` que no se edita:
el saldo es la suma. El premio, la meta y el importe mínimo los decide el restaurante (sellos.json, desde el backoffice).
La tarjeta es anónima (no lleva correo ni nombre); el permiso de publicidad sigue siendo cosa de clientes.py."""
import contextlib, datetime, hmac, json, os, re, secrets, sqlite3, time

import idiomas, restaurante

DB = os.path.join(restaurante.DIR, "sellos.db")
CONFIG = os.path.join(restaurante.DIR, "sellos.json")
ID_RE = re.compile(r"[A-Za-z0-9_-]{16}")
POR_DEFECTO = {"activo": True, "sellos_meta": 8, "premio": "Un detalle de la casa", "importe_minimo": 5.0, "premio_i18n": {}}
IDIOMAS_PREMIO = tuple(i for i in idiomas.IDIOMAS if i != idiomas.FUENTE)   # el premio base (`premio`) está en castellano

ESQUEMA = """
CREATE TABLE IF NOT EXISTS tarjetas (
    id TEXT PRIMARY KEY,
    auth_token TEXT NOT NULL,
    creado TEXT NOT NULL,
    actualizado REAL NOT NULL,
    idioma TEXT NOT NULL DEFAULT 'es'
);
CREATE TABLE IF NOT EXISTS movimientos (
    id INTEGER PRIMARY KEY,
    tarjeta_id TEXT NOT NULL REFERENCES tarjetas(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('sello', 'canje')),
    delta INTEGER NOT NULL,
    pedido_id TEXT UNIQUE,
    importe REAL,
    origen TEXT NOT NULL,
    fecha TEXT NOT NULL,
    detalle TEXT
);
CREATE INDEX IF NOT EXISTS movimientos_tarjeta ON movimientos(tarjeta_id, id);
CREATE TABLE IF NOT EXISTS dispositivos (
    id INTEGER PRIMARY KEY,
    dispositivo TEXT NOT NULL,
    push_token TEXT NOT NULL,
    tarjeta_id TEXT NOT NULL REFERENCES tarjetas(id),
    UNIQUE (dispositivo, tarjeta_id)
);
CREATE TABLE IF NOT EXISTS avisos (
    tarjeta_id TEXT PRIMARY KEY REFERENCES tarjetas(id),
    titulo TEXT NOT NULL,
    texto TEXT NOT NULL,
    baja_url TEXT NOT NULL,
    fecha TEXT NOT NULL
);
"""


# ---------- configuración del restaurante ----------
def config():
    """sellos.json del restaurante completado con los valores por defecto (los valores malos se ignoran)."""
    try:
        with open(CONFIG, encoding="utf-8") as f:
            leida = json.load(f)
    except (OSError, ValueError):
        leida = {}
    if not isinstance(leida, dict):
        leida = {}
    c = {**POR_DEFECTO, **{k: v for k, v in leida.items() if k in POR_DEFECTO}}
    try:
        return {**leida, **validar_config(c)}
    except ValueError:
        return {**leida, **POR_DEFECTO}


def validar_config(c):
    if not isinstance(c, dict):
        raise idiomas.Msg("sellos.error.ajustes")
    meta, minimo, premio = c.get("sellos_meta"), c.get("importe_minimo"), c.get("premio")
    if not isinstance(meta, int) or isinstance(meta, bool) or not 1 <= meta <= 30:
        raise idiomas.Msg("sellos.error.meta")
    if not isinstance(minimo, (int, float)) or isinstance(minimo, bool) or not 0 <= minimo <= 999:
        raise idiomas.Msg("sellos.error.minimo")
    if not isinstance(premio, str) or not 1 <= len(premio.strip()) <= 80 or re.search(r"[\x00-\x1f]", premio):
        raise idiomas.Msg("sellos.error.premio")
    if not isinstance(c.get("activo"), bool):
        raise idiomas.Msg("sellos.error.activo")
    traducidos = c.get("premio_i18n") or {}
    if not isinstance(traducidos, dict):
        raise idiomas.Msg("sellos.error.premio")
    limpios = {}
    for idioma in IDIOMAS_PREMIO:
        txt = traducidos.get(idioma) or ""
        if not isinstance(txt, str) or len(txt.strip()) > 80 or re.search(r"[\x00-\x1f]", txt):
            raise idiomas.Msg("sellos.error.premio")
        if txt.strip():
            limpios[idioma] = txt.strip()
    return {"activo": c["activo"], "sellos_meta": meta, "premio": premio.strip(), "importe_minimo": round(float(minimo), 2), "premio_i18n": limpios}


def premio_en(c, idioma):
    """El premio en un idioma: el que escribió el dueño para ese idioma; si lo dejó vacío y el premio es el de fábrica, su traducción
    de los ficheros de idioma; si no, el texto en castellano."""
    if idioma in IDIOMAS_PREMIO:
        propio = (c.get("premio_i18n") or {}).get(idioma)
        if propio:
            return propio
        if c["premio"] == POR_DEFECTO["premio"]:
            return idiomas.t("sellos.premio_defecto", idioma)
    return c["premio"]


def premios(c):
    return {i: premio_en(c, i) for i in idiomas.IDIOMAS}


def guardar_config(nuevos):
    """Valida y guarda lo que edita el backoffice. Lo demás de sellos.json (la parte `wallet`) se conserva."""
    limpios = validar_config(nuevos)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            actual = json.load(f)
    except (OSError, ValueError):
        actual = {}
    actual = {**(actual if isinstance(actual, dict) else {}), **limpios}
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(actual, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CONFIG)
    return limpios


# ---------- base de datos ----------
@contextlib.contextmanager
def conectar():
    con = sqlite3.connect(DB, timeout=10, isolation_level=None)   # transacciones a mano (BEGIN IMMEDIATE)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(ESQUEMA)
        if not any(c["name"] == "idioma" for c in con.execute("PRAGMA table_info(tarjetas)")):   # base anterior a los idiomas
            con.execute("ALTER TABLE tarjetas ADD COLUMN idioma TEXT NOT NULL DEFAULT 'es'")
        yield con
    finally:
        con.close()


@contextlib.contextmanager
def transaccion():
    with conectar() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            yield con
        except BaseException:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")


def ahora():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")


def id_valido(tid):
    return isinstance(tid, str) and bool(ID_RE.fullmatch(tid))


def extraer_id(texto):
    """Lo que lee el lector de la caja: el código a secas o un enlace /tarjeta?t=CODIGO. Devuelve el id o None."""
    if not isinstance(texto, str):
        return None
    texto = texto.strip()
    m = re.search(r"[?&]t=([A-Za-z0-9_-]{16})(?![A-Za-z0-9_-])", texto)
    if m:
        return m.group(1)
    return texto if id_valido(texto) else None


def _saldo(con, tid):
    return con.execute("SELECT COALESCE(SUM(delta), 0) FROM movimientos WHERE tarjeta_id=?", (tid,)).fetchone()[0]


def crear_tarjeta(idioma=idiomas.FUENTE):
    """Tarjeta nueva. `idioma` es el de la persona que la pide: los textos de su pase de Wallet salen en él."""
    tid, auth = secrets.token_urlsafe(12), secrets.token_urlsafe(24)
    with conectar() as con:
        con.execute("INSERT INTO tarjetas(id, auth_token, creado, actualizado, idioma) VALUES (?,?,?,?,?)",
                    (tid, auth, ahora(), time.time(), idiomas.valido(idioma) or idiomas.FUENTE))
    return {"id": tid, "auth_token": auth}


def poner_idioma(tid, idioma):
    """Cambia el idioma de la tarjeta (p. ej. al vincularla a un cliente con el suyo) y, si cambia, la marca como modificada."""
    idioma = idiomas.valido(idioma)
    if not idioma or not id_valido(tid):
        return
    with transaccion() as con:
        if con.execute("UPDATE tarjetas SET idioma=? WHERE id=? AND idioma<>?", (idioma, tid, idioma)).rowcount:
            _tocar(con, tid)


def estado(tid, idioma=None):
    """Lo que se enseña de una tarjeta (cliente y caja). None si no existe. El premio sale en `idioma` (por defecto, el de la tarjeta)."""
    if not id_valido(tid):
        return None
    c = config()
    with conectar() as con:
        t = con.execute("SELECT id, creado, actualizado, idioma FROM tarjetas WHERE id=?", (tid,)).fetchone()
        if not t:
            return None
        sellos = _saldo(con, tid)
        canjes = con.execute("SELECT COUNT(*) FROM movimientos WHERE tarjeta_id=? AND tipo='canje'", (tid,)).fetchone()[0]
        aviso = con.execute("SELECT titulo, texto, baja_url, fecha FROM avisos WHERE tarjeta_id=?", (tid,)).fetchone()
    return {"aviso": dict(aviso) if aviso else None, "id": tid, "sellos": sellos, "sellos_meta": c["sellos_meta"],
            "premio": premio_en(c, idiomas.valido(idioma) or t["idioma"]),
            "premios_disponibles": sellos // c["sellos_meta"], "canjes": canjes, "creado": t["creado"], "actualizado": t["actualizado"], "idioma": t["idioma"]}


def auth_valido(tid, token):
    if not id_valido(tid) or not isinstance(token, str):
        return False
    with conectar() as con:
        t = con.execute("SELECT auth_token FROM tarjetas WHERE id=?", (tid,)).fetchone()
    return bool(t and hmac.compare_digest(t["auth_token"], token))


def auth_token(tid):
    with conectar() as con:
        t = con.execute("SELECT auth_token FROM tarjetas WHERE id=?", (tid,)).fetchone()
    return t["auth_token"] if t else None


def _tocar(con, tid):
    # +1 µs por si dos cambios caen en el mismo reloj: «passesUpdatedSince» de Apple compara con el último valor visto
    con.execute("UPDATE tarjetas SET actualizado=MAX(?, actualizado + 0.000001) WHERE id=?", (time.time(), tid))


def sellar(tid, importe, origen, pedido_id=None):
    """Intenta dar un sello. Devuelve (resultado, estado): resultado es «sellado», «repetido» (ese pedido ya dio su sello),
    «importe_bajo», «tope» (ya tiene el premio: hay que canjearlo antes de seguir), «desactivado» o «sin_tarjeta».
    Con la tarjeta dada de baja o sin programa no se hace nada."""
    c = config()
    if not c["activo"]:
        return "desactivado", estado(tid)
    if not id_valido(tid) or estado(tid) is None:
        return "sin_tarjeta", None
    if not isinstance(importe, (int, float)) or isinstance(importe, bool) or importe < c["importe_minimo"]:
        return "importe_bajo", estado(tid)
    try:
        with transaccion() as con:
            if _saldo(con, tid) >= c["sellos_meta"]:   # el tope se comprueba y se aplica en la misma transacción
                return "tope", estado(tid)
            con.execute("INSERT INTO movimientos(tarjeta_id, tipo, delta, pedido_id, importe, origen, fecha) VALUES (?,?,?,?,?,?,?)",
                        (tid, "sello", 1, pedido_id, round(float(importe), 2), origen, ahora()))
            _tocar(con, tid)
    except sqlite3.IntegrityError:
        return "repetido", estado(tid)
    return "sellado", estado(tid)


def canjear(tid):
    """Resta `sellos_meta` sellos y apunta el canje. Devuelve (True, estado) o (False, estado) si no llegan los sellos."""
    c = config()
    with transaccion() as con:
        if not id_valido(tid) or not con.execute("SELECT 1 FROM tarjetas WHERE id=?", (tid,)).fetchone():
            return False, None
        if _saldo(con, tid) < c["sellos_meta"]:
            ok = False
        else:
            con.execute("INSERT INTO movimientos(tarjeta_id, tipo, delta, origen, fecha, detalle) VALUES (?,?,?,?,?,?)",
                        (tid, "canje", -c["sellos_meta"], "caja", ahora(), c["premio"]))
            _tocar(con, tid)
            ok = True
    return ok, estado(tid)


def listar(busqueda="", limite=30):
    """Últimas tarjetas por uso para la lista de la caja: solo código, sellos y fechas (la tarjeta es anónima; nada de contacto)."""
    c = config()
    like = "%" + re.sub(r"[%_\\]", "", str(busqueda or "").strip()) + "%"
    with conectar() as con:
        filas = con.execute(
            "SELECT t.id, t.creado, COALESCE(SUM(m.delta), 0) AS sellos, MAX(m.fecha) AS ultimo FROM tarjetas t "
            "LEFT JOIN movimientos m ON m.tarjeta_id=t.id WHERE t.id LIKE ? GROUP BY t.id ORDER BY t.actualizado DESC LIMIT ?",
            (like, int(limite))).fetchall()
        total = con.execute("SELECT COUNT(*) FROM tarjetas").fetchone()[0]
    return {"total": total, "tarjetas": [{"id": f["id"], "sellos": f["sellos"], "sellos_meta": c["sellos_meta"],
                                         "premio_disponible": f["sellos"] >= c["sellos_meta"], "ultimo_uso": f["ultimo"] or f["creado"]} for f in filas]}


def poner_aviso(tid, titulo, texto, baja_url):
    """Deja en la tarjeta la última promoción (la que muestra el pase de Wallet) y marca la tarjeta como cambiada."""
    with transaccion() as con:
        con.execute("INSERT INTO avisos(tarjeta_id, titulo, texto, baja_url, fecha) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(tarjeta_id) DO UPDATE SET titulo=excluded.titulo, texto=excluded.texto, baja_url=excluded.baja_url, fecha=excluded.fecha",
                    (tid, titulo, texto, baja_url, ahora()))
        _tocar(con, tid)


def movimientos(tid):
    with conectar() as con:
        return [dict(m) for m in con.execute(
            "SELECT tipo, delta, pedido_id, importe, origen, fecha, detalle FROM movimientos WHERE tarjeta_id=? ORDER BY id", (tid,))]


# ---------- dispositivos de Apple Wallet (servicio web de PassKit) ----------
def registrar_dispositivo(dispositivo, push_token, tid):
    """Devuelve True si es un registro nuevo (201) y False si ya estaba (200; se actualiza el push token)."""
    with conectar() as con:
        ya = con.execute("SELECT 1 FROM dispositivos WHERE dispositivo=? AND tarjeta_id=?", (dispositivo, tid)).fetchone()
        con.execute("INSERT INTO dispositivos(dispositivo, push_token, tarjeta_id) VALUES (?,?,?) "
                    "ON CONFLICT(dispositivo, tarjeta_id) DO UPDATE SET push_token=excluded.push_token", (dispositivo, push_token, tid))
    return not ya


def quitar_dispositivo(dispositivo, tid):
    with conectar() as con:
        con.execute("DELETE FROM dispositivos WHERE dispositivo=? AND tarjeta_id=?", (dispositivo, tid))


def tarjetas_de_dispositivo(dispositivo, desde=None):
    """(ids, última marca) de las tarjetas de ese dispositivo cambiadas después de `desde` (epoch); sin `desde`, todas."""
    with conectar() as con:
        filas = con.execute("SELECT t.id, t.actualizado FROM dispositivos d JOIN tarjetas t ON t.id=d.tarjeta_id "
                            "WHERE d.dispositivo=? AND t.actualizado>? ORDER BY t.actualizado", (dispositivo, desde or 0)).fetchall()
    return [f["id"] for f in filas], (max(f["actualizado"] for f in filas) if filas else None)


def push_tokens(tid):
    with conectar() as con:
        return [f["push_token"] for f in con.execute("SELECT DISTINCT push_token FROM dispositivos WHERE tarjeta_id=?", (tid,))]

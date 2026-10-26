# SPDX-License-Identifier: EUPL-1.2
"""Las cuatro cifras del backoffice (pestaña Cifras): pedidos por QR, tarjetas guardadas, reseñas (clics al botón) y clientes que repiten.
Todo se calcula al pedirlo desde lo que ya existe (pedidos.json, historial/, sellos.db) más una tabla propia, kpis.db, con un
clic por pedido al botón de reseña. De Google no se puede leer cuántas reseñas llegan de verdad: el clic es lo medible."""
import contextlib, datetime, glob, json, os, re, sqlite3

import idiomas, restaurante, sellos

DB = os.path.join(restaurante.DIR, "kpis.db")
PEDIDOS = os.path.join(restaurante.DIR, "pedidos.json")
HISTORIAL = os.path.join(restaurante.DIR, "historial")
MES_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
ESQUEMA = "CREATE TABLE IF NOT EXISTS clics_resena (pedido_id TEXT PRIMARY KEY, fecha TEXT NOT NULL);"


@contextlib.contextmanager
def _conectar(ruta, esquema=""):
    con = sqlite3.connect(ruta, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        if esquema:
            con.executescript(esquema)
        yield con
        con.commit()
    finally:
        con.close()


def registrar_clic_resena(pedido_id):
    """Apunta el clic al botón de reseña (uno por pedido: pulsarlo varias veces no cuenta más)."""
    if not isinstance(pedido_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", pedido_id):
        return False
    with _conectar(DB, ESQUEMA) as con:
        con.execute("INSERT OR IGNORE INTO clics_resena(pedido_id, fecha) VALUES (?, ?)", (pedido_id, sellos.ahora()))
    return True


def mes_anterior(mes):
    a, m = int(mes[:4]), int(mes[5:])
    return f"{a - 1}-12" if m == 1 else f"{a}-{m - 1:02d}"


def mes_actual():
    return datetime.date.today().isoformat()[:7]


def _pedidos():
    try:
        with open(PEDIDOS, encoding="utf-8") as f:
            todos = json.load(f)
    except (OSError, ValueError):
        todos = []
    for ruta in sorted(glob.glob(os.path.join(HISTORIAL, "pedidos-*.jsonl"))):
        with open(ruta, encoding="utf-8") as f:
            todos += [json.loads(l) for l in f if l.strip()]
    return [p for p in todos if p.get("estado") not in ("rechazado", "cancelado")]   # pedidos online que no llegaron a hacerse


def _pct(parte, total):
    return round(100 * parte / total, 1) if total else None


def _cifras(mes, pedidos):
    delmes = [p for p in pedidos if str(p.get("fecha", ""))[:7] == mes]
    qr = sum(1 for p in delmes if p.get("via") == "qr")
    manual = sum(1 for p in delmes if p.get("via") == "manual")   # los anteriores a medirse (sin «via») no entran en el porcentaje
    with sellos.conectar() as con:
        tarjetas = con.execute("SELECT COUNT(*) FROM tarjetas WHERE substr(creado, 1, 7) = ?", (mes,)).fetchone()[0]
        repiten = con.execute("SELECT COUNT(*) FROM (SELECT tarjeta_id FROM movimientos WHERE tipo = 'sello' AND substr(fecha, 1, 7) = ? "
                              "GROUP BY tarjeta_id HAVING COUNT(*) >= 2)", (mes,)).fetchone()[0]
    with _conectar(DB, ESQUEMA) as con:
        clics = con.execute("SELECT COUNT(*) FROM clics_resena WHERE substr(fecha, 1, 7) = ?", (mes,)).fetchone()[0]
    return {"pedidos": len(delmes), "pedidos_qr": qr, "pedidos_manual": manual, "pedidos_sin_medir": len(delmes) - qr - manual,
            "pct_qr": _pct(qr, qr + manual), "tarjetas_nuevas": tarjetas, "clics_resena": clics, "clientes_repiten": repiten}


def nombre_mes(mes, idioma=idiomas.FUENTE):
    """«2026-10» -> «octubre de 2026» / «October 2026» / «2026年10月» (tablas propias, nunca locale)."""
    return idiomas.mes(int(mes[:4]), int(mes[5:]), idioma)


def calcular(mes=None, idioma=idiomas.FUENTE):
    """Cifras del mes (AAAA-MM, por defecto el actual), las del mes anterior y los totales de siempre de tarjetas y clientes fieles.
    «mes_texto» y «anterior_texto» son los nombres de esos meses en el idioma pedido."""
    if mes is None:
        mes = mes_actual()
    if not isinstance(mes, str) or not MES_RE.fullmatch(mes):
        raise idiomas.Msg("kpis.mes_no_valido")
    pedidos = _pedidos()
    m = restaurante.marca()
    with sellos.conectar() as con:
        total_tarjetas = con.execute("SELECT COUNT(*) FROM tarjetas").fetchone()[0]
        total_repiten = con.execute("SELECT COUNT(*) FROM (SELECT tarjeta_id FROM movimientos WHERE tipo = 'sello' "
                                    "GROUP BY tarjeta_id HAVING COUNT(*) >= 2)").fetchone()[0]
    return {"mes": mes, "mes_texto": nombre_mes(mes, idioma), "anterior": mes_anterior(mes), "anterior_texto": nombre_mes(mes_anterior(mes), idioma), "actual": _cifras(mes, pedidos), "previo": _cifras(mes_anterior(mes), pedidos),
            "totales": {"tarjetas": total_tarjetas, "clientes_repiten": total_repiten},
            "resena": {"enlace": restaurante.resena_url(m), "valor": m.get("resena_url") or m.get("google_place_id") or ""}}

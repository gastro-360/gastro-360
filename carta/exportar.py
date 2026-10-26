# SPDX-License-Identifier: EUPL-1.2
"""Exportar pedidos (backoffice → Exportar): CSV y Excel (.xlsx) de un rango de días, con la stdlib.
Cada línea de pedido es una fila; el total del pedido sale solo en la primera línea de cada pedido (así la columna se puede sumar).
Sin datos de clientes (ni nombre, ni correo, ni nota, ni dirección o teléfono de los pedidos online) y sin nada de cobro: el aviso «no es una factura» va en los dos formatos."""
import csv, datetime, io, re, zipfile
from xml.sax.saxutils import escape

import idiomas, kpis

MAX_DIAS = 366
FORMATOS = ("csv", "xlsx")
FECHA_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
ESTADOS = ("nuevo", "recibido", "aceptado", "preparando", "listo", "en_reparto", "entregado")
COLUMNAS = ("fecha", "numero", "mesa", "zona", "estado", "producto", "extras", "cantidad", "precio", "subtotal", "total", "tipo", "envio")
NUMERICAS = {"numero": 1, "mesa": 1, "cantidad": 1, "precio": 2, "subtotal": 2, "total": 2, "envio": 2}   # columna -> estilo (1 entero, 2 importe)


def fecha_iso(valor):
    if not isinstance(valor, str) or not FECHA_RE.fullmatch(valor):
        raise idiomas.Msg("srv.exportar.fecha_no_valida", valor=str(valor)[:20])
    try:
        return datetime.date.fromisoformat(valor)
    except ValueError:
        raise idiomas.Msg("srv.exportar.fecha_no_valida", valor=valor) from None


def rango(desde, hasta, hoy):
    """(desde, hasta) como fechas. Sin indicar: el mes en curso hasta hoy. Lanza idiomas.Msg si no vale."""
    hoy = datetime.date.fromisoformat(hoy)
    d = fecha_iso(desde) if desde else hoy.replace(day=1)
    h = fecha_iso(hasta) if hasta else hoy
    if d > h:
        raise idiomas.Msg("srv.exportar.orden", desde=d.isoformat(), hasta=h.isoformat())
    dias = (h - d).days + 1
    if dias > MAX_DIAS:
        raise idiomas.Msg("srv.exportar.rango_largo", dias=dias, max=MAX_DIAS)
    return d, h


def pedidos_en(desde, hasta):
    """Pedidos cuyo día de servicio cae entre desde y hasta (ambos incluidos), por fecha y número."""
    d, h = desde.isoformat(), hasta.isoformat()
    return sorted((p for p in kpis._pedidos() if d <= p.get("fecha", "") <= h), key=lambda p: (p["fecha"], p.get("creado", 0), p.get("numero", 0)))


def _texto(v, idioma):
    return idiomas.tr(v, idioma) if isinstance(v, dict) else str(v)


def _momento(p):
    try:
        return datetime.datetime.fromtimestamp(p["creado"]).replace(second=0, microsecond=0)
    except (KeyError, TypeError, ValueError, OSError):
        return datetime.datetime.fromisoformat(p["fecha"])


def filas(pedidos, idioma):
    """Una fila por línea de pedido: dict por columna; fecha como datetime y los números como int/float."""
    salida = []
    for p in pedidos:
        for i, l in enumerate(p.get("lineas") or [{}]):
            cant, precio = l.get("cant", 0), l.get("precio", 0)
            tipo = p.get("tipo") if p.get("tipo") in ("domicilio", "recoger") else "mesa"   # ni dirección ni teléfono: no salen del servidor
            salida.append({"fecha": _momento(p), "numero": p.get("numero", ""), "tipo": idiomas.t("exportar.tipo." + tipo, idioma),
                           "mesa": p.get("mesa") or "", "zona": p.get("zona", ""),
                           "estado": idiomas.t("exportar.estado." + p["estado"], idioma) if p.get("estado") in ESTADOS else p.get("estado", ""),
                           "producto": _texto(l.get("n", ""), idioma), "extras": ", ".join(_texto(e, idioma) for e in l.get("extra") or []),
                           "cantidad": cant, "precio": precio, "subtotal": round(cant * precio, 2),
                           # total del pedido = lo que vio el cliente: productos + gastos de envío (solo en la primera línea)
                           "total": total_pedido(p) if i == 0 else "", "envio": p.get("envio", 0) if i == 0 else ""})
    return salida


def total_pedido(p):
    """Productos más gastos de envío (los pedidos de mesa no llevan envío)."""
    return round(p.get("total", 0) + p.get("envio", 0), 2)


def resumen(pedidos):
    return {"pedidos": len(pedidos), "lineas": sum(len(p.get("lineas") or [1]) for p in pedidos), "total": round(sum(total_pedido(p) for p in pedidos), 2)}


def nombre_fichero(desde, hasta, formato):
    return f"pedidos_{desde.isoformat()}_a_{hasta.isoformat()}.{formato}"


def _cabeceras(idioma):
    return [idiomas.t("exportar.col." + c, idioma) for c in COLUMNAS]


def _aviso(desde, hasta, idioma):
    return idiomas.t("exportar.aviso", idioma, desde=desde.isoformat(), hasta=hasta.isoformat())


# ---------- CSV ----------
def _seguro(texto):
    """Una celda de texto que empieza por = + - @ (o por tabulación o retorno) la tomaría Excel por una fórmula: se le antepone una comilla simple."""
    return "'" + texto if texto[:1] in ("=", "+", "-", "@", "\t", "\r") else texto


def _celda_csv(col, v):
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if col in NUMERICAS and v != "":
        return str(v) if NUMERICAS[col] == 1 else f"{v:.2f}".replace(".", ",")
    return _seguro(str(v))


def a_csv(desde, hasta, pedidos, idioma):
    """UTF-8 con BOM, «;» de separador, coma decimal y CRLF. Primera línea: el aviso; segunda: las cabeceras."""
    b = io.StringIO(newline="")
    w = csv.writer(b, delimiter=";", quotechar='"', lineterminator="\r\n")
    w.writerow([_aviso(desde, hasta, idioma)])
    w.writerow(_cabeceras(idioma))
    for f in filas(pedidos, idioma):
        w.writerow([_celda_csv(c, f[c]) for c in COLUMNAS])
    return b.getvalue().encode("utf-8-sig")


# ---------- Excel (.xlsx) ----------
ANCHOS = {"fecha": 17, "numero": 9, "mesa": 7, "zona": 14, "estado": 14, "producto": 30, "extras": 30, "cantidad": 9, "precio": 12, "subtotal": 12, "total": 14, "tipo": 12, "envio": 10}
NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
CABECERA_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
ILEGALES = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _xml(txt):
    return escape(ILEGALES.sub("", str(txt)))


def _col(i):
    return chr(ord("A") + i)


def _cadena(ref, txt, estilo=0):
    # Cadena en línea (t="inlineStr"): Excel nunca la evalúa como fórmula, aunque empiece por «=».
    return f'<c r="{ref}" t="inlineStr"' + (f' s="{estilo}"' if estilo else "") + f'><is><t xml:space="preserve">{_xml(txt)}</t></is></c>'


def _serie(dt):
    return (dt - datetime.datetime(1899, 12, 30)).total_seconds() / 86400


def nombre_hoja(idioma):
    return re.sub(r"[\[\]:*?/\\]", "-", idiomas.t("exportar.hoja", idioma))[:31]


def a_xlsx(desde, hasta, pedidos, idioma):
    """Libro de una hoja: fila 1 el aviso, fila 2 las cabeceras (fija al desplazarse) y desde la 3 los datos. Estilos: 1 negrita, 2 entero, 3 importe, 4 fecha y hora."""
    estilo = {c: (2 if NUMERICAS.get(c) == 1 else 3) for c in NUMERICAS}
    estilo["fecha"] = 4
    filas_xml = [f'<row r="1">{_cadena("A1", _aviso(desde, hasta, idioma), 1)}</row>',
                 '<row r="2">' + "".join(_cadena(f"{_col(i)}2", t, 1) for i, t in enumerate(_cabeceras(idioma))) + "</row>"]
    for n, f in enumerate(filas(pedidos, idioma), start=3):
        celdas = []
        for i, c in enumerate(COLUMNAS):
            v, ref = f[c], f"{_col(i)}{n}"
            if v == "":
                continue
            if isinstance(v, datetime.datetime):
                celdas.append(f'<c r="{ref}" s="4"><v>{_serie(v):.10f}</v></c>')
            elif c in NUMERICAS:
                celdas.append(f'<c r="{ref}" s="{estilo[c]}"><v>{v}</v></c>')
            else:
                celdas.append(_cadena(ref, v))
        filas_xml.append(f'<row r="{n}">' + "".join(celdas) + "</row>")
    ultima = len(filas_xml)
    hoja = (CABECERA_XML + f'<worksheet {NS}><dimension ref="A1:{_col(len(COLUMNAS) - 1)}{ultima}"/>'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="2" topLeftCell="A3" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            '<sheetFormatPr defaultRowHeight="15"/><cols>'
            + "".join(f'<col min="{i + 1}" max="{i + 1}" width="{ANCHOS[c]}" customWidth="1"/>' for i, c in enumerate(COLUMNAS))
            + "</cols><sheetData>" + "".join(filas_xml) + "</sheetData></worksheet>")
    estilos = (CABECERA_XML + f'<styleSheet {NS}><numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd\\ hh:mm"/></numFmts>'
               '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
               '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
               '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
               '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
               '<cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
               '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
               '<xf numFmtId="1" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
               '<xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
               '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
               '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    libro = (CABECERA_XML + f'<workbook {NS} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
             f'<sheets><sheet name="{_xml(nombre_hoja(idioma))}" sheetId="1" r:id="rId1"/></sheets></workbook>')
    rels_libro = (CABECERA_XML + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                  '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                  '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    rels = (CABECERA_XML + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    tipos = (CABECERA_XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
             '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
             '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, contenido in (("[Content_Types].xml", tipos), ("_rels/.rels", rels), ("xl/workbook.xml", libro),
                                  ("xl/_rels/workbook.xml.rels", rels_libro), ("xl/styles.xml", estilos), ("xl/worksheets/sheet1.xml", hoja)):
            z.writestr(zipfile.ZipInfo(nombre, (2026, 1, 1, 0, 0, 0)), contenido.encode("utf-8"), zipfile.ZIP_DEFLATED)
    return b.getvalue()

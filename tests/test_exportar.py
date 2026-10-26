# SPDX-License-Identifier: EUPL-1.2
"""Exportar pedidos a CSV y Excel:  python -m unittest tests.test_exportar -v
Usa una carpeta temporal (CARTA_RESTAURANTES): no toca restaurantes/."""
import csv, datetime, http.client, io, json, os, shutil, sys, tempfile, threading, unittest, xml.etree.ElementTree as ET, zipfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="exportar-")
os.environ.update(CARTA_RESTAURANTES=TMP, RESTAURANTE="demo")
sys.path.insert(0, os.path.join(RAIZ, "carta"))
import nuevo_restaurante  # noqa: E402

nuevo_restaurante.crear("demo", "Bar Demo", raiz=TMP)
import exportar, idiomas, servidor  # noqa: E402

CLAVE = "clave-de-prueba"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def hora(fecha, h, m=0):
    return datetime.datetime.fromisoformat(f"{fecha}T{h:02d}:{m:02d}:00").timestamp()


def pedido(fecha, numero, lineas, estado="entregado", h=13):
    total = round(sum(l["precio"] * l["cant"] for l in lineas), 2)
    return {"id": f"p{fecha}{numero}", "fecha": fecha, "numero": numero, "mesa": 4, "zona": "Terraza", "estado": estado, "creado": hora(fecha, h, numero),
            "lineas": lineas, "total": total, "nota": "sin cebolla, soy Pepa", "cliente": "cliente-secreto", "tarjeta": "tarjeta-secreta"}


def linea(n, cant, precio, extra=()):
    return {"pid": "x", "n": n, "cant": cant, "precio": precio, "extra": list(extra)}


PEDIDOS = [
    pedido("2026-10-01", 1, [linea("Tortilla", 2, 6.5), linea("=HYPERLINK(\"http://x\")", 1, 3.25, ["Queso", "@extra"])]),
    pedido("2026-10-01", 2, [linea("-Caña; \"grande\"\ny más", 3, 2.1)], estado="nuevo"),
    {**pedido("2026-10-15", 1, [linea("+Café", 1, 1.5)]), "tipo": "domicilio", "mesa": None, "zona": "", "envio": 2.5,
     "entrega": {"nombre": "Ana Secreta", "telefono": "699000111", "direccion": "Calle Secreta 9", "cp": "08001"}},
    pedido("2026-11-01", 1, [linea("Fuera de rango", 1, 9)]),
]
HISTORICO = [PEDIDOS[0], PEDIDOS[2]]   # estos dos viven en el historial mensual; el resto en pedidos.json


def siembra():
    os.makedirs(servidor.HISTORIAL, exist_ok=True)
    with open(os.path.join(servidor.HISTORIAL, "pedidos-2026-10.jsonl"), "w", encoding="utf-8") as f:
        for p in HISTORICO:
            f.write(json.dumps(p) + "\n")
    with open(servidor.PEDIDOS, "w", encoding="utf-8") as f:
        json.dump([p for p in PEDIDOS if p not in HISTORICO], f)


class Exportar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        siembra()
        servidor.guardar_clave(CLAVE)
        cls.srv = servidor.Servidor(("127.0.0.1", 0), servidor.Manejador)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.cookie = None
        cls.http("GET", "/api/sesion", auth=False)
        cls.http("POST", "/api/login", {"clave": CLAVE})

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    @classmethod
    def http(cls, metodo, ruta, cuerpo=None, auth=True, cabeceras=None):
        c = http.client.HTTPConnection("127.0.0.1", cls.srv.server_address[1])
        h = {"Content-Type": "application/json", **(cabeceras or {})}
        if auth and cls.cookie:
            h["Cookie"] = cls.cookie
        c.request(metodo, ruta, json.dumps(cuerpo) if cuerpo is not None else None, h)
        r = c.getresponse()
        datos = r.read()
        if r.getheader("Set-Cookie"):
            cls.cookie = r.getheader("Set-Cookie").split(";")[0]
        return r.status, r, datos

    def get_json(self, ruta, **k):
        st, _, d = self.http("GET", ruta, **k)
        return st, json.loads(d)

    def csv(self, desde="2026-10-01", hasta="2026-10-31", extra=""):
        st, r, d = self.http("GET", f"/api/exportar?desde={desde}&hasta={hasta}&formato=csv{extra}")
        self.assertEqual(st, 200, d)
        self.assertTrue(d.startswith(b"\xef\xbb\xbf"), "el CSV debe llevar BOM UTF-8")
        return r, list(csv.reader(io.StringIO(d.decode("utf-8-sig"), newline=""), delimiter=";"))

    # --- acceso y validación
    def test_sin_sesion_401(self):
        for ruta in ("/api/exportar", "/api/exportar?formato=csv", "/api/exportar?desde=2026-10-01&hasta=2026-10-02&formato=xlsx"):
            st, _, _ = self.http("GET", ruta, auth=False)
            self.assertEqual(st, 401, ruta)

    def test_fechas_invalidas_400_explicado(self):
        casos = {"desde=ayer&hasta=2026-10-02": "AAAA-MM-DD", "desde=2026-02-30&hasta=2026-10-02": "AAAA-MM-DD", "desde=2026-10-01&hasta=2026-10-1": "AAAA-MM-DD",
                 "desde=2026-10-05&hasta=2026-10-02": "posterior", "desde=2025-01-01&hasta=2026-12-31": "máximo es 366",
                 "desde=2026-10-01&hasta=2026-10-02&formato=pdf": "csv o xlsx"}
        for q, texto in casos.items():
            st, j = self.get_json("/api/exportar?" + q)
            self.assertEqual(st, 400, q)
            self.assertIn(texto, j["error"], q)
        st, j = self.get_json("/api/exportar?desde=ayer&hasta=2026-10-02", cabeceras={"X-Idioma": "en"})
        self.assertIn("YYYY-MM-DD", j["error"])

    def test_rango_maximo_366_dias_incluido(self):
        st, j = self.get_json("/api/exportar?desde=2026-01-01&hasta=2027-01-01")   # 366 días: vale
        self.assertEqual(st, 200)
        st, _ = self.get_json("/api/exportar?desde=2026-01-01&hasta=2027-01-02")   # 367: no
        self.assertEqual(st, 400)

    def test_por_defecto_el_mes_en_curso(self):
        st, j = self.get_json("/api/exportar")
        hoy = datetime.date.fromisoformat(servidor.dia_servicio())
        self.assertEqual((st, j["desde"], j["hasta"]), (200, hoy.replace(day=1).isoformat(), hoy.isoformat()))

    # --- contenido
    def test_resumen_cuadra(self):
        st, j = self.get_json("/api/exportar?desde=2026-10-01&hasta=2026-10-31")
        esperado = round(sum(p["total"] + p.get("envio", 0) for p in PEDIDOS[:3]), 2)   # con los gastos de envío
        self.assertEqual((st, j["pedidos"], j["lineas"], j["total"]), (200, 3, 4, esperado))
        _, j = self.get_json("/api/exportar?desde=2026-10-15&hasta=2026-10-15")   # ambos extremos incluidos
        self.assertEqual(j["pedidos"], 1)

    def test_csv_formato_y_totales(self):
        r, filas = self.csv()
        self.assertEqual(r.getheader("Content-Disposition"), 'attachment; filename="pedidos_2026-10-01_a_2026-10-31.csv"')
        self.assertTrue(r.getheader("Content-Type").startswith("text/csv"))
        self.assertEqual(filas[0], ["Este documento no es una factura. Listado de pedidos del 2026-10-01 al 2026-10-31."])
        self.assertEqual(filas[1][:3], ["Fecha y hora", "Nº de pedido", "Mesa"])
        datos = filas[2:]
        self.assertEqual(len(datos), 4)
        self.assertTrue(all(len(f) == 13 for f in filas[1:]))   # 12.ª columna: tipo; 13.ª: gastos de envío
        self.assertEqual(filas[1][11:], ["Tipo", "Envío"])
        online = [f for f in filas[2:] if f[11] == "Domicilio"]
        self.assertEqual([(f[10], f[12]) for f in online], [("4,00", "2,50")])   # total = productos + envío
        self.assertNotIn("Secret", "\n".join(";".join(f) for f in filas))      # ni nombre, ni dirección
        self.assertNotIn("699000111", "\n".join(";".join(f) for f in filas))
        coma = lambda s: float(s.replace(",", "."))
        self.assertEqual(round(sum(coma(f[10]) for f in datos if f[10]), 2), round(sum(p["total"] + p.get("envio", 0) for p in PEDIDOS[:3]), 2))   # total solo en la primera línea
        self.assertEqual(round(sum(coma(f[9]) for f in datos), 2), round(sum(p["total"] for p in PEDIDOS[:3]), 2))             # subtotales = totales
        self.assertEqual(datos[0][:5], ["2026-10-01 13:01", "1", "4", "Terraza", "Servido"])
        self.assertEqual((datos[0][7], datos[0][8], datos[0][9], datos[0][10]), ("2", "6,50", "13,00", "16,25"))
        self.assertEqual(datos[1][10], "")
        self.assertNotIn("Fuera de rango", [f[5] for f in datos])

    def test_csv_escapa_formulas_comillas_y_saltos(self):
        _, filas = self.csv()
        productos = [f[5] for f in filas[2:]]
        self.assertIn("'=HYPERLINK(\"http://x\")", productos)
        self.assertIn("'-Caña; \"grande\"\ny más", productos)     # comillas, «;» y salto de línea sobreviven al viaje de ida y vuelta
        self.assertIn("'+Café", productos)
        self.assertIn("Queso, '@extra"[:5], [f[6] for f in filas[2:]][1])
        for f in filas[2:]:
            for celda in f[5:7]:
                self.assertNotRegex(celda, r"^[=+\-@\t\r]")
        st, r, d = self.http("GET", "/api/exportar?desde=2026-10-01&hasta=2026-10-01&formato=csv")
        self.assertIn(b'"\'-Ca\xc3\xb1a; ""grande""\ny m\xc3\xa1s"', d)

    def test_sin_datos_personales(self):
        _, filas = self.csv()
        todo = json.dumps(filas, ensure_ascii=False)
        for secreto in ("Pepa", "cebolla", "cliente-secreto", "tarjeta-secreta"):
            self.assertNotIn(secreto, todo)
        st, _, x = self.http("GET", "/api/exportar?desde=2026-10-01&hasta=2026-10-31&formato=xlsx")
        z = zipfile.ZipFile(io.BytesIO(x))
        for n in z.namelist():
            for secreto in (b"Pepa", b"cebolla", b"cliente-secreto", b"tarjeta-secreta"):
                self.assertNotIn(secreto, z.read(n))

    def test_rango_vacio_solo_cabecera_y_aviso(self):
        r, filas = self.csv("2026-09-01", "2026-09-30")
        self.assertEqual(len(filas), 2)
        self.assertIn("no es una factura", filas[0][0])
        _, j = self.get_json("/api/exportar?desde=2026-09-01&hasta=2026-09-30")
        self.assertEqual((j["pedidos"], j["lineas"], j["total"]), (0, 0, 0))
        st, _, x = self.http("GET", "/api/exportar?desde=2026-09-01&hasta=2026-09-30&formato=xlsx")
        self.assertEqual(len(self.hoja(x)), 2)

    def test_idioma_del_fichero(self):
        _, filas = self.csv(extra="&idioma=en")
        self.assertEqual(filas[0][0], "This document is not an invoice. List of orders from 2026-10-01 to 2026-10-31.")
        self.assertEqual(filas[1][0], "Date and time")
        _, filas = self.csv(extra="&idioma=zh")
        self.assertIn("不是发票", filas[0][0])

    # --- Excel
    def hoja(self, datos, nombre=None):
        """Filas de la hoja como listas de valores (str/float), leyendo el .xlsx solo con zipfile + xml."""
        z = zipfile.ZipFile(io.BytesIO(datos))
        self.assertIsNone(z.testzip())
        for n in z.namelist():
            if n.endswith((".xml", ".rels")):
                ET.fromstring(z.read(n))   # bien formado
        self.assertEqual(z.namelist()[0], "[Content_Types].xml")
        hoja = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        salida = []
        for row in hoja.find("m:sheetData", NS):
            fila = [""] * 13
            for c in row:
                col = ord(c.get("r")[0]) - ord("A")
                if c.get("t") == "inlineStr":
                    fila[col] = "".join(t.text or "" for t in c.iter("{%s}t" % NS["m"]))
                else:
                    fila[col] = float(c.find("m:v", NS).text)
            salida.append(fila)
        return salida

    def test_xlsx_estructura_y_totales(self):
        st, r, d = self.http("GET", "/api/exportar?desde=2026-10-01&hasta=2026-10-31&formato=xlsx")
        self.assertEqual(st, 200)
        self.assertEqual(r.getheader("Content-Disposition"), 'attachment; filename="pedidos_2026-10-01_a_2026-10-31.xlsx"')
        self.assertTrue(r.getheader("Content-Type").endswith("spreadsheetml.sheet"))
        z = zipfile.ZipFile(io.BytesIO(d))
        self.assertEqual(sorted(z.namelist()), sorted(["[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "xl/styles.xml", "xl/worksheets/sheet1.xml"]))
        libro = ET.fromstring(z.read("xl/workbook.xml"))
        hojas = [s.get("name") for s in libro.find("m:sheets", NS)]
        self.assertEqual(hojas, ["Pedidos - no es una factura"])
        filas = self.hoja(d)
        self.assertEqual(filas[0][0], "Este documento no es una factura. Listado de pedidos del 2026-10-01 al 2026-10-31.")
        self.assertEqual(len(filas), 6)
        self.assertEqual(filas[1][0], "Fecha y hora")
        self.assertEqual(round(sum(f[10] for f in filas[2:] if f[10] != ""), 2), round(sum(p["total"] + p.get("envio", 0) for p in PEDIDOS[:3]), 2))
        self.assertEqual(filas[2][5], "Tortilla")
        self.assertEqual(filas[3][5], "=HYPERLINK(\"http://x\")")
        self.assertEqual(filas[4][5], "-Caña; \"grande\"\ny más")
        fecha = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=filas[2][0], seconds=30)   # +30 s: el serie decimal no es exacto
        self.assertEqual(fecha.strftime("%Y-%m-%d %H:%M"), "2026-10-01 13:01")
        estilos = ET.fromstring(z.read("xl/styles.xml"))
        self.assertEqual(estilos.find("m:cellXfs", NS).get("count"), str(len(estilos.find("m:cellXfs", NS))))

    def test_nombre_de_hoja_valido_en_todos_los_idiomas(self):
        for l in idiomas.IDIOMAS:
            n = exportar.nombre_hoja(l)
            self.assertTrue(0 < len(n) <= 31, (l, n))
            self.assertNotRegex(n, r"[\[\]:*?/\\]")
            self.assertRegex(idiomas.t("exportar.aviso", l, desde="a", hasta="b"), r"^(Este documento no es una factura|This document is not an invoice|Aquest document no és una factura|本文件不是发票|Ce document n’est pas une facture|Dieses Dokument ist keine Rechnung|Questo documento non è una fattura|Este documento não é uma fatura)")


if __name__ == "__main__":
    unittest.main()

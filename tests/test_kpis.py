# SPDX-License-Identifier: EUPL-1.2
"""Cifras del backoffice con datos sembrados:  python -m unittest tests.test_kpis -v
Usan una carpeta temporal (CARTA_RESTAURANTES): no tocan restaurantes/."""
import http.client, json, os, shutil, sys, tempfile, threading, unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="kpis-")
os.environ.update(CARTA_RESTAURANTES=TMP, RESTAURANTE="demo")
sys.path.insert(0, os.path.join(RAIZ, "carta"))
import nuevo_restaurante  # noqa: E402

nuevo_restaurante.crear("demo", "Bar Demo", raiz=TMP)
import kpis, sellos, servidor  # noqa: E402

CLAVE = "clave-de-prueba"


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def pedido(fecha, via=None):
    p = {"id": "p" + str(abs(hash((fecha, via, os.urandom(4))))), "fecha": fecha, "estado": "entregado", "total": 9.0}
    if via:
        p["via"] = via
    return p


def tarjeta(creado):
    tid = sellos.crear_tarjeta()["id"]
    with sellos.transaccion() as con:
        con.execute("UPDATE tarjetas SET creado = ? WHERE id = ?", (creado, tid))
    return tid


def sello(tid, fecha, n):
    with sellos.transaccion() as con:
        con.execute("INSERT INTO movimientos(tarjeta_id, tipo, delta, pedido_id, importe, origen, fecha) VALUES (?,?,?,?,?,?,?)",
                    (tid, "sello", 1, f"{tid}-{fecha}-{n}", 8.0, "servido", fecha + "T12:00:00+02:00"))


def siembra():
    os.makedirs(servidor.HISTORIAL, exist_ok=True)
    # septiembre (historial): 1 por QR, 1 a mano
    with open(os.path.join(servidor.HISTORIAL, "pedidos-2025-09.jsonl"), "w", encoding="utf-8") as f:
        for p in (pedido("2025-09-10", "qr"), pedido("2025-09-11", "manual")):
            f.write(json.dumps(p) + "\n")
    # octubre: 3 por QR, 1 a mano, 1 anterior a medirse (sin «via»); uno de ellos ya en el historial
    with open(os.path.join(servidor.HISTORIAL, "pedidos-2025-10.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps(pedido("2025-10-01", "qr")) + "\n")
    with open(servidor.PEDIDOS, "w", encoding="utf-8") as f:
        json.dump([pedido("2025-10-02", "qr"), pedido("2025-10-03", "qr"), pedido("2025-10-04", "manual"), pedido("2025-10-05")], f)
    a, b, c, d = tarjeta("2025-10-02T10:00:00+02:00"), tarjeta("2025-10-03T10:00:00+02:00"), tarjeta("2025-10-04T10:00:00+02:00"), tarjeta("2025-09-20T10:00:00+02:00")
    sello(a, "2025-10-05", 1); sello(a, "2025-10-06", 2)                      # A repite en octubre
    sello(b, "2025-10-05", 1)                                                  # B no
    sello(c, "2025-09-05", 1); sello(c, "2025-10-05", 1); sello(c, "2025-10-07", 2)   # C repite en octubre (1 en sept.)
    sello(d, "2025-09-21", 1); sello(d, "2025-09-22", 2)                      # D repite en septiembre
    with kpis._conectar(kpis.DB, kpis.ESQUEMA) as con:
        con.executemany("INSERT INTO clics_resena(pedido_id, fecha) VALUES (?, ?)",
                        [("a", "2025-10-02T13:00:00+02:00"), ("b", "2025-10-03T13:00:00+02:00"), ("c", "2025-09-12T13:00:00+02:00")])


class Cifras(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        siembra()
        servidor.guardar_clave(CLAVE)
        cls.srv = servidor.Servidor(("127.0.0.1", 0), servidor.Manejador)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.cookie = None
        cls.http("POST", "/api/login", {"clave": CLAVE})

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    @classmethod
    def http(cls, metodo, ruta, cuerpo=None, auth=True):
        c = http.client.HTTPConnection("127.0.0.1", cls.srv.server_address[1])
        h = {"Content-Type": "application/json"}
        if auth and cls.cookie:
            h["Cookie"] = cls.cookie
        c.request(metodo, ruta, json.dumps(cuerpo) if cuerpo is not None else None, h)
        r = c.getresponse()
        txt = r.read().decode()
        if r.getheader("Set-Cookie"):
            cls.cookie = r.getheader("Set-Cookie").split(";")[0]
        return r.status, (json.loads(txt) if txt.startswith(("{", "[")) else txt)

    def test_cifras_del_mes(self):
        d = kpis.calcular("2025-10")
        a, p = d["actual"], d["previo"]
        self.assertEqual((a["pedidos"], a["pedidos_qr"], a["pedidos_manual"], a["pedidos_sin_medir"], a["pct_qr"]), (5, 3, 1, 1, 75.0))
        self.assertEqual((p["pedidos"], p["pct_qr"]), (2, 50.0))
        self.assertEqual((a["tarjetas_nuevas"], p["tarjetas_nuevas"], d["totales"]["tarjetas"]), (3, 1, 4))
        self.assertEqual((a["clics_resena"], p["clics_resena"]), (2, 1))
        self.assertEqual((a["clientes_repiten"], p["clientes_repiten"], d["totales"]["clientes_repiten"]), (2, 1, 3))
        self.assertEqual(d["anterior"], "2025-09")

    def test_mes_sin_datos_y_enero(self):
        d = kpis.calcular("2024-01")
        self.assertIsNone(d["actual"]["pct_qr"])
        self.assertEqual(d["anterior"], "2023-12")
        with self.assertRaises(ValueError):
            kpis.calcular("2025-13")

    def test_clic_una_vez_por_pedido(self):
        antes = kpis.calcular(kpis.mes_actual())["actual"]["clics_resena"]
        for _ in range(3):
            self.assertTrue(kpis.registrar_clic_resena("pedido-nuevo-1"))
        despues = kpis.calcular(kpis.mes_actual())["actual"]["clics_resena"]
        self.assertEqual(despues, antes + 1)
        self.assertFalse(kpis.registrar_clic_resena("../mal"))
        self.assertFalse(kpis.registrar_clic_resena(None))

    def test_http_endpoint(self):
        self.assertEqual(self.http("GET", "/api/kpis?mes=2025-10", auth=False)[0], 401)
        st, d = self.http("GET", "/api/kpis?mes=2025-10")
        self.assertEqual((st, d["actual"]["pct_qr"], d["actual"]["clientes_repiten"], d["actual"]["tarjetas_nuevas"], d["actual"]["clics_resena"]), (200, 75.0, 2, 3, 2))
        self.assertEqual(self.http("GET", "/api/kpis?mes=mal")[0], 400)
        self.assertEqual(self.http("POST", "/api/resena/clic", {"id": "desde-http"}, auth=False)[0], 400)   # no es un pedido: no cuenta
        servido = next(p["id"] for p in servidor.leer_pedidos() if p["estado"] == "entregado")
        self.assertEqual(self.http("POST", "/api/resena/clic", {"id": servido}, auth=False)[0], 200)
        self.assertEqual(self.http("POST", "/api/resena/clic", {"id": "no válido!"}, auth=False)[0], 400)

    def test_enlace_de_resena_desde_el_backoffice(self):
        self.assertEqual(self.http("POST", "/api/resena", {"enlace": "ChIJ_pruebaPlaceId123"}, auth=False)[0], 401)
        self.assertEqual(self.http("GET", "/api/kpis")[1]["resena"], {"enlace": "", "valor": ""})
        for mal in ("http://inseguro.es", 'https://x.es/"onclick="', "corto", "https://con espacio.es", 5):
            self.assertEqual(self.http("POST", "/api/resena", {"enlace": mal})[0], 400, mal)
        self.assertEqual(self.http("GET", "/api/kpis")[1]["resena"]["enlace"], "")
        st, r = self.http("POST", "/api/resena", {"enlace": " ChIJ_pruebaPlaceId123 "})
        self.assertEqual((st, r["enlace"]), (200, "https://search.google.com/local/writereview?placeid=ChIJ_pruebaPlaceId123"))
        web = tempfile.mkdtemp(prefix="web-", dir=TMP)
        with open(os.path.join(web, "index.html"), "w", encoding="utf-8") as f:
            f.write('<script>const RESENA="";</script>')
        servidor.restaurante.WEB, antes = web, servidor.restaurante.WEB
        try:
            self.http("POST", "/api/resena", {"enlace": "https://g.page/r/a;b/review"})
            self.http("POST", "/api/resena", {"enlace": "ChIJ_pruebaPlaceId123"})
            self.assertEqual(open(os.path.join(web, "index.html"), encoding="utf-8").read(),
                             '<script>const RESENA="https://search.google.com/local/writereview?placeid=ChIJ_pruebaPlaceId123";</script>')
        finally:
            servidor.restaurante.WEB = antes
        st, r = self.http("POST", "/api/resena", {"enlace": "https://g.page/r/ejemplo/review"})
        self.assertEqual(self.http("GET", "/api/kpis")[1]["resena"], {"enlace": "https://g.page/r/ejemplo/review", "valor": "https://g.page/r/ejemplo/review"})
        self.assertEqual(self.http("POST", "/api/resena", {"enlace": ""})[1]["enlace"], "")
        self.assertEqual(self.http("GET", "/api/kpis")[1]["resena"], {"enlace": "", "valor": ""})

    def test_pedido_guarda_via(self):
        with open(os.path.join(sellos.restaurante.DIR, "datos.json"), encoding="utf-8") as f:
            datos = json.load(f)
        pid = datos["platos"][0]["id"]
        for via, esperado in (("qr", "qr"), (None, "manual"), ("otra", "manual")):
            cuerpo = {"mesa": 1, "lineas": [{"pid": pid}]}
            if via:
                cuerpo["via"] = via
            st, r = self.http("POST", "/api/pedido", cuerpo, auth=False)
            self.assertEqual(st, 200, r)
            p = next(p for p in servidor.leer_pedidos() if p["id"] == r["id"])
            self.assertEqual(p["via"], esperado)


if __name__ == "__main__":
    unittest.main()

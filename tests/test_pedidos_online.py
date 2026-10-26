# SPDX-License-Identifier: EUPL-1.2
"""Pedidos online (a domicilio y para recoger):  python3 -m unittest tests.test_pedidos_online -v
Usa una carpeta temporal (CARTA_RESTAURANTES): no toca restaurantes/."""
import datetime, http.client, json, os, re, shutil, sys, tempfile, threading, unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="online-")
os.environ.update(CARTA_RESTAURANTES=TMP, RESTAURANTE="demo")
sys.path.insert(0, os.path.join(RAIZ, "carta"))
import nuevo_restaurante  # noqa: E402

nuevo_restaurante.crear("demo", "Bar Demo", raiz=TMP)
import idiomas, pedidos_online as po, servidor  # noqa: E402

CLAVE = "clave-de-prueba"
LUNES_13 = datetime.datetime(2026, 10, 26, 13, 0)   # lunes


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def ajustes(**k):
    a = {"domicilio": True, "recoger": True, "pausa": False, "dias": [0, 1, 2, 3, 4], "tramos": [["12:30", "16:00"], ["20:00", "23:30"]],
         "minimo": 10, "envio": 2.5, "cps": ["08001", "08002"], "preparacion": 30}
    a.update(k)
    return po.validar_ajustes(a)


def cuerpo(**k):
    c = {"tipo": "domicilio", "nombre": "Ana", "telefono": "600 123 456", "direccion": "Calle Mayor 1, 2.º", "cp": "08001",
         "hora": "asap", "pago": "efectivo", "cambio": "billete de 50"}
    c.update(k)
    return c


class Validacion(unittest.TestCase):
    def falla(self, clave, c, a=None, subtotal=20, ahora=LUNES_13):
        with self.assertRaises(idiomas.Msg) as e:
            po.validar_entrega(c, a or ajustes(), subtotal, ahora)
        self.assertEqual(e.exception.clave, clave)

    def test_domicilio_valido(self):
        r = po.validar_entrega(cuerpo(), ajustes(), 20, LUNES_13)
        self.assertEqual((r["tipo"], r["envio"], r["pago"], r["cambio"]), ("domicilio", 2.5, "efectivo", "billete de 50"))
        self.assertEqual(r["entrega"]["cp"], "08001")
        self.assertGreaterEqual(len(r["seguimiento"]), 30)

    def test_recoger_sin_direccion_ni_envio(self):
        r = po.validar_entrega(cuerpo(tipo="recoger", direccion=None, cp=None, pago="tarjeta"), ajustes(), 20, LUNES_13)
        self.assertEqual((r["envio"], r["cambio"]), (0.0, ""))
        self.assertNotIn("direccion", r["entrega"])

    def test_zona_por_codigo_postal(self):
        self.falla("srv.online.fuera_zona", cuerpo(cp="28001"))
        self.falla("srv.online.cp", cuerpo(cp="8001"))

    def test_horario(self):
        self.falla("srv.online.cerrado_ahora", cuerpo(), ahora=LUNES_13.replace(hour=18))
        self.falla("srv.online.cerrado_ahora", cuerpo(), ahora=LUNES_13 + datetime.timedelta(days=5))   # sábado: no está en dias
        self.falla("srv.online.fuera_horario", cuerpo(hora="17:30"))
        self.falla("srv.online.hora_pronto", cuerpo(hora="13:15"))
        self.falla("srv.online.hora", cuerpo(hora="25:00"))
        # programado: fuera de horario ahora pero a una hora válida, sí
        r = po.validar_entrega(cuerpo(hora="21:00"), ajustes(), 20, LUNES_13.replace(hour=18))
        self.assertEqual(r["hora"], "21:00")

    def test_minimo_tipo_pausa_pago(self):
        self.falla("srv.online.minimo", cuerpo(), subtotal=9.99)
        self.falla("srv.online.tipo", cuerpo(tipo="mesa"))
        self.falla("srv.online.tipo_inactivo", cuerpo(), a=ajustes(domicilio=False))
        self.falla("srv.online.pausa", cuerpo(), a=ajustes(pausa=True))
        self.falla("srv.online.pago", cuerpo(pago="bizum"))
        self.falla("srv.online.telefono", cuerpo(telefono="123"))
        self.falla("srv.online.nombre", cuerpo(nombre="  "))

    def test_ajustes(self):
        with self.assertRaises(idiomas.Msg) as e:
            ajustes(cps=[])
        self.assertEqual(e.exception.clave, "srv.online.sin_zona")
        for malo in ({"tramos": [["16:00", "12:00"]]}, {"minimo": -1}, {"preparacion": 2}, {"cps": ["ABCDE"]}, {"dias": [7]}):
            with self.assertRaises(idiomas.Msg):
                ajustes(**malo)
        self.assertEqual(ajustes(cps="08002, 08001 08001")["cps"], ["08001", "08002"])
        aparte = po.FICHERO + ".aparte"
        if os.path.exists(po.FICHERO):
            os.replace(po.FICHERO, aparte)
        try:
            self.assertFalse(po.leer_ajustes()["domicilio"] or po.leer_ajustes()["recoger"])   # sin fichero ni defecto: todo desactivado
        finally:
            if os.path.exists(aparte):
                os.replace(aparte, po.FICHERO)


class Estados(unittest.TestCase):
    def pedido(self, tipo="domicilio", estado="recibido", hora="asap"):
        return {"tipo": tipo, "estado": estado, "hora": hora, "creado": LUNES_13.timestamp(), "t": {}}

    def test_flujo_domicilio(self):
        p = self.pedido()
        with self.assertRaises(idiomas.Msg):
            po.cambiar_estado(p, "preparando", {}, LUNES_13)        # sin aceptar no pasa a cocina
        with self.assertRaises(idiomas.Msg):
            po.cambiar_estado(p, "aceptado", {}, LUNES_13)          # aceptar pide minutos
        po.cambiar_estado(p, "aceptado", {"minutos": 40}, LUNES_13)
        self.assertEqual(p["hora_estimada"], "13:40")
        for e in ("preparando", "listo"):
            po.cambiar_estado(p, e, {}, LUNES_13)
        with self.assertRaises(idiomas.Msg):
            po.cambiar_estado(p, "entregado", {}, LUNES_13)         # domicilio: antes, en reparto
        po.cambiar_estado(p, "en_reparto", {}, LUNES_13)
        po.cambiar_estado(p, "entregado", {}, LUNES_13)
        self.assertEqual(p["estado"], "entregado")

    def test_flujo_recoger_sin_reparto(self):
        p = self.pedido("recoger", "listo")
        with self.assertRaises(idiomas.Msg):
            po.cambiar_estado(p, "en_reparto", {}, LUNES_13)
        po.cambiar_estado(p, "entregado", {}, LUNES_13)

    def test_rechazo_y_cancelacion_con_motivo(self):
        p = self.pedido()
        with self.assertRaises(idiomas.Msg):
            po.cambiar_estado(p, "rechazado", {}, LUNES_13)
        po.cambiar_estado(p, "rechazado", {"motivo": "Fuera de zona hoy"}, LUNES_13)
        self.assertEqual(p["motivo"], "Fuera de zona hoy")
        self.assertEqual(po.siguientes(p), ())   # final
        q = self.pedido(estado="preparando")
        po.cambiar_estado(q, "cancelado", {"motivo": "Sin existencias"}, LUNES_13)
        with self.assertRaises(idiomas.Msg):
            po.cambiar_estado(q, "preparando", {}, LUNES_13)

    def test_programado_estima_a_la_hora_pedida(self):
        p = self.pedido(hora="21:00")
        po.cambiar_estado(p, "aceptado", {"minutos": 30}, LUNES_13)
        self.assertEqual(p["hora_estimada"], "21:00")


class Caducidad(unittest.TestCase):
    def pedido(self, hora="asap", estado="recibido"):
        return {"tipo": "recoger", "estado": estado, "hora": hora, "fecha": "2026-10-26", "creado": LUNES_13.timestamp(), "t": {"recibido": 0}}

    def test_programado_caduca_pasada_su_hora(self):
        p = self.pedido("21:00")
        self.assertEqual(po.caducar([p], LUNES_13.replace(hour=20, minute=59), 5), 0)
        self.assertEqual(po.caducar([p], LUNES_13.replace(hour=21, minute=1), 5), 1)
        self.assertEqual((p["estado"], p["motivo"]), ("cancelado", "sin aceptar"))

    def test_asap_caduca_al_acabar_el_dia_de_servicio(self):
        p, aceptado = self.pedido(), self.pedido(estado="aceptado")
        manana_4 = LUNES_13.replace(hour=4) + datetime.timedelta(days=1)
        self.assertEqual(po.caducar([p, aceptado], manana_4, 5), 0)
        self.assertEqual(po.caducar([p, aceptado], manana_4.replace(hour=5, minute=1), 5), 1)
        self.assertEqual((p["estado"], aceptado["estado"]), ("cancelado", "aceptado"))   # solo los que nadie aceptó

    def test_se_archiva_y_no_se_ve_en_sala(self):
        viejo = {**self.pedido(), "id": "viejo", "numero": 1, "fecha": "2026-01-05", "lineas": [], "total": 0,
                 "creado": datetime.datetime(2026, 1, 5, 13).timestamp()}
        servidor.guardar_pedidos([viejo])
        self.assertEqual(servidor.leer_pedidos(), [])
        with open(os.path.join(servidor.HISTORIAL, "pedidos-2026-01.jsonl"), encoding="utf-8") as f:
            archivado = [json.loads(l) for l in f if l.strip()]
        self.assertEqual([(x["id"], x["estado"], x["motivo"]) for x in archivado], [("viejo", "cancelado", "sin aceptar")])


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        servidor.guardar_clave(CLAVE)
        with open(po.FICHERO, "w") as f:
            json.dump(ajustes(dias=list(range(7)), tramos=[["00:00", "23:59"]], minimo=1, preparacion=5), f)
        d = servidor.leer_datos()
        cls.plato = d["platos"][0]
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
        datos = r.read()
        if r.getheader("Set-Cookie"):
            cls.cookie = r.getheader("Set-Cookie").split(";")[0]
        try:
            return r.status, json.loads(datos)
        except ValueError:
            return r.status, datos.decode()

    def nuevo(self, **k):
        servidor.envios.clear()
        st, r = self.http("POST", "/api/pedido/online", {**cuerpo(**{"cambio": "", **k}), "lineas": [{"pid": self.plato["id"]}, {"pid": self.plato["id"]}]}, auth=False)
        self.assertEqual(st, 200, r)
        return r

    def estado(self, pid, estado, **k):
        return self.http("POST", "/api/pedido/estado", {"id": pid, "estado": estado, **k})

    def test_recorrido_completo(self):
        r = self.nuevo()
        self.assertEqual(r["estado"], "recibido")
        t = r["seguimiento"]
        st, s = self.http("GET", "/api/seguir?t=" + t, auth=False)
        self.assertEqual(st, 200)
        self.assertEqual(s["importe_estimado"], round(2 * self.plato["p"] + 2.5, 2))
        self.assertNotIn("telefono", json.dumps(s))
        # la cocina no lo ve hasta aceptarlo; la sala sí
        _, coc = self.http("GET", "/api/pedidos")
        self.assertNotIn(r["id"], [p["id"] for p in coc["pedidos"]])
        _, sala = self.http("GET", "/api/pedidos?vista=sala")
        self.assertIn(r["id"], [p["id"] for p in sala["pedidos"]])
        self.assertNotIn("seguimiento", json.dumps(sala))
        self.assertEqual(self.estado(r["id"], "preparando")[0], 400)
        st, resp = self.estado(r["id"], "aceptado", minutos=25)
        self.assertEqual(st, 200)
        for secreto in ("entrega", "seguimiento", "token"):   # la respuesta no devuelve tokens ni datos de entrega
            self.assertNotIn(secreto, resp["pedido"])
        self.assertNotIn(r["seguimiento"], json.dumps(resp))
        _, coc = self.http("GET", "/api/pedidos")
        enc = [p for p in coc["pedidos"] if p["id"] == r["id"]]
        self.assertTrue(enc and "entrega" not in enc[0])
        for e in ("preparando", "listo", "en_reparto", "entregado"):
            self.assertEqual(self.estado(r["id"], e)[0], 200, e)
        _, s = self.http("GET", "/api/seguir?t=" + t, auth=False)
        self.assertEqual(s["estado"], "entregado")
        self.assertTrue(s["hora_estimada"])

    def test_seguimiento_no_adivinable(self):
        r = self.nuevo(tipo="recoger")
        for malo in ("", r["id"], str(r["numero"]), r["seguimiento"][:-1] + ("A" if r["seguimiento"][-1] != "A" else "B")):
            self.assertEqual(self.http("GET", "/api/seguir?t=" + malo, auth=False)[0], 404, malo)
        self.assertNotIn("seguimiento", self.http("GET", "/api/pedido?id=" + r["id"], auth=False)[1])

    def test_hoja_de_reparto_sin_importes(self):
        r = self.nuevo(pago="efectivo", cambio="billete de 50")
        self.assertEqual(self.http("GET", "/admin/reparto?id=" + r["id"], auth=False)[0], 401)
        st, h = self.http("GET", "/admin/reparto?id=" + r["id"])
        self.assertEqual(st, 200)
        self.assertIn("600 123 456", h)
        self.assertIn("Calle Mayor 1", h)
        self.assertIn("Cobrar con el ticket de caja", h)
        self.assertIn("billete de 50", h)
        self.assertNotIn("€", h)
        for importe in (r["total"], self.plato["p"], 2.5):
            for txt in (f"{importe:.2f}", f"{importe:.2f}".replace(".", ",")):
                self.assertNotIn(txt, h)
        self.assertIsNone(re.search(r"(?i)total|importe|cobrad|factura", h))

    def test_rechazo_visible_al_cliente_y_fuera_de_cocina(self):
        r = self.nuevo()
        self.assertEqual(self.estado(r["id"], "rechazado")[0], 400)   # sin motivo
        self.assertEqual(self.estado(r["id"], "rechazado", motivo="Hoy no repartimos")[0], 200)
        _, s = self.http("GET", "/api/seguir?t=" + r["seguimiento"], auth=False)
        self.assertEqual((s["estado"], s["motivo"]), ("rechazado", "Hoy no repartimos"))

    def test_validacion_y_limite_por_ip(self):
        servidor.envios.clear()
        st, e = self.http("POST", "/api/pedido/online", {**cuerpo(cp="28001"), "lineas": [{"pid": self.plato["id"]}]}, auth=False)
        self.assertEqual(st, 400)
        self.assertIn("28001", e["error"])
        for _ in range(servidor.MAX_PEDIDOS_IP):
            servidor.envios.setdefault("127.0.0.1", []).append(datetime.datetime.now().timestamp())
        st, _ = self.http("POST", "/api/pedido/online", {**cuerpo(), "lineas": [{"pid": self.plato["id"]}]}, auth=False)
        self.assertEqual(st, 429)
        servidor.envios.clear()

    def test_ajustes_protegidos(self):
        self.assertEqual(self.http("POST", "/api/online/ajustes", ajustes(), auth=False)[0], 401)
        st, r = self.http("POST", "/api/online/ajustes", {**ajustes(dias=list(range(7)), tramos=[["00:00", "23:59"]], minimo=1, preparacion=5), "cps": "08001,08002"})
        self.assertEqual((st, r["ajustes"]["cps"]), (200, ["08001", "08002"]))
        st, pub = self.http("GET", "/api/online", auth=False)
        self.assertTrue(pub["disponible"])
        self.assertNotIn("telefono", pub)

    def test_mesa_sigue_igual(self):
        servidor.envios.clear()
        st, r = self.http("POST", "/api/pedido", {"mesa": 3, "lineas": [{"pid": self.plato["id"]}]}, auth=False)
        self.assertEqual((st, r["estado"]), (200, "nuevo"))
        self.assertEqual(self.estado(r["id"], "entregado")[0], 200)   # mesa conserva su flujo libre


if __name__ == "__main__":
    unittest.main()

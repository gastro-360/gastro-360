# SPDX-License-Identifier: EUPL-1.2
"""Reservas con aforo por tramos:  python3 -m unittest tests.test_reservas -v
Usa una carpeta temporal (CARTA_RESTAURANTES): no toca restaurantes/."""
import datetime, http.client, json, os, re, shutil, sys, tempfile, threading, unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reservas-")
os.environ.update(CARTA_RESTAURANTES=TMP, RESTAURANTE="demo")
sys.path.insert(0, os.path.join(RAIZ, "carta"))
import nuevo_restaurante  # noqa: E402

nuevo_restaurante.crear("demo", "Bar Demo", raiz=TMP)
import idiomas, reservas as rs, servidor  # noqa: E402

CLAVE = "clave-de-prueba"
LUNES_10 = datetime.datetime(2026, 10, 26, 10, 0)   # lunes
LUNES = "2026-10-26"


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def ajustes(**k):
    a = {"activo": True, "modo": "automatico", "tramo": 30, "aforo": 10, "max_reserva": 8,
         "horario": [[["13:00", "15:30"], ["20:00", "22:30"]]] * 6 + [[]], "cerrados": ["2026-12-25"],
         "antelacion_min": 60, "antelacion_max": 30, "no_presentada": 20}
    a.update(k)
    return rs.validar_ajustes(a)


def cuerpo(**k):
    c = {"fecha": LUNES, "hora": "13:30", "comensales": 4, "nombre": "Ana", "telefono": "600 123 456", "email": "", "nota": ""}
    c.update(k)
    return c


class Modelo(unittest.TestCase):
    def falla(self, clave, c, a=None, lista=(), ahora=LUNES_10):
        with self.assertRaises(idiomas.Msg) as e:
            rs.validar(c, a or ajustes(), list(lista), ahora)
        self.assertEqual(e.exception.clave, clave)

    def test_tramos(self):
        a = ajustes()
        self.assertEqual(rs.tramos_del_dia(a, datetime.date(2026, 10, 26))[:6], ["13:00", "13:30", "14:00", "14:30", "15:00", "20:00"])
        self.assertEqual(rs.tramos_del_dia(a, datetime.date(2026, 11, 1)), [])    # domingo: sin horario
        self.assertEqual(rs.tramos_del_dia(a, datetime.date(2026, 12, 25)), [])   # día cerrado
        self.assertEqual(len(rs.tramos_del_dia(ajustes(tramo=60), datetime.date(2026, 10, 26))), 6)

    def test_modo_automatico_confirma(self):
        r = rs.validar(cuerpo(), ajustes(), [], LUNES_10)
        self.assertEqual(r["estado"], "confirmada")
        self.assertGreaterEqual(len(r["token"]), 30)

    def test_modo_manual_solicita(self):
        self.assertEqual(rs.validar(cuerpo(), ajustes(modo="manual"), [], LUNES_10)["estado"], "solicitada")

    def test_aforo_lleno(self):
        a, lista = ajustes(), []
        lista.append(rs.validar(cuerpo(comensales=6), a, lista, LUNES_10))
        lista.append(rs.validar(cuerpo(comensales=4), a, lista, LUNES_10))   # 10 de 10
        self.falla("srv.reservas.lleno", cuerpo(comensales=1), lista=lista)
        self.assertEqual(rs.validar(cuerpo(hora="14:00", comensales=8), a, lista, LUNES_10)["hora"], "14:00")   # otro tramo, sí
        libres = {t["hora"]: t["libres"] for t in rs.libres_del_dia(a, lista, datetime.date(2026, 10, 26), LUNES_10)}
        self.assertEqual(libres["13:30"], 0)
        lista[0]["estado"] = "cancelada"   # una cancelada libera su sitio
        self.assertEqual(rs.validar(cuerpo(comensales=6), a, lista, LUNES_10)["comensales"], 6)

    def test_validaciones(self):
        self.falla("srv.reservas.inactivo", cuerpo(), a=ajustes(activo=False))
        self.falla("srv.reservas.cerrado", cuerpo(hora="17:00"))
        self.falla("srv.reservas.cerrado", cuerpo(fecha="2026-11-01"))
        self.falla("srv.reservas.pronto", cuerpo(hora="13:00"), ahora=LUNES_10.replace(hour=12, minute=30))
        self.falla("srv.reservas.fecha_fuera", cuerpo(fecha="2026-12-30"))
        self.falla("srv.reservas.fecha_fuera", cuerpo(fecha="2026-10-25"))
        self.falla("srv.reservas.comensales", cuerpo(comensales=9))
        self.falla("srv.reservas.comensales", cuerpo(comensales=0))
        self.falla("srv.online.telefono", cuerpo(telefono="12"))
        self.falla("srv.reservas.email", cuerpo(email="no-es-correo"))
        self.falla("srv.reservas.fecha", cuerpo(fecha="mañana"))

    def test_ajustes_malos(self):
        for malo in ({"modo": "a-veces"}, {"tramo": 7}, {"aforo": 0}, {"horario": [[]] * 6}, {"horario": [[["15:00", "13:00"]]] * 7},
                     {"cerrados": ["25/12/2026"]}, {"no_presentada": 1}):
            with self.assertRaises(idiomas.Msg, msg=malo):
                ajustes(**malo)
        self.assertEqual(ajustes(cerrados="2026-12-31, 2026-12-25")["cerrados"], ["2026-12-25", "2026-12-31"])
        self.assertFalse(rs.APAGADO["activo"])   # sin ajustes ni defecto: desactivado

    def test_caducidad_de_solicitadas(self):
        a = ajustes(modo="manual")
        r = rs.validar(cuerpo(), a, [], LUNES_10)
        lista = [r]
        self.assertEqual(rs.caducar(lista, LUNES_10.replace(hour=13, minute=29), a), 0)
        self.assertEqual(rs.caducar(lista, LUNES_10.replace(hour=13, minute=30), a), 1)
        self.assertEqual((r["estado"], r["motivo"]), ("rechazada", rs.MOTIVO_SIN_RESPUESTA))

    def test_no_presentada(self):
        a = ajustes(no_presentada=20)
        r = rs.validar(cuerpo(), a, [], LUNES_10)
        lista = [r]
        self.assertEqual(rs.caducar(lista, LUNES_10.replace(hour=13, minute=49), a), 0)
        self.assertEqual(r["estado"], "confirmada")
        self.assertEqual(rs.caducar(lista, LUNES_10.replace(hour=13, minute=50), a), 1)
        self.assertEqual(r["estado"], "no_presentada")
        # sentada antes de tiempo: no se toca
        s = rs.validar(cuerpo(hora="14:00"), a, [], LUNES_10)
        rs.cambiar_estado(s, "sentada", {"mesa": "5"}, [s], a, LUNES_10.replace(hour=14))
        rs.caducar([s], LUNES_10.replace(hour=18), a)
        self.assertEqual((s["estado"], s["mesa"]), ("sentada", "5"))

    def test_deshacer_no_presentada_comprueba_aforo(self):
        """Deshacer «no presentada» vuelve a ocupar aforo: si el tramo ya se llenó, error claro; y no antes de la hora."""
        a = ajustes(aforo=10)
        r = rs.validar(cuerpo(comensales=8), a, [], LUNES_10)
        with self.assertRaises(idiomas.Msg) as e:   # antes de su hora no se puede marcar no presentada
            rs.cambiar_estado(r, "no_presentada", {}, [r], a, LUNES_10.replace(hour=13, minute=29))
        self.assertEqual(e.exception.clave, "srv.reservas.antes_de_hora")
        self.assertNotIn("no_presentada", rs.siguientes(r, a, LUNES_10.replace(hour=13, minute=29)))
        self.assertIn("no_presentada", rs.siguientes(r, a, LUNES_10.replace(hour=13, minute=30)))
        rs.cambiar_estado(r, "no_presentada", {}, [r], a, LUNES_10.replace(hour=13, minute=35))
        otra = rs.validar(cuerpo(comensales=8), a, [r], LUNES_10)   # el hueco liberado se vuelve a reservar
        lista = [r, otra]
        for destino in ("sentada", "confirmada"):
            with self.assertRaises(idiomas.Msg) as e:
                rs.cambiar_estado(r, destino, {}, lista, a, LUNES_10.replace(hour=13, minute=40))
            self.assertEqual(e.exception.clave, "srv.reservas.sin_aforo")
            self.assertEqual(r["estado"], "no_presentada")
        self.assertEqual(rs.ocupados(lista, LUNES, "13:30"), 8)   # no pasa de 8 a 16
        otra["estado"] = "cancelada"
        rs.cambiar_estado(r, "sentada", {}, lista, a, LUNES_10.replace(hour=13, minute=40))   # ahora sí cabe
        self.assertEqual(r["estado"], "sentada")

    def test_no_vuelve_a_confirmada_pasada_la_cortesia(self):
        """Pasada la hora + cortesía, volver a «confirmada» no se ofrece ni se acepta (caducar lo revertiría): vale «sentada»."""
        a = ajustes(no_presentada=20)
        for origen in ("sentada", "no_presentada"):
            r = rs.validar(cuerpo(comensales=2), a, [], LUNES_10)
            rs.cambiar_estado(r, origen, {}, [r], a, LUNES_10.replace(hour=13, minute=35))
            antes = LUNES_10.replace(hour=13, minute=49)
            self.assertIn("confirmada", rs.siguientes(r, a, antes))
            self.assertIn("confirmada", rs.para_sala(r, a, antes)["acciones"])
            tarde = LUNES_10.replace(hour=13, minute=50)
            self.assertNotIn("confirmada", rs.siguientes(r, a, tarde))
            self.assertNotIn("confirmada", rs.para_sala(r, a, tarde)["acciones"])
            with self.assertRaises(idiomas.Msg) as e:
                rs.cambiar_estado(r, "confirmada", {}, [r], a, tarde)
            self.assertEqual((e.exception.clave, r["estado"]), ("srv.reservas.tarde", origen))
            if origen == "no_presentada":
                self.assertIn("sentada", rs.para_sala(r, a, tarde)["acciones"])
                rs.cambiar_estado(r, "sentada", {"mesa": "3"}, [r], a, tarde)
                rs.caducar([r], tarde.replace(hour=18), a)
                self.assertEqual(r["estado"], "sentada")
        # dentro de la cortesía sí se puede deshacer, y caducar luego la trata como cualquier confirmada
        r = rs.validar(cuerpo(comensales=2), a, [], LUNES_10)
        rs.cambiar_estado(r, "sentada", {}, [r], a, LUNES_10.replace(hour=13, minute=35))
        rs.cambiar_estado(r, "confirmada", {}, [r], a, LUNES_10.replace(hour=13, minute=40))
        self.assertEqual(r["estado"], "confirmada")

    def test_transiciones(self):
        a = ajustes(modo="manual")
        r = rs.validar(cuerpo(), a, [], LUNES_10)
        with self.assertRaises(idiomas.Msg):
            rs.cambiar_estado(r, "sentada", {}, [r], a, LUNES_10)   # una solicitada no se sienta sin aceptar
        with self.assertRaises(idiomas.Msg):
            rs.cambiar_estado(r, "rechazada", {}, [r], a, LUNES_10)   # sin motivo
        rs.cambiar_estado(r, "confirmada", {}, [r], a, LUNES_10)
        rs.cambiar_estado(r, "cancelada", {"motivo": "Cerramos por avería"}, [r], a, LUNES_10)
        self.assertEqual(rs.para_cliente(r, LUNES_10)["motivo"], "Cerramos por avería")
        self.assertNotIn("telefono", rs.para_cliente(r, LUNES_10))


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        servidor.guardar_clave(CLAVE)
        cls.manana = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        with open(rs.FICHERO, "w") as f:
            json.dump(ajustes(horario=[[["00:00", "23:59"]]] * 7, cerrados=[], antelacion_min=0, aforo=6), f)
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

    def reservar(self, hora, **k):
        servidor.envios_reservas.clear()
        return self.http("POST", "/api/reservar", cuerpo(fecha=self.manana, hora=hora, **k), auth=False)

    def sala(self):
        st, d = self.http("GET", "/api/reservas?fecha=" + self.manana)
        self.assertEqual(st, 200)
        return d

    def test_recorrido_y_aforo_lleno(self):
        st, r = self.reservar("12:00", comensales=4)
        self.assertEqual((st, r["estado"]), (200, "confirmada"))
        st, e = self.reservar("12:00", comensales=3)   # 4 + 3 > 6
        self.assertEqual(st, 400)
        self.assertIn("completa", e["error"])
        st, pub = self.http("GET", "/api/reservar?fecha=" + self.manana, auth=False)
        self.assertEqual({t["hora"]: t["libres"] for t in pub["tramos"]}["12:00"], 2)
        d = self.sala()
        self.assertNotIn("token", json.dumps(d["reservas"]))
        self.assertEqual({t["hora"]: t["ocupados"] for t in d["tramos"]}["12:00"], 4)
        rid = next(x["id"] for x in d["reservas"] if x["hora"] == "12:00")
        st, resp = self.http("POST", "/api/reserva/estado", {"id": rid, "estado": "sentada", "mesa": "7"})
        self.assertEqual((st, resp["reserva"]["estado"], resp["reserva"]["mesa"]), (200, "sentada", "7"))
        self.assertNotIn("token", resp["reserva"])
        st, c = self.http("GET", "/api/reserva?t=" + r["token"], auth=False)
        self.assertEqual((st, c["estado"], c["cancelable"]), (200, "sentada", False))
        self.assertNotIn("600", json.dumps(c))   # sin teléfono

    def test_modo_manual_aceptar_y_rechazar(self):
        self.http("POST", "/api/reservas/ajustes", {**ajustes(horario=[[["00:00", "23:59"]]] * 7, cerrados=[], antelacion_min=0, aforo=6), "modo": "manual"})
        try:
            st, r1 = self.reservar("13:00", comensales=2)
            st, r2 = self.reservar("13:30", comensales=2)
            self.assertEqual((r1["estado"], r2["estado"]), ("solicitada", "solicitada"))
            ids = {x["hora"]: x["id"] for x in self.sala()["reservas"]}
            self.assertEqual(self.http("POST", "/api/reserva/estado", {"id": ids["13:00"], "estado": "confirmada"})[0], 200)
            self.assertEqual(self.http("POST", "/api/reserva/estado", {"id": ids["13:30"], "estado": "rechazada"})[0], 400)   # sin motivo
            self.assertEqual(self.http("POST", "/api/reserva/estado", {"id": ids["13:30"], "estado": "rechazada", "motivo": "Grupo privado"})[0], 200)
            self.assertEqual(self.http("GET", "/api/reserva?t=" + r1["token"], auth=False)[1]["estado"], "confirmada")
            c = self.http("GET", "/api/reserva?t=" + r2["token"], auth=False)[1]
            self.assertEqual((c["estado"], c["motivo"]), ("rechazada", "Grupo privado"))
        finally:
            self.http("POST", "/api/reservas/ajustes", ajustes(horario=[[["00:00", "23:59"]]] * 7, cerrados=[], antelacion_min=0, aforo=6))

    def test_cancelacion_con_token(self):
        st, r = self.reservar("15:00", comensales=2)
        self.assertEqual(st, 200)
        for malo in ("", "corto", r["token"][:-1] + ("A" if r["token"][-1] != "A" else "B")):
            self.assertEqual(self.http("POST", "/api/reserva/cancelar", {"t": malo}, auth=False)[0], 404, malo)
            self.assertEqual(self.http("GET", "/api/reserva?t=" + malo, auth=False)[0], 404, malo)
        rid = next(x["id"] for x in self.sala()["reservas"] if x["hora"] == "15:00")
        self.assertEqual(self.http("GET", "/api/reserva?t=" + rid, auth=False)[0], 404)   # el id no sirve de enlace
        st, c = self.http("POST", "/api/reserva/cancelar", {"t": r["token"]}, auth=False)
        self.assertEqual((st, c["estado"], c["cancelable"]), (200, "cancelada", False))
        self.assertEqual(self.http("POST", "/api/reserva/cancelar", {"t": r["token"]}, auth=False)[0], 400)   # ya cancelada
        self.assertEqual({t["hora"]: t["ocupados"] for t in self.sala()["tramos"]}["15:00"], 0)

    def test_sala_sin_sesion_401(self):
        for metodo, ruta, c in (("GET", "/api/reservas", None), ("GET", "/api/reservas/ajustes", None),
                                ("POST", "/api/reserva/estado", {"id": "x", "estado": "sentada"}), ("POST", "/api/reservas/ajustes", ajustes())):
            self.assertEqual(self.http(metodo, ruta, c, auth=False)[0], 401, ruta)

    def test_limite_por_ip(self):
        servidor.envios.clear(); servidor.envios_reservas.clear()
        for _ in range(servidor.MAX_RESERVAS_IP):
            servidor.envios_reservas.setdefault("127.0.0.1", []).append(datetime.datetime.now().timestamp())
        st, e = self.http("POST", "/api/reservar", cuerpo(fecha=self.manana, hora="16:00"), auth=False)
        self.assertEqual(st, 429)
        self.assertIn("reservas", e["error"])
        self.assertEqual(servidor.envios.get("127.0.0.1", []), [])   # no toca el cupo de los pedidos
        servidor.envios_reservas.clear()

    def test_cupos_separados_pedidos_y_reservas(self):
        """Gastar el cupo de pedidos no impide reservar, y reservar no gasta el cupo de pedidos."""
        servidor.envios.clear(); servidor.envios_reservas.clear()
        for _ in range(servidor.MAX_PEDIDOS_IP):
            servidor.envios.setdefault("127.0.0.1", []).append(datetime.datetime.now().timestamp())
        st, _ = self.http("POST", "/api/reservar", cuerpo(fecha=self.manana, hora="16:30", comensales=1), auth=False)
        self.assertEqual(st, 200)
        self.assertEqual(len(servidor.envios["127.0.0.1"]), servidor.MAX_PEDIDOS_IP)
        self.assertEqual(len(servidor.envios_reservas["127.0.0.1"]), 1)
        servidor.envios.clear(); servidor.envios_reservas.clear()

    def test_xss_escapado(self):
        malo = '<img src=x onerror=alert(1)>'
        st, r = self.reservar("18:00", comensales=1, nombre=malo, nota=malo)
        self.assertEqual(st, 200)
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1])
        c.request("GET", "/api/reserva?t=" + r["token"])
        resp = c.getresponse()
        self.assertTrue(resp.getheader("Content-Type").startswith("application/json"))
        self.assertEqual(json.loads(resp.read())["nombre"], malo)   # el dato llega tal cual, como JSON; lo pinta esc()
        # las páginas pintan los datos del cliente siempre con esc()
        for pagina, campos in (("reserva.html", ("R.nombre", "R.hora", "R.comensales")),
                               ("admin.html", ("r.nombre", "r.telefono", "r.email", "r.hora", "r.id"))):
            with open(os.path.join(RAIZ, "carta", pagina), encoding="utf-8") as f:
                html = f.read()
            for campo in campos:
                usos = re.findall(r"\$\{([^{}]*\b" + re.escape(campo) + r"\b[^{}]*)\}", html)
                self.assertTrue(usos, campo)
                for u in usos:
                    self.assertIn("esc(", u, f"{pagina}: {campo} sin escapar en ${{{u}}}")
        # nota y motivo también
        with open(os.path.join(RAIZ, "carta", "admin.html"), encoding="utf-8") as f:
            self.assertIn("esc(r.nota", f.read())

    def test_paginas_y_desactivado(self):
        for ruta in ("/reservar", "/reserva?t=x"):
            st, h = self.http("GET", ruta, auth=False)
            self.assertEqual(st, 200)
            self.assertIn("reserv", h)
        aparte = rs.FICHERO + ".aparte"
        os.replace(rs.FICHERO, aparte)
        try:
            self.assertFalse(self.http("GET", "/api/reservar", auth=False)[1]["activo"])   # sin ajustes ni defecto: apagado
            self.assertEqual(self.reservar("19:00")[0], 400)
        finally:
            os.replace(aparte, rs.FICHERO)


if __name__ == "__main__":
    unittest.main()

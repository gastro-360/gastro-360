# SPDX-License-Identifier: EUPL-1.2
"""Vigilante contra un /salud y un Telegram simulados:  python -m unittest tests.test_vigilante -v"""
import json, os, sys, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "carta"))
sys.path.insert(0, os.path.join(RAIZ, "tests"))
import telegram_mock, vigilante  # noqa: E402


def servir(handler):
    s = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


ESTADO = {"codigo": 200}


class Salud(BaseHTTPRequestHandler):
    def do_GET(self):
        c = ESTADO["codigo"]
        d = json.dumps({"ok": c == 200, "problemas": [] if c == 200 else ["datos.json ilegible"]}).encode()
        self.send_response(c)
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def log_message(self, *a):
        pass


class Reloj:
    t = 1000.0

    def __call__(self):
        return self.t


class TestVigilante(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.salud, cls.tg = servir(Salud), servir(telegram_mock.H)
        cls.url = f"http://127.0.0.1:{cls.salud.server_port}/salud"
        cls.api = f"http://127.0.0.1:{cls.tg.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.salud.shutdown(); cls.tg.shutdown()

    def setUp(self):
        ESTADO["codigo"] = 200
        telegram_mock.MENSAJES.clear()
        self.reloj = Reloj()
        self.v = vigilante.Vigilante(self.url, vigilante.Telegram("TOKEN123", "42", self.api), "Demo", fallos=3, reloj=self.reloj)

    def textos(self):
        return [m["text"] for m in telegram_mock.MENSAJES]

    def test_sano_no_avisa(self):
        for _ in range(5):
            self.assertTrue(self.v.paso())
        self.assertEqual(self.textos(), [])

    def test_caida_avisa_una_vez_y_recuperacion_otra(self):
        ESTADO["codigo"] = 503
        self.v.paso(); self.v.paso()
        self.assertEqual(self.textos(), [], "no avisa antes de N fallos seguidos")
        self.v.paso(); self.v.paso(); self.v.paso()
        self.assertEqual(len(self.textos()), 1, "avisa de la caída una sola vez")
        self.assertIn("CAÍDA", self.textos()[0])
        self.assertIn("datos.json ilegible", self.textos()[0])
        self.assertEqual(telegram_mock.MENSAJES[0]["chat_id"], "42")
        self.assertEqual(telegram_mock.MENSAJES[0]["token"], "TOKEN123")
        ESTADO["codigo"] = 200
        self.reloj.t += 125
        self.v.paso()
        self.assertEqual(len(self.textos()), 2)
        self.assertIn("recuperada", self.textos()[1])
        self.assertIn("2 min", self.textos()[1])
        self.v.paso()
        self.assertEqual(len(self.textos()), 2, "no repite la recuperación")

    def test_fallo_suelto_no_avisa(self):
        ESTADO["codigo"] = 503
        self.v.paso(); self.v.paso()
        ESTADO["codigo"] = 200
        self.v.paso()
        ESTADO["codigo"] = 503
        self.v.paso(); self.v.paso()
        self.assertEqual(self.textos(), [])

    def test_sin_respuesta_cuenta_como_caida(self):
        v = vigilante.Vigilante("http://127.0.0.1:1/salud", vigilante.Telegram("T", "1", self.api), "Demo", fallos=1)
        v.paso()
        self.assertEqual(len(self.textos()), 1)
        self.assertIn("sin respuesta", self.textos()[0])

    def test_telegram_caido_reintenta(self):
        v = vigilante.Vigilante(self.url, vigilante.Telegram("T", "1", "http://127.0.0.1:1"), "Demo", fallos=1)
        ESTADO["codigo"] = 503
        v.paso()
        self.assertFalse(v.aviso_caida)
        v.tg.api = self.api
        v.paso()
        self.assertTrue(v.aviso_caida)
        self.assertEqual(len(self.textos()), 1)

    def test_sin_configurar_no_revienta(self):
        v = vigilante.Vigilante(self.url, vigilante.Telegram("", ""), "Demo", fallos=1)
        ESTADO["codigo"] = 503
        v.paso(); v.paso()
        ESTADO["codigo"] = 200
        v.paso()
        self.assertEqual(self.textos(), [])

    def test_desde_entorno(self):
        os.environ.update(TELEGRAM_BOT_TOKEN="a", TELEGRAM_CHAT_ID="b", TELEGRAM_API_URL=self.api, VIGILANTE_FALLOS="2", VIGILANTE_INTERVALO="7")
        try:
            v, intervalo = vigilante.desde_entorno()
        finally:
            for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_API_URL", "VIGILANTE_FALLOS", "VIGILANTE_INTERVALO"):
                os.environ.pop(k)
        self.assertEqual((v.fallos, intervalo, v.tg.configurado, v.tg.api), (2, 7.0, True, self.api))


if __name__ == "__main__":
    unittest.main()

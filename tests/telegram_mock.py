# SPDX-License-Identifier: EUPL-1.2
"""Simulador de la API de Telegram para pruebas: guarda cada sendMessage y los devuelve en GET /mensajes.
  python tests/telegram_mock.py [puerto]   (por defecto 9000)"""
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MENSAJES = []


class H(BaseHTTPRequestHandler):
    def _json(self, codigo, obj):
        d = json.dumps(obj).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def do_POST(self):
        cuerpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path.startswith("/bot") and self.path.endswith("/sendMessage"):
            MENSAJES.append({"token": self.path[4:].split("/")[0], "chat_id": cuerpo.get("chat_id"), "text": cuerpo.get("text")})
            print("mensaje:", cuerpo.get("text"), flush=True)
            return self._json(200, {"ok": True, "result": {"message_id": len(MENSAJES)}})
        self._json(404, {"ok": False})

    def do_GET(self):
        if self.path == "/mensajes":
            return self._json(200, MENSAJES)
        self._json(404, {"ok": False})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1]) if len(sys.argv) > 1 else 9000), H).serve_forever()

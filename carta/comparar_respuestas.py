# SPDX-License-Identifier: EUPL-1.2
"""Huella de lo que sirve el servidor, para comprobar que un cambio de código no altera la carta.

  python comparar_respuestas.py PUERTO SALIDA.json     guarda la huella (sha256) de cada ruta
  python comparar_respuestas.py --comparar A.json B.json   dice si dos huellas coinciden
"""
import hashlib, json, os, sys, urllib.request, urllib.error

import restaurante

RUTAS = ["/", "/admin", "/cocina", "/datos.js", "/fotos.js", "/sw.js", "/manifest.webmanifest", "/_headers",
         f"/img/{restaurante.marca()['logo']}", "/img/icon-192.png", "/img/icon-512.png", "/img/icon-maskable-512.png",
         "/img/apple-touch-icon.png", "/img/referencia_capa.jpg", *sorted(f"/fotos/{f}" for f in os.listdir(os.path.join(restaurante.DIR, "fotos")))[:2],
         "/api/sesion", "/api/datos", "/api/pedidos"]


def huella(puerto):
    salida = {}
    for r in RUTAS:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{puerto}{r}", timeout=10) as resp:
                cuerpo = resp.read()
                salida[r] = [resp.status, resp.headers.get("Content-Type"), len(cuerpo), hashlib.sha256(cuerpo).hexdigest()]
        except urllib.error.HTTPError as e:
            salida[r] = [e.code, e.headers.get("Content-Type"), 0, ""]
    return salida


if __name__ == "__main__":
    if sys.argv[1] == "--comparar":
        a, b = (json.load(open(f)) for f in sys.argv[2:4])
        difs = [r for r in sorted(set(a) | set(b)) if a.get(r) != b.get(r)]
        for r in difs:
            print("DISTINTO", r, a.get(r), b.get(r))
        print(f"{len(a) - len(difs)} de {len(a)} rutas idénticas" + ("" if not difs else f"; {len(difs)} distintas"))
        sys.exit(1 if difs else 0)
    json.dump(huella(int(sys.argv[1])), open(sys.argv[2], "w"), indent=1)
    print("huella guardada en", sys.argv[2])

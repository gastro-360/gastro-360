# SPDX-License-Identifier: EUPL-1.2
"""Botón de reseña de Google:  python -m unittest tests.test_resena -v   (desde la raíz del repo; necesita Pillow y node)

Se genera la carta de un restaurante temporal y se ejecuta de verdad el JavaScript que pinta cada pedido (htmlEnviado)."""
import json, os, re, shutil, subprocess, sys, tempfile, unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARTA = os.path.join(RAIZ, "carta")
sys.path.insert(0, CARTA)
import nuevo_restaurante  # noqa: E402

try:
    import PIL  # noqa: F401
    HAY_PIL = True
except ImportError:
    HAY_PIL = False

ESTADOS = ["nuevo", "preparando", "listo", "entregado"]
URL = "https://search.google.com/local/writereview?placeid=ChIJ_pruebaPlaceId123"


def carta(marca_extra):
    """Genera index.html de un restaurante temporal con esos campos extra en marca.json y devuelve su texto."""
    tmp = tempfile.mkdtemp()
    try:
        nuevo_restaurante.crear("bar-prueba", "Bar Prueba", raiz=tmp)
        ruta = os.path.join(tmp, "bar-prueba", "marca.json")
        with open(ruta, encoding="utf-8") as f:
            m = json.load(f)
        m.update(marca_extra)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(m, f)
        web = os.path.join(tmp, "web")
        env = {**os.environ, "RESTAURANTE": "bar-prueba", "CARTA_RESTAURANTES": tmp, "CARTA_WEB": web}
        subprocess.run([sys.executable, "preparar_netlify.py"], cwd=CARTA, env=env, check=True, capture_output=True)
        with open(os.path.join(web, "index.html"), encoding="utf-8") as f:
            return f.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def pinta(html, pedidos):
    """Ejecuta htmlEnviado de la página con node para cada pedido y devuelve el HTML de cada uno."""
    trozo = re.search(r"/\*RESENA-INI\*/(.*?)/\*RESENA-FIN\*/", html, re.S).group(1)
    estados = re.search(r"const ESTADO=.*?\n.*?\n", html).group(0)
    # la página usa I18N (carta/idiomas.js, que necesita navegador): aquí un sustituto mínimo con el diccionario castellano real
    with open(os.path.join(RAIZ, "carta", "i18n", "es.json"), encoding="utf-8") as f:
        es = json.dumps(json.load(f))
    i18n = ("const D=" + es + ";const I18N={t:(k,p={})=>(D[k]||k).replace(/\\{(\\w+)\\}/g,(_,x)=>p[x]),"
            "th:(k,p)=>I18N.t(k,p),tn:(k,n,p={})=>I18N.t(k+(n===1?'.uno':'.otros'),{...p,n})};")
    js = ("const eur={format:v=>v+' €'};" + i18n + estados + trozo +
          "console.log(JSON.stringify(" + json.dumps(pedidos) + ".map(htmlEnviado)))")
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def pedido(i, estado):
    return {"id": f"p{i}", "numero": i, "mesa": 3 + i, "estado": estado, "total": 7.5 * i, "n": i}


@unittest.skipUnless(HAY_PIL and shutil.which("node"), "hacen falta Pillow y node")
class BotonResena(unittest.TestCase):
    def test_aparece_igual_en_todos_los_servidos_y_no_antes(self):
        html = carta({"google_place_id": "ChIJ_pruebaPlaceId123"})
        pedidos = [pedido(i + 1, e) for i, e in enumerate(ESTADOS * 3)]
        salida = pinta(html, pedidos)
        botones = []
        for p, h in zip(pedidos, salida):
            if p["estado"] == "entregado":
                self.assertEqual(len(re.findall(r'<a class="resena"', h)), 1, h)
                botones.append(re.search(r'<a class="resena"[^>]*>[^<]*</a>', h).group(0))
            else:
                self.assertNotIn("resena", h, f"no debe aparecer en «{p['estado']}»")
                self.assertNotIn("<a ", h)
        self.assertEqual(len(botones), 3)
        self.assertEqual(len(set(botones)), 1, "mismo botón y mismo enlace para todos los pedidos servidos")
        self.assertIn(f'href="{URL}"', botones[0])
        self.assertIn('rel="noopener noreferrer"', botones[0])

    def test_enlace_directo_manda_sobre_el_place_id(self):
        html = carta({"resena_url": "https://g.page/r/ejemplo/review", "google_place_id": "ChIJ_pruebaPlaceId123"})
        self.assertIn('href="https://g.page/r/ejemplo/review"', pinta(html, [pedido(1, "entregado")])[0])

    def test_sin_enlace_configurado_no_hay_boton(self):
        html = carta({})
        for h in pinta(html, [pedido(i + 1, e) for i, e in enumerate(ESTADOS)]):
            self.assertNotIn("resena", h)

    def test_no_depende_del_pedido(self):
        # El botón no mira importe, nota ni nada del cliente: dos pedidos servidos muy distintos dan el mismo botón.
        html = carta({"google_place_id": "ChIJ_pruebaPlaceId123"})
        a, b = pinta(html, [pedido(1, "entregado"), {**pedido(9, "entregado"), "total": 0.5, "n": 40, "demo": True}])
        self.assertEqual(re.search(r'<a class="resena".*?</a>', a).group(0), re.search(r'<a class="resena".*?</a>', b).group(0))

    def test_marca_no_valida(self):
        import restaurante
        tmp = tempfile.mkdtemp()
        try:
            for extra in ({"resena_url": "http://inseguro.es"}, {"resena_url": 'https://x.es/"onclick="'},
                          {"google_place_id": "corto"}, {"google_place_id": "ChIJ<script>aaaaaaaa"}):
                with open(os.path.join(tmp, "marca.json"), "w", encoding="utf-8") as f:
                    json.dump({"nombre": "Bar", "logo": "l.png", **extra}, f)
                with self.assertRaises(ValueError, msg=extra):
                    restaurante.cargar_marca(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

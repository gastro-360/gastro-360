# SPDX-License-Identifier: EUPL-1.2
"""CSP y recursos de terceros:  python -m unittest discover -s tests -p test_seguridad.py"""
import glob, os, re, sys, unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "carta"))
import seguridad  # noqa: E402


class Csp(unittest.TestCase):
    def test_script_en_linea_por_huella_y_sin_eval(self):
        c = seguridad.csp("<script>alert(1)</script><script src='/a.js'></script>")
        self.assertEqual(len(seguridad.huellas_scripts("<script>alert(1)</script><script src='/a.js'></script>")), 1)
        self.assertIn("default-src 'self'", c)
        self.assertIn("connect-src 'self'", c)
        self.assertNotIn("unsafe-eval", c)
        self.assertNotIn("'unsafe-inline'", c.split("script-src")[1].split(";")[0])

    def test_sin_scripts_solo_self(self):
        self.assertIn("script-src 'self';", seguridad.csp(""))


class SinTerceros(unittest.TestCase):
    def test_las_paginas_no_cargan_nada_de_fuera(self):
        patron = re.compile(r"""(<script[^>]+src=|<link[^>]+href=|<iframe[^>]+src=|<img[^>]+src=|@import\s+|url\()\s*["']?(https?:)?//""", re.I)
        for f in glob.glob(os.path.join(RAIZ, "carta", "*.html")) + glob.glob(os.path.join(RAIZ, "carta", "*.py")):
            with open(f, encoding="utf-8") as fh:
                self.assertIsNone(patron.search(fh.read()), f"{os.path.basename(f)} carga un recurso externo")


if __name__ == "__main__":
    unittest.main()

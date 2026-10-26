# SPDX-License-Identifier: EUPL-1.2
"""Tokens de diseño: salen de marca.json, caen a un tema neutro y garantizan contraste."""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "carta"))
import restaurante, tema


def marca(**colores):
    return restaurante.completar_marca({"nombre": "X", "logo": "l.png", "colores": colores})


class TestTema(unittest.TestCase):
    def test_tema_por_defecto_es_valido(self):
        css = tema.css()
        self.assertIn(":root{", css)
        for t in ("--fondo", "--tinta", "--primario", "--acento", "--r", "--f-texto"):
            self.assertIn(t + ":", css)

    def test_contraste_garantizado(self):
        d, _ = tema.tokens(marca(fondo="#202020", tinta="#888888", acento="#777777"))
        self.assertGreaterEqual(tema.contraste(d["--tinta"], d["--fondo"]), 12)
        self.assertGreaterEqual(tema.contraste(d["--acento-texto"], d["--fondo"]), 4.5)

    def test_cambiar_un_color_cambia_el_css(self):
        self.assertIn("--acento:#ff6600", tema.css(marca(acento="#ff6600")))

    def test_forma_invalida_se_rechaza(self):
        with self.assertRaises(Exception):
            restaurante.completar_marca({"nombre": "X", "logo": "l.png", "forma": {"radio": 99}})


if __name__ == "__main__":
    unittest.main()

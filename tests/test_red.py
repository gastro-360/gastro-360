# SPDX-License-Identifier: EUPL-1.2
"""La dirección que ofrece «Mesas y QR» no es la interna de un contenedor:  python -m unittest tests.test_red -v
Usa una carpeta temporal (CARTA_RESTAURANTES): no toca restaurantes/."""
import os, shutil, sys, tempfile, unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="red-")
os.environ.update(CARTA_RESTAURANTES=TMP, RESTAURANTE="demo")
sys.path.insert(0, os.path.join(RAIZ, "carta"))
import nuevo_restaurante  # noqa: E402

nuevo_restaurante.crear("demo", "Bar Demo", raiz=TMP)
import servidor  # noqa: E402


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class Red(unittest.TestCase):
    def test_en_contenedor_no_se_ofrece_la_ip_interna(self):
        with mock.patch.object(servidor, "en_contenedor", return_value=True), mock.patch.object(servidor, "ip_local", return_value="172.18.0.2"):
            self.assertEqual(servidor.info_red(), {"ip": "", "contenedor": True})

    def test_fuera_de_contenedor_se_ofrece_la_de_la_wifi(self):
        with mock.patch.object(servidor, "en_contenedor", return_value=False), mock.patch.object(servidor, "ip_local", return_value="192.168.1.20"):
            self.assertEqual(servidor.info_red(), {"ip": "192.168.1.20", "contenedor": False})


if __name__ == "__main__":
    unittest.main()

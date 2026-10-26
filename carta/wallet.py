# SPDX-License-Identifier: EUPL-1.2
"""Tarjeta de sellos en Apple Wallet y Google Wallet: lo común (dónde están las credenciales, modo de prueba, aviso a las tarjetas).

Sin credenciales reales (cuenta Apple Developer, cuenta emisora de Google Wallet) nada de esto habla con Apple ni con Google:
con WALLET_MODO=prueba se usan certificados y claves de PRUEBA autogenerados y clientes simulados (anotan lo que enviarían en
REGISTRO); sin credenciales y sin WALLET_MODO=prueba, el canal no está disponible y la tarjeta funciona solo como página web.
Las credenciales reales van en restaurantes/<local>/wallet/ (fuera de git, en el volumen en Docker); ver docs/MANUAL.md."""
import collections, os, shutil, subprocess, tempfile, threading

import restaurante

WALLET_DIR = os.environ.get("WALLET_DIR") or os.path.join(restaurante.DIR, "wallet")
REGISTRO = collections.deque(maxlen=200)   # lo que han «enviado» los simuladores (se ve en /api/wallet/simulador)
_bloqueo = threading.Lock()


def modo_prueba():
    return os.environ.get("WALLET_MODO") == "prueba"


def anotar(canal, **datos):
    REGISTRO.append({"canal": canal, **datos})


def openssl(*args, entrada=None):
    """Ejecuta openssl (viene en la imagen de Python). Devuelve stdout; lanza RuntimeError con su mensaje si falla."""
    r = subprocess.run(["openssl", *args], input=entrada, capture_output=True)
    if r.returncode:
        raise RuntimeError("openssl " + args[0] + ": " + r.stderr.decode("utf-8", "replace").strip()[:300])
    return r.stdout


def preparar_prueba(nombre, generar):
    """Carpeta wallet/prueba/<nombre>/ con el material de prueba; `generar(carpeta)` lo crea la primera vez (de forma atómica)."""
    destino = os.path.join(WALLET_DIR, "prueba", nombre)
    with _bloqueo:
        if not os.path.isdir(destino):
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            tmp = tempfile.mkdtemp(prefix=nombre + "-", dir=os.path.dirname(destino))
            try:
                generar(tmp)
                os.rename(tmp, destino)
            except BaseException:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
    return destino


def notificar(tid):
    """Avisa a las tarjetas Apple (push vacío: el móvil vuelve a pedir la tarjeta) y actualiza el objeto de Google.
    Se llama en segundo plano tras cada sello o canje; un fallo se apunta pero nunca tumba al servidor."""
    import wallet_apple, wallet_google
    for canal, f in (("apple", wallet_apple.empujar), ("google", wallet_google.actualizar)):
        try:
            f(tid)
        except Exception as e:   # noqa: BLE001
            print(f"ERROR wallet {canal}: {e!r}", flush=True)


def notificar_en_segundo_plano(tid):
    threading.Thread(target=notificar, args=(tid,), daemon=True).start()


def avisar(tid, titulo, texto, baja_url, idioma=None):
    """Promoción como aviso en la tarjeta: la deja en el pase y avisa a Apple (push) y a Google (mensaje con aviso).
    `idioma`: el del mensaje de Google (por defecto, el de la tarjeta; el pase de Apple sale siempre en el de la tarjeta).
    Devuelve (llegó_a_algún_canal, detalle). Un canal que falla no impide el otro."""
    import sellos, wallet_apple, wallet_google
    sellos.poner_aviso(tid, titulo, texto, baja_url)
    partes, llego = [], False
    for canal, f in (("apple", lambda: wallet_apple.empujar(tid)), ("google", lambda: wallet_google.avisar(tid, titulo, texto, idioma))):
        try:
            r = f()
        except Exception as e:   # noqa: BLE001
            partes.append(f"{canal}: error {e!r}"[:120])
            continue
        if canal == "apple":
            partes.append(f"apple: {r} dispositivo(s)")
        else:
            partes.append("google: " + ("avisado" if r else "sin objeto"))
        llego = llego or bool(r)
    return llego, "; ".join(partes)

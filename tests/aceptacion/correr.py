# SPDX-License-Identifier: EUPL-1.2
"""Runner de aceptación: ejecuta los casos automatizables de docs/GUION-ACEPTACION.md contra CUALQUIER url (local o remota).
Lo lanza tests/aceptacion/correr.sh dentro de la imagen de pruebas. No asume modos de prueba: detecta qué canales existen
(correo, Wallet, enlace de reseña) y comprueba el aviso si faltan o que funcionan si están.

Variables: QA_BASE_URL, QA_CLAVE, QA_SOLO (ids separados por comas), QA_SALIDA, QA_BASIC_USUARIO / QA_BASIC_CLAVE (opcionales:
autenticación HTTP básica delante del sitio; nunca se imprimen ni se guardan), QA_VERSION_ESPERADA (opcional), QA_REPO (carpeta
del repo montada en solo lectura, para CA-29).
No es destructivo: crea sus propios pedidos (nota «QA-agente»), clientes (qa-agente-…@example.com) y tarjetas, deja los pedidos
en «Servido» al acabar y devuelve a su sitio todo lo que toca (precio, interruptor de pedidos)."""
import json, os, re, sys, time, traceback
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

BASE = os.environ["QA_BASE_URL"].rstrip("/")
CLAVE = os.environ["QA_CLAVE"]
SOLO = [x.strip() for x in os.environ.get("QA_SOLO", "").split(",") if x.strip()]
SALIDA = os.environ.get("QA_SALIDA", "/salida")
BASIC = ({"username": os.environ["QA_BASIC_USUARIO"], "password": os.environ["QA_BASIC_CLAVE"], "origin": BASE}
         if os.environ.get("QA_BASIC_USUARIO") and os.environ.get("QA_BASIC_CLAVE") else None)
REPO = os.environ.get("QA_REPO", "/repo")
PROPIO = urlparse(BASE).netloc
MARCA = f"qa-agente-{int(time.time())}"
MOVIL = dict(viewport={"width": 360, "height": 740}, device_scale_factor=2, is_mobile=True, has_touch=True, locale="es-ES")
ESCRITORIO = dict(viewport={"width": 1280, "height": 800}, locale="es-ES")
VIEWPORTS = (("360", MOVIL), ("1280", ESCRITORIO))
os.makedirs(SALIDA, exist_ok=True)

# Textos que el runner espera ver. Un único sitio: si cambian los textos de la interfaz, se cambian aquí.
TEXTOS = {
    "promo_sin_canal": ["BREVO_API_KEY", "CORREO_MODO=prueba"],
    "camara_sin_soporte": r"navegador no puede leer el código con la cámara",
    "tarjetas_titulo": r"últimas tarjetas",
    "wallet_quien": r"dueño|quien (lo )?instale|persona que",
    "cifra_ayuda": r"\bcuenta\b",
    "cifras_vacias": r"todavía no hay datos|aún no hay datos|aún no ha pasado nada|todavía no ha pasado nada",
    "resena_falta": r"enlace de reseña",
    "resena_donde": r"google_place_id|resena_url|marca\.json|ajustes",
    "tarjeta_pista": r"guardar mi tarjeta de sellos",
    "baja_invalida": r"no (es )?válid|no encuentro|caducad",
    "cerrado": r"no se aceptan pedidos",
}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


class Falla(Exception):
    pass


class Manual(Exception):
    pass


CASOS = []


def caso(id, titulo, issue=None, tolera_4xx=False):
    def reg(f):
        CASOS.append(dict(id=id, titulo=titulo, issue=issue, fn=f, tolera_4xx=tolera_4xx))
        return f
    return reg


def espera(p, expr, seg=15):
    """Espera a que la expresión JS sea cierta. Se evalúa por el protocolo del navegador: wait_for_function usa eval(), que la CSP prohíbe."""
    fin = time.time() + seg
    while time.time() < fin:
        try:
            if p.evaluate(expr):
                return True
        except Exception:   # noqa: BLE001
            pass
        time.sleep(0.2)
    return False


def texto(p, sel="body"):
    return p.locator(sel).first.inner_text()


class Ejecucion:
    """Estado compartido de toda la pasada: navegador, sesión del dueño y lo que crean los casos."""

    def __init__(self, pw):
        self.pw = pw
        self.browser = pw.chromium.launch(args=["--ignore-certificate-errors"])   # el service worker no admite el certificado propio de Caddy en local
        self.ctx_api = self.nuevo_contexto(MOVIL)
        self.api_ok = False
        self.pedidos = {}          # id -> estado conocido (para dejarlos en «Servido»)
        self.tarjeta = None
        self.email = None
        self.plato = None
        self.mesa = 1
        self.resena = None

    def nuevo_contexto(self, tipo, **extra):
        return self.browser.new_context(ignore_https_errors=True, http_credentials=BASIC, **tipo, **extra)

    # ---- API con la sesión del dueño (sin navegador) ----
    def api(self, metodo, ruta, cuerpo=None):
        r = self.ctx_api.request.fetch(BASE + ruta, method=metodo, data=cuerpo, headers={"Content-Type": "application/json"} if cuerpo is not None else None)
        try:
            j = r.json()
        except Exception:   # noqa: BLE001
            j = {}
        return r.status, j

    def entrar_api(self):
        if not self.api_ok:
            s, _ = self.api("POST", "/api/login", {"clave": CLAVE})
            if s != 200:
                raise Falla(f"no se puede entrar al backoffice por API (HTTP {s}): ¿CLAVE correcta?")
            self.api_ok = True
            self.estado_sesion = self.ctx_api.storage_state()

    def preparar(self):
        self.entrar_api()
        html = self.ctx_api.request.get(BASE + "/").text()
        m = re.search(r"const RESENA=(.*?);\n", html)
        self.resena = json.loads(m.group(1)) if m and m.group(1).strip() not in ("", "null") else None
        _, d = self.api("GET", "/api/datos")
        self.mesa = (d.get("mesas") or [{"n": 1}])[0]["n"]
        self.plato = next(x for x in d["platos"] if not x.get("oculto"))["id"]

    def pedido_api(self, nota, estado=None, permiso=None):
        cuerpo = {"mesa": self.mesa, "lineas": [{"pid": self.plato}], "nota": nota, "via": "manual"}
        if permiso:
            cuerpo["permiso"] = permiso
        s, j = self.api("POST", "/api/pedido", cuerpo)
        if s != 200:
            raise Falla(f"no se pudo crear un pedido por API (HTTP {s}): {j.get('error', '')}")
        self.pedidos[j["id"]] = "nuevo"
        if estado and estado != "nuevo":
            self.mover(j["id"], estado)
        return j["id"]

    def mover(self, pid, estado):
        s, j = self.api("POST", "/api/pedido/estado", {"id": pid, "estado": estado})
        if s != 200:
            raise Falla(f"no se pudo pasar el pedido a «{estado}» (HTTP {s})")
        self.pedidos[pid] = estado

    def estado_pedido(self, pid):
        _, j = self.api("GET", "/api/pedidos")
        return next((x["estado"] for x in j.get("pedidos", []) if x["id"] == pid), None)

    def canales(self):
        s, j = self.api("GET", "/api/promociones")
        return (j.get("canales") or {}) if s == 200 else {}

    def modo_prueba_correo(self):
        return self.api("GET", "/api/promociones/simulador")[0] == 200

    def es_apto(self, email):
        f = next((x for x in self.api("GET", "/api/clientes")[1].get("clientes", []) if x["email"] == email), None)
        return bool(f and f["apto_marketing"])

    def confirmar_permiso(self, email, seg=25):
        """Alta directa (por defecto): marcar la casilla ya dio el alta, no hay nada que confirmar y devuelve True.
        Con CONFIRMACION_DOBLE=1 saca el token del correo de confirmación del simulador (CORREO_MODO=prueba) y confirma por POST /api/confirmar.
        Devuelve True si el cliente queda confirmado; False si no hay simulador (escenario sin credenciales: queda pendiente)."""
        if self.es_apto(email):
            return True
        if not self.modo_prueba_correo():
            return False
        fin = time.time() + seg
        while time.time() < fin:
            for m in self.api("GET", "/api/promociones/simulador")[1].get("correos", []):
                if m["para"] == email and not m.get("asunto", "").startswith("Publicidad:"):
                    t = re.search(r"/confirmar\?t=([\w\-]+)", json.dumps(m))
                    if t:
                        return self.api("POST", "/api/confirmar", {"token": t.group(1)})[0] == 200
            time.sleep(0.5)
        return False

    def tarjeta_qa(self):
        if not self.tarjeta:
            s, j = self.api("POST", "/api/tarjeta", {})
            if s != 200:
                raise Manual(f"el programa de sellos no está activo (HTTP {s}): no se puede crear una tarjeta")
            self.tarjeta = j["id"]
        return self.tarjeta

    def limpiar_pedidos(self):
        for pid, est in list(self.pedidos.items()):
            if est != "entregado":
                try:
                    self.mover(pid, "entregado")
                except Exception:   # noqa: BLE001
                    pass

    def cerrar(self):
        self.limpiar_pedidos()
        self.browser.close()


class Caso:
    """Un caso en marcha: abre páginas vigiladas (errores de consola/JS/red y hosts ajenos) y acumula los fallos."""

    def __init__(self, ej, meta):
        self.ej, self.meta = ej, meta
        self.fallos, self.errores, self.contextos, self.paginas = [], [], [], []
        self.captura = None

    id = property(lambda s: s.meta["id"])

    def exige(self, cond, msg):
        if not cond:
            self.fallos.append(msg)
        return bool(cond)

    def pagina(self, tipo, sesion=False, init=None):
        ctx = self.ej.nuevo_contexto(tipo, storage_state=self.ej.estado_sesion if sesion else None)
        self.contextos.append(ctx)
        if init:
            ctx.add_init_script(init)
        ctx.on("request", self._peticion)
        p = ctx.new_page()
        p.on("pageerror", lambda e: self.errores.append(f"error JS: {str(e)[:160]}"))
        p.on("console", self._consola)
        p.on("requestfailed", lambda r: "ERR_ABORTED" not in str(r.failure) and self.errores.append(f"petición fallida: {urlparse(r.url).path} {r.failure}"))
        p.on("dialog", lambda d: d.accept())
        self.paginas.append(p)
        return p

    def _peticion(self, r):
        u = urlparse(r.url)
        if u.scheme not in ("data", "blob", "about") and u.netloc != PROPIO:
            self.errores.append(f"petición a otro host: {u.netloc}")

    def _consola(self, m):
        if m.type not in ("error", "warning"):
            return
        if self.meta["tolera_4xx"] and re.search(r"status of 4\d\d", m.text):
            return
        self.errores.append(f"consola {m.type}: {m.text[:160]}")

    def foto(self, p, nombre):
        ruta = f"{SALIDA}/{self.id}-{nombre}.png"
        p.screenshot(path=ruta)
        self.captura = self.captura or ruta

    def sin_desborde(self, p, que):
        d = p.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        self.exige(d <= 1, f"{que}: hay scroll horizontal (sobran {d}px)")

    def cerrar(self):
        if self.fallos or self.errores:
            for i, p in enumerate(self.paginas):
                try:
                    ruta = f"{SALIDA}/{self.id}-falla-{i}.png"
                    p.screenshot(path=ruta)
                    self.captura = ruta
                except Exception:   # noqa: BLE001
                    pass
        for c in self.contextos:
            try:
                c.close()
            except Exception:   # noqa: BLE001
                pass


# ====================================================================== ayudas de pantallas
def abrir_carta(c, tipo, ruta=None):
    p = c.pagina(tipo)
    p.goto(f"{BASE}{ruta or '/?mesa=' + str(c.ej.mesa)}")
    p.wait_for_selector("#lista [data-b]", timeout=20000)
    return p


def enviar_pedido(c, p, tipo, nota, email=None, marcar=False):
    """Monta el primer plato, lo envía y devuelve el id del pedido que la carta enseña como «Recibido»."""
    p.locator("#lista [data-b]").first.click()
    p.locator("#add").click()
    if not espera(p, "document.querySelector('#lineas').children.length>=1"):
        raise Falla("el plato no se añade al pedido")
    if tipo is MOVIL:
        p.locator("#verPedido").click()
    p.locator("#enviar").click()
    p.wait_for_selector("#dlgEnviar[open]", timeout=10000)
    if email:
        p.locator("#dlgEmail").fill(email)
        if marcar:
            p.locator("#dlgPermisoCasilla").check()
    p.locator("#dlgNota").fill(nota)
    p.locator("#dlgOk").click()
    p.wait_for_selector(".env[data-pedido]", timeout=15000)
    pid = p.locator(".env[data-pedido]").first.get_attribute("data-pedido")
    c.ej.pedidos[pid] = "nuevo"
    return pid


def pedido_en_carta(c, tipo, nota):
    p = abrir_carta(c, tipo)
    return p, enviar_pedido(c, p, tipo, nota)


def entrar_cocina(c, tipo, clave=None):
    p = c.pagina(tipo)
    p.goto(f"{BASE}/cocina")
    p.locator("#clave").fill(CLAVE if clave is None else clave)
    p.locator("#formLogin button[type=submit]").click()
    return p


def entrar_admin(c, tipo):
    p = c.pagina(tipo, sesion=True)
    p.goto(f"{BASE}/admin")
    if not p.locator("#vista").first.is_visible():
        p.wait_for_selector("#vista .grupo, #vista .cab", timeout=15000)
    return p


# Texto de la opción elegida frente al hueco del selector (descontando relleno y flecha): devuelve «ancho/hueco» si se corta.
CORTE_SELECTOR_IDIOMA = """() => { const s = document.querySelector('.top .sel-idioma'); const cs = getComputedStyle(s);
  const cv = document.createElement('canvas').getContext('2d'); cv.font = cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily;
  const w = cv.measureText(s.options[s.selectedIndex].text).width;
  const hueco = s.getBoundingClientRect().width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 20;
  return w > hueco ? Math.round(w) + '/' + Math.round(hueco) : ''; }"""


def pestana(p, tab, seg=15):
    p.locator(f'.tab[data-tab="{tab}"]').click()
    if not espera(p, "!document.querySelector('#vista').innerText.includes('Cargando')", seg):
        raise Falla(f"la pestaña «{tab}» se queda en «Cargando…»")
    return texto(p, "#vista")


# ====================================================================== CLIENTE
@caso("CA-01", "Carta: se abre, enseña platos y la mesa del QR")
def ca01(c):
    for nom, tipo in VIEWPORTS:
        p = abrir_carta(c, tipo)
        c.exige(p.locator("#lista [data-b]").count() >= 1, f"{nom}px: no hay platos en la carta")
        c.exige(f"mesa {c.ej.mesa}" in texto(p, "#mesaTag").lower(), f"{nom}px: no se ve «Mesa {c.ej.mesa}» del QR")
        c.exige("{{" not in p.content(), f"{nom}px: quedan marcadores {{{{…}}}} sin rellenar")
        c.sin_desborde(p, f"{nom}px carta")
        c.foto(p, f"carta-{nom}")
        for lang in ("es", "en", "ca", "zh", "fr", "de", "it", "pt"):
            p.select_option(".top .sel-idioma", lang)
            p.wait_for_timeout(300)
            corta = p.evaluate(CORTE_SELECTOR_IDIOMA)
            c.exige(not corta, f"{nom}px ({lang}): el selector de idioma corta su texto ({corta})")


@caso("CA-02", "Pedido: montar un plato, quitar un ingrediente y enviarlo a cocina")
def ca02(c):
    for nom, tipo in VIEWPORTS:
        p = abrir_carta(c, tipo)
        p.locator("#lista [data-b]").first.click()
        chip = p.locator("#chips .chip:not(.off):not(.extra) [data-t]")
        if chip.count():
            chip.first.click()
            c.exige(p.locator("#lista .mod").count() >= 1, f"{nom}px: quitar un ingrediente no marca «Personalizado»")
        pid = enviar_pedido(c, p, tipo, f"QA-agente CA-02 {nom}")
        env = texto(p, ".env[data-pedido]").lower()
        c.exige("recibido" in env, f"{nom}px: el cliente no ve su pedido «Recibido» ({env[:60]})")
        c.exige(f"mesa {c.ej.mesa}" in env, f"{nom}px: el pedido no sale con la mesa {c.ej.mesa}")
        c.sin_desborde(p, f"{nom}px tras enviar")
        lista = c.ej.api("GET", "/api/pedidos")[1].get("pedidos", [])
        mio = next((x for x in lista if x["id"] == pid), None)
        c.exige(bool(mio) and mio["nota"] == f"QA-agente CA-02 {nom}", f"{nom}px: el pedido no llega a cocina con su nota")
        c.foto(p, f"pedido-{nom}")


@caso("CA-03", "Casilla de permiso: viene sin marcar, se lee entera y sin marcarla no se guarda el correo")
def ca03(c):
    correo = f"{MARCA}-sin-permiso@example.com"
    for nom, tipo in VIEWPORTS:
        p = abrir_carta(c, tipo)
        p.locator("#lista [data-b]").first.click()
        p.locator("#add").click()
        espera(p, "document.querySelector('#lineas').children.length>=1")
        if tipo is MOVIL:
            p.locator("#verPedido").click()
        p.locator("#enviar").click()
        p.wait_for_selector("#dlgEnviar[open]", timeout=10000)
        casilla = p.locator("#dlgPermisoCasilla")
        casilla.wait_for(state="visible", timeout=5000)
        c.exige(not casilla.is_checked(), f"{nom}px: la casilla viene premarcada")
        t = texto(p, "#dlgPermisoTexto")
        c.exige(len(t) > 80 and "baja" in t.lower(), f"{nom}px: el texto de la casilla no se lee entero o no menciona la baja")
        caja = p.locator("#dlgEnviar").bounding_box()
        c.exige(bool(caja) and caja["x"] >= 0 and caja["x"] + caja["width"] <= p.viewport_size["width"] + 1, f"{nom}px: el diálogo no cabe en la pantalla")
        c.foto(p, f"dialogo-{nom}")
        if tipo is MOVIL:
            p.locator("#dlgEmail").fill(correo)
            p.locator("#dlgNota").fill("QA-agente CA-03")
            p.locator("#dlgOk").click()
            p.wait_for_selector(".env[data-pedido]", timeout=15000)
            c.ej.pedidos[p.locator(".env[data-pedido]").first.get_attribute("data-pedido")] = "nuevo"
    clientes = c.ej.api("GET", "/api/clientes")[1].get("clientes", [])
    c.exige(not any(x["email"] == correo for x in clientes), "con la casilla sin marcar se ha guardado el correo")


@caso("CA-04", "Permiso dado: con la casilla marcada queda la prueba (texto, versión y fecha) y el cliente es apto")
def ca04(c):
    c.ej.email = f"{MARCA}@example.com"
    p = abrir_carta(c, MOVIL)
    enviar_pedido(c, p, MOVIL, "QA-agente CA-04", email=c.ej.email, marcar=True)
    ficha = next((x for x in c.ej.api("GET", "/api/clientes")[1].get("clientes", []) if x["email"] == c.ej.email), None)
    if not c.exige(bool(ficha), "el cliente con permiso no aparece en la ficha de clientes"):
        return
    doble = os.environ.get("QA_CONFIRMACION_DOBLE", "").strip().lower() in ("1", "true", "si", "sí", "yes")   # opcional: fija el modo esperado
    if not ficha["apto_marketing"]:   # doble confirmación (CONFIRMACION_DOBLE=1): pendiente hasta el clic del titular
        c.exige(ficha.get("pendiente"), "con doble confirmación, antes de confirmar por correo el cliente debe quedar pendiente y NO apto")
    else:   # por defecto, alta directa: apto al instante, sin solicitud pendiente
        c.exige(not ficha.get("pendiente") and not doble, "en alta directa el cliente es apto al instante sin quedar pendiente"
                " (si se esperaba doble confirmación, QA_CONFIRMACION_DOBLE=1 no coincide con el servidor)")
    if not c.ej.confirmar_permiso(c.ej.email):
        c.exige(not ficha["apto_marketing"], "sin canal de correo no se puede confirmar: debe quedar pendiente, no apto")
        c.foto(p, "permiso")
        return "escenario sin canal de correo: queda «Pendiente de confirmar» (no apto); confirmar el enlace del correo, a mano"
    ficha = next(x for x in c.ej.api("GET", "/api/clientes")[1]["clientes"] if x["email"] == c.ej.email)
    prueba = ficha["permisos"][-1]
    c.exige(ficha["apto_marketing"], "el cliente no figura como apto para marketing")
    c.exige(prueba["accion"] == "alta" and prueba["texto"] and prueba["texto_version"] and prueba["fecha"] and prueba["canal"],
            "la prueba del permiso no guarda texto, versión, fecha y canal")
    c.foto(p, "permiso")


@caso("CA-05", "Estado del pedido: el cliente ve cada cambio de cocina sin recargar y se le avisa cuando está listo")
def ca05(c):
    p, pid = pedido_en_carta(c, MOVIL, "QA-agente CA-05")
    c.ej.mover(pid, "preparando")
    c.exige(espera(p, "document.querySelector('.env[data-e]').dataset.e==='preparando'", 20), "no ve «En preparación» sin recargar")
    c.exige("en preparación" in texto(p, ".env[data-pedido]").lower(), "el pedido no dice «En preparación»")
    c.ej.mover(pid, "listo")
    c.exige(espera(p, "document.querySelector('.env[data-e]').dataset.e==='listo'", 20), "no ve «Listo» sin recargar")
    c.exige(espera(p, "document.querySelector('#toast') && /listo/i.test(document.querySelector('#toast').innerText)", 5), "no sale el aviso «¡Pedido listo!»")
    c.foto(p, "listo")
    c.sin_desborde(p, "360px estado del pedido")


@caso("CA-06", "Reseña de Google: solo en «Servido», mismo botón para todos y sin preguntar si gustó")
def ca06(c):
    p, pid = pedido_en_carta(c, MOVIL, "QA-agente CA-06")
    c.exige(p.locator(".env a.resena").count() == 0, "sale el botón de reseña antes de servir el pedido")
    c.ej.mover(pid, "entregado")
    c.exige(espera(p, "document.querySelector('.env[data-e=entregado]')", 20), "no ve «Servido» sin recargar")
    boton = p.locator(".env[data-e=entregado] a.resena")
    if c.ej.resena:
        c.exige(boton.count() == 1 and boton.first.get_attribute("href") == c.ej.resena, "al servir no sale el botón con el enlace del local")
        c.exige(bool(boton.count()) and "reseña" in boton.first.inner_text().lower(), "el botón no dice «reseña»")
        detalle = "hay enlace de reseña: el botón sale solo en «Servido»"
    else:
        c.exige(boton.count() == 0, "sale un botón de reseña sin enlace configurado")
        detalle = "sin enlace de reseña en este local: no sale el botón (el aviso al dueño es CA-28)"
    t = texto(p, "#enviados").lower()
    c.exige(not re.search(r"descuento|regalo|te ha gustado|valora|puntúa|estrellas", t), "la carta pregunta si gustó u ofrece algo por reseñar")
    c.foto(p, "servido")
    return detalle


@caso("CA-07", "Tarjeta de sellos: el cliente la guarda tras el pedido, la ve con su código y es anónima")
def ca07(c):
    cfg = c.ej.api("GET", "/api/sellos/config")[1]
    if not cfg.get("activo"):
        raise Manual("el programa de sellos está desactivado en este local")
    p, pid = pedido_en_carta(c, MOVIL, "QA-agente CA-07")
    c.ej.mover(pid, "entregado")
    boton = p.locator("#tarjetaNueva")
    espera(p, "document.querySelector('#tarjetaNueva')", 20)
    if not c.exige(boton.count() == 1, "tras el pedido no sale «Guardar mi tarjeta de sellos»"):
        return
    boton.click()
    p.wait_for_url(re.compile(r"/tarjeta\?t="), timeout=15000)
    codigo = p.url.split("t=")[1]
    c.ej.tarjeta = c.ej.tarjeta or codigo
    c.exige(p.wait_for_selector("#qr:not([hidden])", timeout=15000) is not None, "no se ve el QR de la tarjeta")
    c.exige(bool(texto(p, "#codigo").strip()), "no se ve el código escrito de la tarjeta")
    cuerpo = texto(p).lower()
    c.exige("@" not in cuerpo, "la tarjeta enseña un correo: debe ser anónima")
    canales = c.ej.api("GET", "/api/sellos/config")[1].get("canales", {})
    for nombre, clave in (("apple wallet", "apple"), ("google wallet", "google")):
        c.exige((nombre in cuerpo) == bool(canales.get(clave)), f"la tarjeta {'ofrece' if nombre in cuerpo else 'no ofrece'} {nombre} pero el canal {'no ' if not canales.get(clave) else ''}existe")
    c.sin_desborde(p, "360px tarjeta")
    c.foto(p, "tarjeta-360")
    p2 = c.pagina(ESCRITORIO)
    p2.goto(f"{BASE}/tarjeta?t={codigo}")
    p2.wait_for_selector("#qr:not([hidden])", timeout=15000)
    c.sin_desborde(p2, "1280px tarjeta")
    return "canales Wallet: " + (", ".join(k for k, v in canales.items() if v) or "ninguno (la tarjeta funciona como página web)")


@caso("CA-08", "Baja: un enlace de baja que no vale lo dice con claridad y no da de baja a nadie", tolera_4xx=True)
def ca08(c):
    for nom, tipo in VIEWPORTS:
        p = c.pagina(tipo)
        p.goto(f"{BASE}/baja?t=enlace-que-no-existe")
        p.wait_for_selector("#msg, #ok", timeout=10000)
        c.sin_desborde(p, f"{nom}px baja")
        t = texto(p).lower()
        if p.locator("#ok").count() and p.locator("#ok").is_visible():
            p.locator("#ok").click()
            espera(p, "document.querySelector('#msg') && document.querySelector('#msg').innerText.length>0", 8)
            t = texto(p).lower()
        c.exige(bool(re.search(TEXTOS["baja_invalida"], t)), f"{nom}px: el enlace falso no dice que no es válido ({t[:80]!r})")
        c.foto(p, f"baja-{nom}")


@caso("CA-09", "Baja completa: el correo trae el enlace, abrirlo no da de baja, confirmar sí y queda la prueba")
def ca09(c):
    if not c.ej.modo_prueba_correo():
        raise Manual("necesita el canal de correo en modo prueba (CORREO_MODO=prueba) para leer el enlace de baja; sin él, comprobar a mano")
    correo = f"{MARCA}-baja@example.com"
    version = c.ej.ctx_api.request.get(BASE + "/api/permiso").json()["version"]
    c.ej.pedido_api("QA-agente CA-09", estado="entregado", permiso={"email": correo, "version": version})
    if not c.exige(c.ej.confirmar_permiso(correo), "no se pudo confirmar el permiso con el enlace del correo de confirmación"):
        return
    s, r = c.ej.api("POST", "/api/promociones", {"titulo": "QA-agente baja", "texto": "Prueba automática del enlace de baja.", "canales": ["email"]})
    if s != 201 and s != 200:
        raise Falla(f"no se pudo crear la promoción de prueba (HTTP {s})")
    c.ej.api("POST", "/api/promociones/enviar", {"id": r["id"]})
    mail = None
    fin = time.time() + 25
    while time.time() < fin and not mail:
        mail = next((m for m in c.ej.api("GET", "/api/promociones/simulador")[1].get("correos", []) if m["para"] == correo and m.get("asunto", "").startswith("Publicidad:")), None)
        time.sleep(0.5)
    if not c.exige(bool(mail), "el correo de promoción no llega al cliente con permiso"):
        return
    token = re.search(r"/baja\?t=([\w\-]+)", json.dumps(mail))
    if not c.exige(bool(token), "el correo no lleva el enlace de baja"):
        return
    apto = lambda: next(x for x in c.ej.api("GET", "/api/clientes")[1]["clientes"] if x["email"] == correo)
    p = c.pagina(MOVIL)
    p.goto(f"{BASE}/baja?t={token.group(1)}")
    p.wait_for_selector("#ok", timeout=10000)
    c.exige(apto()["apto_marketing"], "abrir el enlace de baja ya da de baja (debe pedir confirmación)")
    c.sin_desborde(p, "360px baja")
    p.locator("#ok").click()
    c.exige(espera(p, "true", 1) and any(not apto()["apto_marketing"] or time.sleep(0.5) for _ in range(20)), "tras confirmar, el cliente sigue apto")
    f = apto()
    c.exige(not f["apto_marketing"] and f["permisos"][-1]["accion"] == "baja", "la baja no queda apuntada como prueba")
    c.foto(p, "baja-360")


# ====================================================================== COCINA
@caso("CA-10", "Cocina: pide la contraseña, avisa si es mala y enseña los pedidos nuevos con su mesa y nota", tolera_4xx=True)
def ca10(c):
    pid = c.ej.pedido_api("QA-agente CA-10")
    for nom, tipo in VIEWPORTS:
        mala = entrar_cocina(c, tipo, clave="clave-que-no-es")
        espera(mala, "document.querySelector('#errLogin').innerText.length>0", 8)
        c.exige(bool(texto(mala, "#errLogin").strip()), f"{nom}px: con una contraseña mala no hay aviso")
        p = entrar_cocina(c, tipo)
        c.exige(espera(p, f"!!document.querySelector('article.ped')", 20), f"{nom}px: la cocina no enseña pedidos")
        t = texto(p, "#tablero")
        c.exige("QA-agente CA-10" in t, f"{nom}px: no se ve la nota del pedido")
        c.exige("mesa" in t.lower(), f"{nom}px: no se ve la mesa")
        c.sin_desborde(p, f"{nom}px cocina")
        c.foto(p, f"cocina-{nom}")
    c.ej.mover(pid, "entregado")


@caso("CA-11", "Cocina: pasar un pedido a En preparación, Listo y Servido con botones grandes")
def ca11(c):
    pid = c.ej.pedido_api("QA-agente CA-11")
    for nom, tipo in VIEWPORTS:
        if nom == "1280":
            pid = c.ej.pedido_api("QA-agente CA-11 b")
        p = entrar_cocina(c, tipo)
        p.wait_for_selector(f'button[data-mover="{pid}"]', timeout=20000)
        for destino in ("preparando", "listo", "entregado"):
            b = p.locator(f'button[data-mover="{pid}"][data-a="{destino}"]')
            b.wait_for(state="visible", timeout=10000)
            alto = b.bounding_box()["height"]
            c.exige(alto >= 40, f"{nom}px: el botón «{destino}» es pequeño ({alto:.0f}px)")
            b.click()
            c.exige(espera(p, "true", 0.1) and any(c.ej.estado_pedido(pid) == destino or time.sleep(0.4) for _ in range(20)),
                    f"{nom}px: el servidor no refleja «{destino}»")
            c.ej.pedidos[pid] = destino
        c.foto(p, f"cocina-servido-{nom}")


# ====================================================================== DUEÑO: backoffice
PESTANAS = (("boc", "nuevo"), ("pic", "nueva ración"), ("ing", "nuevo ingrediente"), ("mes", "mesas"),
            ("sel", "tarjeta de sellos"), ("pro", "promociones"), ("cif", "cifras"), ("exp", "no es una factura"), ("onl", "pedidos online"), ("res", "reservas"))


@caso("CA-12", "Backoffice: pide la contraseña, avisa si es mala y enseña las diez pestañas", tolera_4xx=True)
def ca12(c):
    for nom, tipo in VIEWPORTS:
        p = c.pagina(tipo)
        p.goto(f"{BASE}/admin")
        p.locator("#clave").fill("clave-que-no-es")
        p.locator("#formLogin button[type=submit]").click()
        espera(p, "document.querySelector('#errLogin').innerText.length>0", 8)
        c.exige(bool(texto(p, "#errLogin").strip()), f"{nom}px: con una contraseña mala no hay aviso")
        p.locator("#clave").fill(CLAVE)
        p.locator("#formLogin button[type=submit]").click()
        p.wait_for_selector("#vista .grupo, #vista .cab", timeout=15000)
        c.exige(p.locator(".tab").count() == 10, f"{nom}px: no hay diez pestañas ({p.locator('.tab').count()})")
        c.sin_desborde(p, f"{nom}px backoffice")
        c.foto(p, f"admin-{nom}")


@caso("CA-13", "Platos, Para picar e Ingredientes cargan y un cambio de precio llega a la carta (se deja como estaba)")
def ca13(c):
    p = entrar_admin(c, ESCRITORIO)
    for tab, que in (("boc", "nuevo"), ("pic", "nueva ración"), ("ing", "nuevo ingrediente")):
        c.exige(que in pestana(p, tab).lower(), f"la pestaña «{tab}» no se ve completa")
    pestana(p, "boc")
    campo = p.locator('input[data-campo="p"][data-tipo="boc"]').first
    antes = campo.input_value()
    nuevo = "9.97" if antes != "9.97" else "9.96"
    guardar = lambda: (p.locator("#guardar").click(), espera(p, "document.querySelector('#guardar').disabled", 15))
    try:
        campo.fill(nuevo)
        campo.dispatch_event("change")
        guardar()
        q = abrir_carta(c, MOVIL)
        c.exige(nuevo.replace(".", ",") in texto(q, "#lista [data-b]"), f"el precio nuevo ({nuevo}) no sale en la carta")
    finally:
        campo.fill(antes)
        campo.dispatch_event("change")
        guardar()
    _, d = c.ej.api("GET", "/api/datos")
    c.exige(str(d["platos"][0]["p"]) in (antes, str(float(antes)), antes.rstrip("0").rstrip(".")), "no se ha podido devolver el precio a como estaba")


@caso("CA-14", "Mesas y QR: explica qué hace, pide la dirección de la carta y deja añadir mesas")
def ca14(c):
    for nom, tipo in VIEWPORTS:
        p = entrar_admin(c, tipo)
        t = pestana(p, "mes").lower()
        for esperado in ("dirección de la carta", "añadir mesas", "código"):
            c.exige(esperado in t, f"{nom}px: falta «{esperado}»")
        c.exige(p.locator("#urlQR").count() == 1 and p.locator('[data-acc="anadirMesas"]').count() == 1, f"{nom}px: faltan el campo de dirección o el botón «Añadir»")
        botones = " ".join(p.locator(".fila-url button").all_inner_texts())
        c.exige(not re.search(r"\b172\.(1[6-9]|2\d|3[01])\.", botones),
                f"{nom}px: ofrece una dirección interna de Docker (172.x) que un móvil no puede abrir: «{botones}»")
        c.sin_desborde(p, f"{nom}px mesas")
        c.foto(p, f"mesas-{nom}")


@caso("CA-15", "Interruptor «Aceptar pedidos»: cerrado, la carta lo avisa, no deja enviar y el servidor lo rechaza (se deja como estaba)")
def ca15(c):
    p = entrar_admin(c, ESCRITORIO)
    boton = p.locator("#aceptar")
    espera(p, "document.querySelector('#aceptar').textContent.length>0", 10)
    abiertos_antes = "abiertos" in boton.inner_text().lower()
    try:
        if abiertos_antes:
            boton.click()
        c.exige(espera(p, "document.querySelector('#aceptar').textContent.includes('CERRADOS')", 10), "el botón no pasa a «CERRADOS»")
        q = abrir_carta(c, MOVIL)
        q.locator("#lista [data-b]").first.click()
        q.locator("#add").click()
        c.exige(q.wait_for_selector("#cerrado:not([hidden])", timeout=10000) is not None and re.search(TEXTOS["cerrado"], texto(q, "#cerrado").lower()),
                "la carta no avisa de que no se aceptan pedidos")
        q.locator("#verPedido").click()
        c.exige(q.locator("#enviar").is_disabled(), "«Enviar a cocina» sigue activo con los pedidos cerrados")
        s, _ = c.ej.api("POST", "/api/pedido", {"mesa": c.ej.mesa, "lineas": [{"pid": c.ej.plato}], "nota": "QA-agente CA-15"})
        c.exige(s == 503, f"el servidor acepta un pedido con los pedidos cerrados (HTTP {s})")
        k = entrar_cocina(c, ESCRITORIO)
        k.wait_for_selector("#tablero .col", timeout=15000)
        c.exige(k.locator("#aceptar.cerrado").count() == 1, "la cocina no marca los pedidos como cerrados")
        c.foto(q, "carta-cerrada")
    finally:
        if abiertos_antes:
            if "CERRADOS" in boton.inner_text():
                boton.click()
            if not espera(p, "document.querySelector('#aceptar').textContent.includes('abiertos')", 10):
                c.ej.api("POST", "/api/aceptar", {"aceptar_pedidos": True})
    c.exige(c.ej.api("GET", "/api/estado")[1].get("aceptar_pedidos") == abiertos_antes, "no se ha dejado el interruptor como estaba")


def sellos_admin(c, tipo=ESCRITORIO, init=None):
    cfg = c.ej.api("GET", "/api/sellos/config")[1]
    if not cfg.get("activo"):
        raise Manual("el programa de sellos está desactivado en este local")
    p = c.pagina(tipo, sesion=True, init=init)
    p.goto(f"{BASE}/admin")
    p.wait_for_selector("#vista .grupo, #vista .cab", timeout=15000)
    pestana(p, "sel")
    return p, cfg


@caso("CA-16", "Sellos: ajustes y caja; buscar una tarjeta por su código, sellar a mano y avisar si el código no existe", tolera_4xx=True)
def ca16(c):
    codigo = c.ej.tarjeta_qa()
    for nom, tipo in VIEWPORTS:
        p, cfg = sellos_admin(c, tipo)
        t = texto(p, "#vista").lower()
        for esperado in ("tarjeta de sellos", "programa activo", "sellos para el premio", "premio", "importe mínimo", "caja"):
            c.exige(esperado in t, f"{nom}px: falta «{esperado}»")
        c.sin_desborde(p, f"{nom}px sellos")
        p.locator("#selCodigo").fill("codigo-que-no-existe")
        p.locator('[data-sel="buscar"]').click()
        c.exige(espera(p, "document.querySelector('#vista').innerText.toLowerCase().includes('no encuentro esa tarjeta')", 8), f"{nom}px: con un código falso no dice «No encuentro esa tarjeta»")
        p.locator("#selCodigo").fill(codigo)
        p.locator('[data-sel="buscar"]').click()
        c.exige(espera(p, "/\\d+ de \\d+ sellos/.test(document.querySelector('#vista').innerText)", 8), f"{nom}px: no encuentra la tarjeta por su código")
        if nom == "1280":
            antes = c.ej.api("GET", "/api/tarjeta?t=" + codigo)[1]["sellos"]
            if antes < cfg["sellos_meta"]:
                p.locator("#selImporte").fill(str(max(cfg["importe_minimo"], 1) + 1))
                p.locator('[data-sel="sellar"]').click()
                espera(p, "document.querySelector('#vista').innerText.includes('Sello puesto')", 8)
                c.exige(c.ej.api("GET", "/api/tarjeta?t=" + codigo)[1]["sellos"] == antes + 1, "«Sellar en caja» no suma el sello")
        c.foto(p, f"sellos-{nom}")


@caso("CA-17", "Sellos: el dueño ve las últimas tarjetas (con sellos y fecha) o, si no hay, cómo consigue el cliente la suya")
def ca17(c):
    codigo = c.ej.tarjeta_qa()
    p, _ = sellos_admin(c)
    t = texto(p, "#vista")
    c.exige(re.search(TEXTOS["tarjetas_titulo"], t, re.I) is not None, "la pestaña Sellos no tiene una lista de «Últimas tarjetas»")
    c.exige(codigo in t, "la lista de tarjetas no enseña el código de la tarjeta recién creada")
    c.foto(p, "sellos-lista")


@caso("CA-18", "Sellos: al llegar al objetivo no se puede sellar más hasta canjear (lo manda el servidor)")
def ca18(c):
    cfg = c.ej.api("GET", "/api/sellos/config")[1]
    if not cfg.get("activo"):
        raise Manual("el programa de sellos está desactivado en este local")
    s, t = c.ej.api("POST", "/api/tarjeta", {})
    if s != 200:
        raise Falla(f"no se pudo crear una tarjeta (HTTP {s})")
    meta, importe = cfg["sellos_meta"], max(cfg["importe_minimo"], 1) + 1
    if meta > 40:
        raise Manual("el objetivo es demasiado alto para sellar a mano en una prueba")
    for _ in range(meta + 1):
        c.ej.api("POST", "/api/sellos/sellar", {"t": t["id"], "importe": importe})
    sellos = c.ej.api("GET", "/api/tarjeta?t=" + t["id"])[1]["sellos"]
    c.exige(sellos <= meta, f"la tarjeta queda en {sellos} de {meta} sellos: se ha sellado por encima del objetivo")
    return f"tras {meta + 1} sellos a mano: {sellos} de {meta}"


@caso("CA-19", "Sellos: si el navegador no puede leer códigos con la cámara, lo dice en vez de esconder el botón")
def ca19(c):
    p, _ = sellos_admin(c, init="delete window.BarcodeDetector;")
    t = texto(p, "#vista")
    c.exige(p.locator('[data-sel="camara"]').count() == 0, "(prueba mal montada: el botón de cámara sale sin BarcodeDetector)")
    c.exige(re.search(TEXTOS["camara_sin_soporte"], t, re.I) is not None,
            "sin BarcodeDetector el botón «Usar la cámara» desaparece sin explicar por qué")
    c.foto(p, "sellos-sin-camara")


@caso("CA-20", "Wallet: la pestaña Sellos dice en qué estado está cada canal y, si falta, qué falta y quién lo consigue, sin remitir a ficheros")
def ca20(c):
    p, _ = sellos_admin(c)
    caja = p.locator(".caja", has_text="Wallet del móvil")
    t = caja.first.inner_text() if caja.count() else ""
    canales = c.ej.api("GET", "/api/sellos/config")[1].get("canales", {})
    if not c.exige(bool(t), "no hay caja «Wallet del móvil»"):
        return
    c.exige(not re.search(r"PENDIENTE|\.md\b", t), "la nota remite a un fichero del repositorio (PENDIENTE.md)")
    c.exige("apple wallet" in t.lower() and "google wallet" in t.lower(), "no nombra Apple Wallet y Google Wallet")
    if not (canales.get("apple") and canales.get("google")):
        c.exige("apple developer" in t.lower() and re.search(TEXTOS["wallet_quien"], t, re.I) is not None,
                "no explica qué cuenta falta (Apple Developer, Google Wallet) ni quién la consigue")
        for canal, carpeta in (("apple", "wallet/apple"), ("google", "wallet/google")):
            if not canales.get(canal):
                c.exige(carpeta in t and "sellos.json" in t and "URL_PUBLICA" in t,
                        f"{canal}: no dice dónde poner las credenciales ({carpeta}, sellos.json, URL_PUBLICA), solo que faltan")
    else:
        c.exige(re.search(r"conectado|prueba", t, re.I) is not None, "no dice si el canal está conectado o en modo prueba")
    c.foto(p, "sellos-wallet")
    pm, _ = sellos_admin(c, VIEWPORTS[0][1])
    c.exige(pm.evaluate("document.documentElement.scrollWidth<=document.documentElement.clientWidth"),
            "a 360 px la pestaña Sellos se sale de la pantalla (¿ruta larga sin partir?)")
    return "canales: " + ", ".join(f"{k}={v or 'no disponible'}" for k, v in canales.items())


@caso("CA-21", "Formularios: las casillas del backoffice salen pegadas a su etiqueta (Sellos y Promociones)")
def ca21(c):
    for nom, tipo in VIEWPORTS:
        p, _ = sellos_admin(c, tipo)
        for tab in ("sel", "pro"):
            pestana(p, tab)
            malas = p.evaluate("""()=>[...document.querySelectorAll('#vista .campo>input[type=checkbox]')].filter(i=>{
              const s=[...i.closest('label').querySelectorAll('span:not(.nota)')][0], t=document.createRange();
              t.selectNodeContents(s);const r=t.getBoundingClientRect(), a=i.getBoundingClientRect();
              const mismaFila=a.top<r.bottom&&a.bottom>r.top;   // la casilla y el principio del texto, en la misma fila y juntos
              return !(mismaFila&&Math.abs(r.left-a.right)<=24&&r.left>=a.left)}).length""")
            c.exige(malas == 0, f"{nom}px, pestaña «{tab}»: {malas} casilla(s) fuera de la fila de su etiqueta o lejos de ella")
        c.foto(p, f"casilla-{nom}")


@caso("CA-22", "Avisos vacíos: una barra de aviso sin texto no se ve")
def ca22(c):
    p, _ = sellos_admin(c)
    for tab in ("sel", "pro"):
        pestana(p, tab)
        malos = p.evaluate("""()=>[...document.querySelectorAll('#vista .aviso')].filter(e=>!e.innerText.trim()&&e.getBoundingClientRect().height>0&&getComputedStyle(e).backgroundColor!=='rgba(0, 0, 0, 0)').length""")
        c.exige(malos == 0, f"pestaña «{tab}»: hay {malos} barra(s) de aviso con fondo pero sin texto")
        c.foto(p, f"aviso-{tab}")


@caso("CA-23", "Promociones: sin canal explica qué falta y cómo probar y no deja enviar; con canal de prueba, envía solo a quien dio permiso", tolera_4xx=True)
def ca23(c):
    canales = c.ej.canales()
    p = entrar_admin(c, ESCRITORIO)
    t = pestana(p, "pro")
    p.locator("#proTitulo").fill("QA-agente promoción")
    p.locator("#proTexto").fill("Prueba automática: no es una promoción real.")
    boton = p.locator('[data-pro="enviar"]')
    if not canales.get("email") and not (canales.get("wallet") or {}).get("apple") and not (canales.get("wallet") or {}).get("google"):
        aviso = texto(p, "#vista")
        c.exige(all(x in aviso for x in TEXTOS["promo_sin_canal"]), "no explica qué variables poner (BREVO_API_KEY…) ni que existe CORREO_MODO=prueba")
        c.exige("Wallet del móvil" in aviso, "el aviso de Wallet no dice dónde están los pasos para conectarlo (pestaña Sellos, «Wallet del móvil»)")
        c.exige(boton.is_disabled(), "con ningún canal, «Enviar promoción» sigue activo (debe estar desactivado con el motivo)")
        c.foto(p, "promociones-sin-canal")
        return "escenario sin canales"
    if canales.get("email") and c.ej.modo_prueba_correo():
        c.exige(p.locator("#proEmail").is_enabled(), "el canal de correo (prueba) sale desactivado")
        p.locator("#proWallet").uncheck() if p.locator("#proWallet").count() and not p.locator("#proWallet").is_disabled() else None
        if not c.ej.email:
            c.ej.email = f"{MARCA}-ficha@example.com"
            version = c.ej.ctx_api.request.get(BASE + "/api/permiso").json()["version"]
            c.ej.pedido_api("QA-agente CA-23", estado="entregado", permiso={"email": c.ej.email, "version": version})
            c.ej.confirmar_permiso(c.ej.email)
            p = entrar_admin(c, ESCRITORIO)
            pestana(p, "pro")
            p.locator("#proTitulo").fill("QA-agente promoción")
            p.locator("#proTexto").fill("Prueba automática: no es una promoción real.")
            p.locator("#proWallet").uncheck() if p.locator("#proWallet").count() and not p.locator("#proWallet").is_disabled() else None
        boton = p.locator('[data-pro="enviar"]')
        boton.click()  # el diálogo «¿Enviar ya la promoción?» se acepta en pagina()
        c.exige(not re.search(r"elige por dónde", texto(p, "#vista"), re.I), "«Enviar promoción» responde «Elige por dónde enviarla» con un canal disponible")
        espera(p, "document.querySelector('#vista').innerText.includes('Enviándose')", 10)
        p.locator('[data-pro="ver"]').first.click()
        espera(p, "/Enviado[^\\n]*\\(simulado\\)/.test(document.querySelector('#vista').innerText)", 15)
        c.exige(re.search(r"Enviado[^\n]*\(simulado\)", texto(p, "#vista")), "el registro no marca el envío como «Enviado (simulado)»")
        c.foto(p, "promociones-enviada")
        return "escenario con correo en modo prueba: «Enviado (simulado)» en el registro"
    raise Manual("hay un canal real (Brevo/Wallet): la prueba automática no envía promociones reales; comprobar a mano")


@caso("CA-24", "Clientes con permiso y bajas: la lista enseña a quien dio permiso con su fecha y a quien se dio de baja")
def ca24(c):
    if not c.ej.email:
        c.ej.email = f"{MARCA}-ficha@example.com"
        version = c.ej.ctx_api.request.get(BASE + "/api/permiso").json()["version"]
        c.ej.pedido_api("QA-agente CA-24", estado="entregado", permiso={"email": c.ej.email, "version": version})
        c.ej.confirmar_permiso(c.ej.email)
    for nom, tipo in VIEWPORTS:
        p = entrar_admin(c, tipo)
        t = pestana(p, "pro")
        c.exige("clientes con permiso y bajas" in t.lower(), f"{nom}px: no hay sección «Clientes con permiso y bajas»")
        if c.ej.modo_prueba_correo() or c.ej.es_apto(c.ej.email):   # en alta directa es apto aunque no haya canal de correo
            c.exige(c.ej.email in t and "con permiso" in t.lower(), f"{nom}px: el cliente de la prueba no sale «Con permiso»")
        else:   # con doble confirmación y sin canal de correo no hay confirmación posible: sale pendiente, nunca «Con permiso»
            c.exige(c.ej.email in t and "pendiente de confirmar" in t.lower(), f"{nom}px: el cliente sin confirmar no sale «Pendiente de confirmar»")
        c.sin_desborde(p, f"{nom}px promociones")
        c.foto(p, f"clientes-{nom}")


@caso("CA-25", "Cifras: salen las cuatro cifras del mes con su comparación")
def ca25(c):
    for nom, tipo in VIEWPORTS:
        p = entrar_admin(c, tipo)
        pestana(p, "cif")
        p.wait_for_selector("[data-kpi=qr]", timeout=15000)
        for k in ("qr", "tarjetas", "resenas", "repiten"):
            c.exige(p.locator(f"[data-kpi={k}] b").count() == 1, f"{nom}px: falta la cifra «{k}»")
        c.sin_desborde(p, f"{nom}px cifras")
        c.foto(p, f"cifras-{nom}")


@caso("CA-26", "Cifras: cada cifra explica cuándo cuenta, y si todo está a cero lo explica")
def ca26(c):
    p = entrar_admin(c, ESCRITORIO)
    pestana(p, "cif")
    p.wait_for_selector("[data-kpi=qr]", timeout=15000)
    sin = [k for k in ("qr", "tarjetas", "resenas", "repiten") if not re.search(TEXTOS["cifra_ayuda"], texto(p, f"[data-kpi={k}]"), re.I)]
    c.exige(not sin, "estas cifras no dicen «cuenta cuando…»: " + ", ".join(sin))
    valores = [texto(p, f"[data-kpi={k}] b").strip() for k in ("qr", "tarjetas", "resenas", "repiten")]
    if all(v in ("0", "–", "-") for v in valores):
        c.exige(re.search(TEXTOS["cifras_vacias"], texto(p, "#vista"), re.I) is not None, "todas las cifras están a cero y no se explica por qué")
    c.foto(p, "cifras-ayuda")


@caso("CA-27", "Cifras: el título dice el mes con nombre («octubre de 2026»), no «2026-10»")
def ca27(c):
    p = entrar_admin(c, ESCRITORIO)
    pestana(p, "cif")
    p.wait_for_selector("[data-kpi=qr]", timeout=15000)
    titulo = texto(p, "#vista .cab h2")
    c.exige(re.search(rf"({'|'.join(MESES)}) de \d{{4}}", titulo, re.I) is not None, f"el título es «{titulo}»: falta el mes con nombre")
    c.foto(p, "cifras-mes")


@caso("CA-28", "Reseña: si el local no tiene enlace de Google, el backoffice avisa y Cifras dice que no puede contar los clics")
def ca28(c):
    if c.ej.resena:
        p = entrar_admin(c, ESCRITORIO)
        pestana(p, "cif")
        c.exige(re.search(TEXTOS["resena_falta"], texto(p, "#vista"), re.I) is None, "hay enlace de reseña y Cifras avisa de que falta")
        return "este local tiene enlace de reseña: no hace falta el aviso"
    p = entrar_admin(c, ESCRITORIO)
    t = pestana(p, "cif")
    p.wait_for_selector("[data-kpi=resenas]", timeout=15000)
    caja = texto(p, "[data-kpi=resenas]")
    c.exige(re.search(TEXTOS["resena_falta"], caja, re.I) is not None, "Cifras no avisa de que «Clics a la reseña» no puede contar sin el enlace de reseña")
    c.exige(re.search(TEXTOS["resena_donde"], caja, re.I) is not None, "no dice dónde se pone el enlace de reseña")
    c.foto(p, "cifras-sin-resena")


@caso("CA-29", ".env.example documenta todas las variables, comentadas en castellano llano")
def ca29(c):
    ruta = os.path.join(REPO, ".env.example")
    if not os.path.exists(ruta):
        raise Manual("no hay copia del repositorio a mano (QA_REPO): comprobar .env.example a mano")
    lineas = open(ruta, encoding="utf-8").read().splitlines()
    leidas = set()
    for nombre in ["docker-compose.yml"] + [os.path.join("carta", f) for f in sorted(os.listdir(os.path.join(REPO, "carta"))) if f.endswith(".py")]:
        ruta_f = os.path.join(REPO, nombre)
        if os.path.isfile(ruta_f):
            texto_f = open(ruta_f, encoding="utf-8").read()
            leidas |= set(re.findall(r"\$\{([A-Z][A-Z0-9_]+)", texto_f))
            leidas |= set(re.findall(r"environ(?:\.get\(|\[)\s*['\"]([A-Z][A-Z0-9_]+)", texto_f))
            leidas |= set(re.findall(r"getenv\(\s*['\"]([A-Z][A-Z0-9_]+)", texto_f))
    INTERNAS = ("PUERTO", "ESCUCHAR", "CONFIAR_PROXY", "CARTA_RESTAURANTES", "CARTA_WEB", "WALLET_DIR")  # las fija la imagen
    c.exige(len(leidas) >= 15, f"solo se han encontrado {len(leidas)} variables en compose y app: ¿falla la lectura del repositorio?")
    for var in sorted(leidas):
        i = next((n for n, l in enumerate(lineas) if re.match(rf"\s*#?\s*{var}\b", l) or (var in INTERNAS and re.search(rf"\b{var}\b", l))), None)
        if i is None:
            c.fallos.append(f".env.example no documenta {var}")
        elif not any(l.lstrip().startswith("#") and len(l.strip("# ")) > 15 for l in lineas[max(0, i - 4):i + 3]):
            c.fallos.append(f"{var} no lleva un comentario explicativo")
        elif var in INTERNAS:
            continue
        elif not any("Probar" in l and ("Producción" in l or "Produccion" in l) for l in lineas[max(0, i - 4):i + 3]):
            c.fallos.append(f"{var} no dice el valor para probar y el de producción")


# ====================================================================== LO QUE AÚN NO EXISTE
@caso("CA-30", "Alérgenos: el dueño los marca por plato y la carta enseña el aviso fijo", tolera_4xx=True)
def ca30(c):
    AVISO = "Información facilitada por el restaurante; consulta al personal"
    c.ej.entrar_api()
    _, orig = c.ej.api("GET", "/api/datos")
    original = json.loads(json.dumps(orig))
    plato = next(x for x in orig["platos"] if x["id"] == c.ej.plato)
    try:
        # el servidor rechaza lo que no es uno de los 14
        malo = json.loads(json.dumps(orig))
        next(x for x in malo["platos"] if x["id"] == c.ej.plato)["alergenos"] = ["gluten", "kiwi"]
        s, j = c.ej.api("PUT", "/api/datos", malo)
        c.exige(s == 400 and "14 alérgenos" in str(j.get("error", "")), f"el servidor no rechaza un alérgeno inventado (HTTP {s})")
        esperado = {"marcados": ["eggs", "sesame"], "sin_declarar": [], "sin_revisar": None}
        textos = {"marcados": r"Huevos[\s\S]*Sésamo|Sésamo[\s\S]*Huevos", "sin_declarar": r"Sin alérgenos declarados", "sin_revisar": r"Consulta al personal"}
        for est, valor in esperado.items():
            _, d = c.ej.api("GET", "/api/datos")
            x = next(x for x in d["platos"] if x["id"] == c.ej.plato)
            x.pop("alergenos", None)
            if valor is not None:
                x["alergenos"] = valor
            s, j = c.ej.api("PUT", "/api/datos", d)
            if s != 200:
                raise Falla(f"no se pudo guardar el estado «{est}» (HTTP {s}): {j.get('error', '')}")
            nota = f"QA-agente CA-30 {est}"
            c.ej.pedido_api(nota, estado="nuevo")
            for nom, tipo in VIEWPORTS:
                p = abrir_carta(c, tipo)
                c.exige(AVISO in texto(p), f"{nom}px: falta el aviso fijo en la carta")
                p.locator(f'#lista [data-b="{c.ej.plato}"]').click()
                alg = texto(p, "#alg")
                c.exige(re.search(textos[est], alg) is not None, f"{nom}px, estado «{est}»: la carta dice «{alg[:80]}»")
                if est == "marcados":
                    c.exige(p.locator("#alg svg").count() == 2, f"{nom}px: faltan los iconos junto al texto")
                c.sin_desborde(p, f"{nom}px carta {est}")
                c.foto(p, f"carta-{est}-{nom}")
        # cocina ve los alérgenos del pedido
        k = entrar_cocina(c, ESCRITORIO)
        k.wait_for_selector("#tablero .col", timeout=15000)
        c.exige(espera(k, "document.querySelector('#tablero').innerText.includes('Consulta al personal')", 10), "la cocina no enseña «Consulta al personal» en el pedido sin revisar")
        c.exige("Sin alérgenos declarados" in texto(k, "#tablero"), "la cocina no enseña «Sin alérgenos declarados»")
        c.exige("Sésamo" in texto(k, "#tablero"), "la cocina no enseña los alérgenos marcados")
        c.foto(k, "cocina-1280")
        # backoffice: aviso con contador en la pestaña principal
        a = entrar_admin(c, ESCRITORIO)
        c.exige(a.locator("#nAlg").count() == 1, "falta el contador de platos sin revisar en la pestaña principal")
        c.foto(a, "admin-1280")
    finally:
        _, d = c.ej.api("GET", "/api/datos")
        original["version"] = d["version"]
        c.ej.api("PUT", "/api/datos", original)
    return "estados marcados / sin declarar / sin revisar en carta (360 y 1280), cocina y backoffice"


@caso("CA-31", "Idiomas: la interfaz cambia a inglés, catalán, chino, francés, alemán, italiano y portugués y la carta cae a castellano si falta un campo")
def ca31(c):
    # Automático: idioma de la primera visita por Accept-Language, diccionarios servidos y campos de la carta por idioma.
    # Manual (y por un nativo): que el chino esté bien escrito, ver docs/REVISION-CHINO.md.
    esperado = {"es-ES,es;q=0.9": "es", "en-US,en;q=0.8": "en", "ca,es;q=0.5": "ca", "zh-CN,zh;q=0.9": "zh", "fr-FR,fr;q=0.9": "fr",
                "de-DE,de;q=0.9": "de", "it-IT,it;q=0.9": "it", "pt-PT,pt;q=0.9": "pt", "nl-NL,nl;q=0.9": "es"}
    for cab, idioma in esperado.items():
        r = c.ej.ctx_api.request.get(BASE + "/", headers={"Accept-Language": cab})
        m = re.search(r'<meta name="gastro-idioma" content="([^"]*)"', r.text())
        c.exige(m is not None and m.group(1) == idioma, f"Accept-Language «{cab}»: la carta debería arrancar en «{idioma}» y dice «{m.group(1) if m else 'sin meta'}»")
    r = c.ej.ctx_api.request.get(BASE + "/idiomas.js")
    c.exige(r.status == 200 and "I18N" in r.text(), f"/idiomas.js no responde (HTTP {r.status})")
    for idioma in ("en", "ca", "zh", "fr", "de", "it", "pt"):
        r = c.ej.ctx_api.request.get(BASE + f"/i18n/{idioma}.js")
        c.exige(r.status == 200 and len(r.text()) > 1000, f"/i18n/{idioma}.js no responde con un diccionario (HTTP {r.status})")
    # el chino lleva caracteres chinos de verdad en el diccionario servido
    c.exige(re.search(r"[\u4e00-\u9fff]", c.ej.ctx_api.request.get(BASE + "/i18n/zh.js").text()) is not None, "el diccionario chino no lleva caracteres chinos")
    # la carta (datos.js) lleva los campos del plato por idioma y el castellano siempre presente
    r = c.ej.ctx_api.request.get(BASE + "/datos.js")
    m = re.search(r"window\.DATOS\s*=\s*(\{.*?\});\s*\n", r.text(), re.S)
    c.exige(m is not None, "datos.js no tiene el formato esperado")
    for plato in json.loads(m.group(1))["platos"]:
        for campo in ("n", "sec"):
            v = plato.get(campo)
            c.exige(isinstance(v, str) and v or isinstance(v, dict) and v.get("es"), f"el campo «{campo}» del plato «{plato.get('id')}» no tiene castellano")
    # El premio de la tarjeta de sellos sale en el idioma de la persona, no en castellano pegado en medio de otro idioma
    resumen = ""
    pub = c.ej.ctx_api.request.get(BASE + "/api/sellos")
    activo = pub.status == 200 and pub.json().get("activo")
    premios = (pub.json().get("premios") or {}) if activo else {}
    if activo:
        c.exige(bool(premios), "/api/sellos no da el premio por idioma (`premios`): saldría en castellano en los otros idiomas")
    if premios:
        for idioma in ("en", "ca", "zh", "fr", "de", "it", "pt"):
            c.exige(bool(premios.get(idioma)), f"/api/sellos no da el premio en «{idioma}»")
        if premios.get("es") == "Un detalle de la casa":   # el premio de fábrica debe venir traducido
            for idioma in ("en", "ca", "zh", "fr", "de", "it", "pt"):
                c.exige(premios[idioma] != premios["es"], f"el premio de fábrica sigue en castellano en «{idioma}»: «{premios[idioma]}»")
        tid = c.ej.tarjeta_qa()
        for idioma in ("en", "ca", "zh", "fr", "de", "it", "pt"):
            esperado = c.ej.api("GET", f"/api/tarjeta?t={tid}&lang={idioma}")[1]["premio"]
            c.exige(esperado == premios[idioma], f"/api/tarjeta en «{idioma}» da «{esperado}» y /api/sellos «{premios[idioma]}»")
            p = c.pagina(MOVIL)
            p.goto(f"{BASE}/tarjeta?t={tid}&lang={idioma}")
            p.wait_for_selector("#qr:not([hidden])", timeout=15000)
            cuerpo = texto(p)
            c.exige(premios[idioma] in cuerpo, f"tarjeta en «{idioma}»: no sale el premio «{premios[idioma]}»")
            c.exige(premios["es"] == premios[idioma] or premios["es"] not in cuerpo, f"tarjeta en «{idioma}»: el premio sale en castellano («{premios['es']}»)")
        resumen = "; premio de la tarjeta traducido en los siete idiomas"
    return "primera visita en los ocho idiomas (+nl cae a es), diccionarios servidos y datos con campos por idioma" + resumen


@caso("CA-32", "Exportación de pedidos: CSV/Excel por rango de días con la leyenda «no es una factura»", tolera_4xx=True)
def ca32(c):
    import csv, io, zipfile
    import xml.etree.ElementTree as ET
    fetch = lambda ruta: c.ej.ctx_api.request.fetch(BASE + ruta)
    s, _ = c.ej.api("GET", "/api/exportar")
    c.exige(s == 200, f"/api/exportar con sesión no responde (HTTP {s})")
    sin = c.ej.pw.request.new_context(ignore_https_errors=True)
    try:
        r = sin.get(BASE + "/api/exportar?formato=csv")
        c.exige(r.status == 401, f"sin sesión, /api/exportar debería dar 401 y da {r.status}")
    finally:
        sin.dispose()
    for q in ("desde=ayer&hasta=2026-01-02", "desde=2026-02-01&hasta=2026-01-01", "desde=2020-01-01&hasta=2026-01-01"):
        r = fetch("/api/exportar?" + q)
        c.exige(r.status == 400 and r.json().get("error"), f"fechas «{q}»: debería dar 400 con un mensaje y da {r.status}")
    antes = fetch("/api/exportar").json()
    _, datos = c.ej.api("GET", "/api/datos")
    precio = next(x for x in datos["platos"] if x["id"] == c.ej.plato)["p"]
    for i in range(3):
        c.ej.pedido_api(f"QA exportar {i}", estado="entregado")
    d = fetch("/api/exportar").json()
    c.exige(d["pedidos"] == antes["pedidos"] + 3, f"el resumen debería subir 3 pedidos y pasa de {antes['pedidos']} a {d['pedidos']}")
    c.exige(abs(d["total"] - antes["total"] - 3 * precio) < 0.005, f"el total no cuadra: {antes['total']} + 3×{precio} ≠ {d['total']}")
    q = f"desde={d['desde']}&hasta={d['hasta']}"
    r = fetch(f"/api/exportar?{q}&formato=csv")
    crudo = r.body()
    c.exige(crudo.startswith(b"\xef\xbb\xbf"), "el CSV no empieza por BOM UTF-8")
    filas = list(csv.reader(io.StringIO(crudo.decode("utf-8-sig"), newline=""), delimiter=";"))
    c.exige("Este documento no es una factura" in filas[0][0], "el CSV no lleva el aviso «no es una factura» en la primera línea")
    c.exige(re.fullmatch(r'attachment; filename="pedidos_\d{4}-\d\d-\d\d_a_\d{4}-\d\d-\d\d\.csv"', r.headers.get("content-disposition", "")) is not None, "nombre de fichero CSV no neutro")
    suma = round(sum(float(f[10].replace(",", ".")) for f in filas[2:] if f[10]), 2)
    c.exige(abs(suma - d["total"]) < 0.005, f"el CSV suma {suma} y el resumen {d['total']}")
    z = zipfile.ZipFile(io.BytesIO(fetch(f"/api/exportar?{q}&formato=xlsx").body()))
    for n in z.namelist():
        ET.fromstring(z.read(n))
    c.exige("no es una factura" in z.read("xl/workbook.xml").decode() and "no es una factura" in z.read("xl/worksheets/sheet1.xml").decode(), "el Excel no lleva el aviso en la hoja y en su nombre")
    vacio = fetch("/api/exportar?desde=2000-01-01&hasta=2000-01-31&formato=csv").body().decode("utf-8-sig")
    c.exige(len(vacio.strip().splitlines()) == 2, "un rango sin pedidos debería dar solo el aviso y la cabecera")
    for nom, tipo in VIEWPORTS:
        a = entrar_admin(c, tipo)
        t = pestana(a, "exp")
        c.exige(a.locator("[data-resumen]").count() == 1 or espera(a, "document.querySelector('[data-resumen]')", 10), f"{nom}px: Exportar no enseña el resumen del rango ({t[:80]!r})")
        c.exige("no es una factura" in texto(a, "#vista"), f"{nom}px: la ayuda no dice que no es una factura")
        with a.expect_download() as dl:
            a.locator('[data-exp="csv"]').click()
        c.exige(re.fullmatch(r"pedidos_\d{4}-\d\d-\d\d_a_\d{4}-\d\d-\d\d\.csv", dl.value.suggested_filename) is not None, f"{nom}px: nombre del CSV descargado: {dl.value.suggested_filename}")
        with a.expect_download() as dl:
            a.locator('[data-exp="xlsx"]').click()
        c.exige(dl.value.suggested_filename.endswith(".xlsx"), f"{nom}px: nombre del Excel descargado: {dl.value.suggested_filename}")
        c.foto(a, f"exportar-{nom}")
        a.locator("#expDesde").fill("2000-01-01")
        a.locator("#expHasta").fill("2000-01-31")
        c.exige(espera(a, "document.querySelector('[data-vacio]')", 10), f"{nom}px: un rango sin pedidos no enseña el aviso")
        c.exige("No hay pedidos" in texto(a, "#vista"), f"{nom}px: el aviso de rango vacío no está en castellano llano")
        a.locator("#expDesde").fill("2000-02-01")
        c.exige(espera(a, "document.querySelector('[data-error]')", 10), f"{nom}px: «desde» posterior a «hasta» no enseña el error")
        c.sin_desborde(a, f"{nom}px Exportar")
        c.foto(a, f"exportar-vacio-{nom}")
    return f"{d['pedidos']} pedidos · {d['total']} € · CSV y Excel con aviso; rango vacío y fechas malas explicados"


# ====================================================================== TRANSVERSALES
@caso("CA-40", "/salud responde JSON con ok y con la versión desplegada")
def ca40(c):
    r = c.ej.ctx_api.request.get(BASE + "/salud")
    j = r.json()
    c.exige(r.status == 200 and j.get("ok") is True, f"/salud no responde ok (HTTP {r.status})")
    c.exige("version" in j and isinstance(j["version"], str), "/salud no trae el campo «version»")
    esperada = os.environ.get("QA_VERSION_ESPERADA")
    if esperada:
        c.exige(j.get("version") == esperada, "la versión desplegada no es la esperada")
    return "version=" + (j.get("version") or "(vacía)")[:12]


@caso("CA-41", "Recorrido completo (carta, cocina, tarjeta, baja y las diez pestañas) sin errores, sin scroll horizontal y sin hablar con otro host")
def ca41(c):
    for nom, tipo in VIEWPORTS:
        p = abrir_carta(c, tipo)
        c.sin_desborde(p, f"{nom}px carta")
        k = entrar_cocina(c, tipo)
        k.wait_for_selector("#tablero .col", timeout=15000)
        c.sin_desborde(k, f"{nom}px cocina")
        t = c.pagina(tipo)
        t.goto(f"{BASE}/tarjeta")
        espera(t, "document.querySelector('#msg') && document.querySelector('#msg').innerText!=='Cargando tu tarjeta…'", 10)
        c.sin_desborde(t, f"{nom}px /tarjeta")
        a = entrar_admin(c, tipo)
        for tab, _ in PESTANAS:
            pestana(a, tab)
            c.sin_desborde(a, f"{nom}px pestaña {tab}")
        c.exige(a.evaluate("typeof window.qrcode === 'function'"), f"{nom}px: la librería de QR no se carga desde el propio servidor")


# ====================================================================== ejecución
def resumen(res):
    ancho = max(len(r["titulo"]) for r in res)
    print(f"\n{'ID':6} {'estado':7} {'issue':6} detalle")
    print("-" * 110)
    for r in res:
        print(f"{r['id']:6} {r['estado']:7} {('#' + str(r['issue'])) if r['issue'] else '-':6} {r['titulo'][:60]} :: {r['detalle'][:140]}")
    n = {e: sum(1 for r in res if r["estado"] == e) for e in ("pasa", "falla", "manual")}
    print("-" * 110)
    print(f"pasa {n['pasa']} · falla {n['falla']} · manual {n['manual']}")


def principal():
    con = []
    with sync_playwright() as pw:
        ej = Ejecucion(pw)
        try:
            pre = ej.ctx_api.request.get(BASE + "/salud")
        except Exception as e:   # noqa: BLE001
            print(f"CA-00 falla: no se puede abrir el sitio ({str(e)[:100]})")
            sys.exit(1)
        if pre.status == 401:
            res = [dict(id="CA-00", estado="falla", detalle="el sitio exige usuario y contraseña (HTTP 401): faltan QA_BASIC_USUARIO / QA_BASIC_CLAVE", captura=None, issue=None, titulo="Acceso al sitio")]
            json.dump([{k: v for k, v in r.items() if k != "titulo"} for r in res], open(f"{SALIDA}/resultado.json", "w"), ensure_ascii=False, indent=1)
            resumen(res)
            sys.exit(1)
        ej.preparar()
        for meta in CASOS:
            if SOLO and meta["id"] not in SOLO:
                continue
            c = Caso(ej, meta)
            estado, detalle = "pasa", ""
            try:
                detalle = meta["fn"](c) or ""
            except Manual as m:
                estado, detalle = "manual", str(m)
            except Falla as f:
                c.fallos.append(str(f))
            except Exception as e:   # noqa: BLE001
                c.fallos.append(f"error inesperado: {type(e).__name__}: {str(e).splitlines()[0][:140] if str(e) else ''}")
                traceback.print_exc(file=sys.stderr)
            c.fallos += sorted(set(c.errores))[:4]
            if c.fallos:
                estado, detalle = "falla", "; ".join(c.fallos)
            c.cerrar()
            con.append(dict(id=meta["id"], estado=estado, detalle=detalle, captura=c.captura, issue=meta["issue"], titulo=meta["titulo"]))
            print(f"{meta['id']} {estado}", flush=True)
        ej.cerrar()
    json.dump([{k: v for k, v in r.items() if k != "titulo"} for r in con], open(f"{SALIDA}/resultado.json", "w"), ensure_ascii=False, indent=1)
    resumen(con)
    sys.exit(1 if any(r["estado"] == "falla" for r in con) else 0)


principal()

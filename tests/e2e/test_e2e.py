# SPDX-License-Identifier: EUPL-1.2
"""E2E: Playwright/Chromium contra el docker compose levantado (por Caddy, HTTPS). Lo lanza tests/e2e.sh.
Varios móviles a 360 px pidiendo a la vez + un escritorio a 1280 px, cocina que los mueve, reseña, tarjeta de sellos,
backoffice (todas las pestañas a 360 y 1280 px), promoción con baja. Cada comprobación imprime OK o FALLO; sale con 1 si falla alguna.
CARTA_URL, CARTA_CLAVE, SALIDA (carpeta de capturas), CONFIRMACION_DOBLE («1»: prueba la doble confirmación; por defecto, alta directa)."""
import asyncio, http.cookiejar, json, os, re, ssl, sys, time, urllib.error, urllib.request
from playwright.async_api import async_playwright

URL = os.environ["CARTA_URL"].rstrip("/")
CLAVE = os.environ["CARTA_CLAVE"]
SALIDA = os.environ.get("SALIDA", "/tmp/e2e")
DOBLE = os.environ.get("CONFIRMACION_DOBLE", "").strip().lower() in ("1", "true", "si", "sí", "yes")
os.makedirs(SALIDA, exist_ok=True)
MOVIL = dict(viewport={"width": 360, "height": 740}, device_scale_factor=2, is_mobile=True, has_touch=True, locale="es-ES")
ESCRITORIO = dict(viewport={"width": 1280, "height": 800}, locale="es-ES")
RESENA = "https://search.google.com/local/writereview?placeid=ChIJ_PRUEBA_E2E"

fallos, total = [], 0


def comprobar(nombre, cond, detalle=""):
    global total
    total += 1
    if cond:
        print(f"OK    {nombre}", flush=True)
    else:
        fallos.append(nombre)
        print(f"FALLO {nombre} {detalle}", flush=True)
    return bool(cond)


# ---------- API (como el dueño en el backoffice, sin navegador) ----------
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


class Api:
    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), urllib.request.HTTPSHandler(context=CTX))

    def json(self, metodo, ruta, cuerpo=None):
        req = urllib.request.Request(URL + ruta, data=None if cuerpo is None else json.dumps(cuerpo).encode(), method=metodo, headers={"Content-Type": "application/json"})
        try:
            with self.op.open(req, timeout=15) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")


API = Api()


async def esperar(f, seg=20, paso=0.3):
    fin = time.time() + seg
    while time.time() < fin:
        v = await asyncio.to_thread(f)
        if v:
            return v
        await asyncio.sleep(paso)
    return None


def pedidos():
    return API.json("GET", "/api/pedidos")[1]["pedidos"]


# ---------- ayudas de navegador ----------
class Pagina:
    """Una página con registro de errores de consola/JS y utilidades."""

    def __init__(self, page, nombre):
        self.p, self.nombre, self.errores = page, nombre, []
        page.on("pageerror", lambda e: self.errores.append(f"JS: {e}"))
        # el service worker no se registra con el certificado propio de Caddy (solo pasa con DOMINIO=localhost): no es un fallo de la app
        page.on("console", lambda m: m.type == "error" and "SSL certificate error" not in m.text and self.errores.append(f"consola: {m.text}"))
        # ERR_ABORTED = la página navega a otra mientras un fetch sin esperar su cuerpo sigue abierto: normal, no es un fallo
        page.on("requestfailed", lambda r: "ERR_ABORTED" not in str(r.failure) and self.errores.append(f"red: {r.url} {r.failure}"))
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

    async def desborda(self):
        return await self.p.evaluate("document.documentElement.scrollWidth - window.innerWidth")

    async def sin_desborde(self, que):
        d = await self.desborda()
        return comprobar(f"{self.nombre}: {que} sin scroll horizontal", d <= 1, f"(sobran {d}px)")

    async def foto(self, nombre):
        await self.p.screenshot(path=f"{SALIDA}/{nombre}.png", full_page=False)

    def sin_errores(self, que):
        comprobar(f"{self.nombre}: {que} sin errores de consola ni de red", not self.errores, str(self.errores[:3]))
        self.errores.clear()


async def contexto(browser, tipo, **extra):
    # bypass_csp: wait_for_function de Playwright evalúa texto con eval(), que la CSP de la app prohíbe a propósito; la CSP se prueba en tests/privacidad.sh
    return await browser.new_context(ignore_https_errors=True, bypass_csp=True, **(MOVIL if tipo == "movil" else ESCRITORIO), **extra)


async def nueva(browser, tipo, nombre, **extra):
    ctx = await contexto(browser, tipo, **extra)
    await ctx.route("**/search.google.com/**", lambda r: r.fulfill(status=200, content_type="text/html", body="<p>Google (simulado)</p>"))
    return ctx, Pagina(await ctx.new_page(), nombre)


# ---------- la carta: un cliente pide ----------
async def pedir(browser, tipo, nombre, mesa, indice, qr=True, quitar=True, permiso_email=None, esperado=None):
    """Abre la carta, monta el plato nº `indice` (quitando un ingrediente), lo envía y espera «Recibido». Devuelve (ctx, pagina, texto)."""
    ctx, pg = await nueva(browser, tipo, nombre)
    p = pg.p
    await p.goto(f"{URL}/?mesa={mesa}" if qr else f"{URL}/")
    await p.wait_for_selector("#lista [data-b]")
    await pg.sin_desborde("carta")
    item = p.locator("#lista [data-b]").nth(indice)
    await item.click()
    texto = (await p.locator("#nombre").inner_text()).strip()
    quitado = None
    if quitar:
        chip = p.locator("#chips .chip:not(.off):not(.extra) [data-t]").first
        quitado = await chip.get_attribute("aria-label")
        await chip.click()
        comprobar(f"{nombre}: quitar un ingrediente marca «Personalizado»", await p.locator("#lista .mod").count() >= 1)
    await p.locator("#add").click()
    await p.wait_for_function("document.querySelector('#lineas').children.length>=1")
    if tipo == "movil":
        await p.locator("#verPedido").click()
    await p.locator("#enviar").click()
    await p.wait_for_selector("#dlgEnviar[open]")
    if not qr:
        await p.locator("#dlgMesaSel").select_option(str(mesa))
    # el diálogo (con la casilla de permiso) cabe en la pantalla y la casilla viene sin marcar
    caja = await p.locator("#dlgEnviar").bounding_box()
    vw = (MOVIL if tipo == "movil" else ESCRITORIO)["viewport"]["width"]
    comprobar(f"{nombre}: el diálogo de envío cabe en {vw}px", caja and caja["x"] >= 0 and caja["x"] + caja["width"] <= vw + 1, str(caja))
    casilla = p.locator("#dlgPermisoCasilla")
    await casilla.wait_for(state="visible")
    comprobar(f"{nombre}: la casilla de permiso viene SIN marcar", not await casilla.is_checked())
    comprobar(f"{nombre}: el texto de la casilla se lee entero", (await p.locator("#dlgPermisoTexto").inner_text()).strip().endswith(("baja.", "baja")) or len(await p.locator("#dlgPermisoTexto").inner_text()) > 80)
    if permiso_email:
        await p.locator("#dlgEmail").fill(permiso_email)
        await casilla.check()
        await pg.foto(f"{nombre}-dialogo")
    await p.locator("#dlgNota").fill(f"E2E {nombre}")
    await p.locator("#dlgOk").click()
    await p.wait_for_selector(".env[data-pedido]", timeout=15000)
    env = await p.locator(".env[data-pedido]").first.inner_text()
    comprobar(f"{nombre}: el cliente ve su pedido «Recibido»", "recibido" in env.lower(), env)
    comprobar(f"{nombre}: el pedido sale con la mesa {mesa}", f"mesa {mesa}" in env.lower(), env)
    await pg.sin_desborde("tras enviar")
    return ctx, pg, texto, quitado


# ---------- cocina ----------
async def cocina_login(browser, tipo, nombre):
    ctx, pg = await nueva(browser, tipo, nombre)
    await pg.p.goto(f"{URL}/cocina")
    await pg.p.locator("#clave").fill(CLAVE)
    await pg.p.locator("#formLogin button[type=submit]").click()
    await pg.p.wait_for_selector("#tablero .col")
    return ctx, pg


async def mover(pg, pid, a):
    """Pulsa el botón de cocina que lleva el pedido al estado `a` y espera a que el servidor lo refleje."""
    await pg.p.locator(f'button[data-mover="{pid}"][data-a="{a}"]').click()
    return await esperar(lambda: next((x for x in pedidos() if x["id"] == pid and x["estado"] == a), None), 10)


# ---------- backoffice ----------
async def admin_login(browser, tipo, nombre):
    ctx, pg = await nueva(browser, tipo, nombre)
    await pg.p.goto(f"{URL}/admin")
    await pg.p.locator("#clave").fill(CLAVE)
    await pg.p.locator("#formLogin button[type=submit]").click()
    await pg.p.wait_for_selector("#vista .grupo, #vista .cab")
    return ctx, pg


async def principal(pw):
    browser = await pw.chromium.launch()
    try:
        await escenarios(browser)
    finally:
        await browser.close()


async def escenarios(browser):
    # ===== 0. preparación por API =====
    c, _ = API.json("POST", "/api/login", {"clave": CLAVE})
    comprobar("backoffice: login por API", c == 200)
    API.json("PUT", "/api/sellos/config", {"activo": True, "sellos_meta": 8, "premio": "Un detalle de la casa", "importe_minimo": 5})
    API.json("POST", "/api/aceptar", {"aceptar_pedidos": True})
    comprobar("arranca sin pedidos de pruebas anteriores", not pedidos())

    # ===== 1. la carta, vacía, a 360 y 1280 =====
    for tipo, nom in (("movil", "carta-360"), ("escritorio", "carta-1280")):
        ctx, pg = await nueva(browser, tipo, nom)
        await pg.p.goto(f"{URL}/?mesa=1")
        await pg.p.wait_for_selector("#lista [data-b]")
        comprobar(f"{nom}: hay platos en la carta", await pg.p.locator("#lista [data-b]").count() >= 5)
        comprobar(f"{nom}: se ve «Mesa 1» del QR", "mesa 1" in (await pg.p.locator("#mesaTag").inner_text()).lower())
        comprobar(f"{nom}: sin marcadores {{{{…}}}} sin rellenar", "{{" not in await pg.p.content())
        await pg.sin_desborde("carta")
        await pg.foto(nom)
        pg.sin_errores("carta")
        await ctx.close()

    # ===== 2. seis móviles a 360 px + un escritorio a 1280 px piden A LA VEZ =====
    correo = f"e2e{int(time.time())}@example.com"
    trabajos = [
        pedir(browser, "movil", "movil1", 1, 0, permiso_email=correo),
        pedir(browser, "movil", "movil2", 2, 1),
        pedir(browser, "movil", "movil3", 3, 2),
        pedir(browser, "movil", "movil4", 4, 3, quitar=False),
        pedir(browser, "movil", "movil5", 5, 4),
        pedir(browser, "movil", "movil6", 6, 5, qr=False),   # sin QR: elige la mesa de la lista
        pedir(browser, "escritorio", "pc1280", 7, 6),
    ]
    res = await asyncio.gather(*trabajos, return_exceptions=True)
    sesiones = {}
    for r, nom in zip(res, ["movil1", "movil2", "movil3", "movil4", "movil5", "movil6", "pc1280"]):
        if isinstance(r, Exception):
            comprobar(f"{nom}: pide sin fallar", False, repr(r))
        else:
            sesiones[nom] = r
    lista = await esperar(lambda: (p := pedidos()) and len(p) == 7 and p, 15)
    comprobar("cocina recibe los 7 pedidos simultáneos", lista and len(lista) == 7, str(len(pedidos())))
    lista = lista or pedidos()
    comprobar("los 7 pedidos tienen número distinto", len({x["numero"] for x in lista}) == len(lista))
    comprobar("cada pedido está en su mesa (1 a 7)", sorted(x["mesa"] for x in lista) == [1, 2, 3, 4, 5, 6, 7])
    por_mesa = {x["mesa"]: x for x in lista}
    comprobar("el pedido sin QR llegó como «manual»; los de QR como «qr»",
              por_mesa.get(6, {}).get("via") == "manual" and all(por_mesa[m].get("via") == "qr" for m in (1, 2, 3, 4, 5, 7) if m in por_mesa), str({m: x.get("via") for m, x in por_mesa.items()}))
    comprobar("el ingrediente quitado llega a cocina (movil1: «sin»)", any(l.get("sin") for l in por_mesa.get(1, {}).get("lineas", [])), json.dumps(por_mesa.get(1, {}).get("lineas")))
    comprobar("movil4 (sin cambios) no lleva «sin» ni extras", not any(l.get("sin") or l.get("extra") for l in por_mesa.get(4, {}).get("lineas", [])))
    comprobar("la nota del cliente llega a cocina", por_mesa.get(2, {}).get("nota") == "E2E movil2")
    ficha = next((x for x in API.json("GET", "/api/clientes")[1]["clientes"] if x["email"] == correo), None)
    if DOBLE:   # CONFIRMACION_DOBLE=1 exportada al lanzar e2e.sh: flujo con correo de confirmación
        comprobar("movil1: antes de confirmar por correo está pendiente y NO es apto", ficha and not ficha["apto_marketing"] and ficha.get("pendiente"), str(ficha)[:200])
        conf = await esperar(lambda: next((m for m in API.json("GET", "/api/promociones/simulador")[1]["correos"]
                                           if m["para"] == correo and not str(m.get("asunto", "")).startswith("Publicidad:")), None), 20)
        tok = re.search(r"/confirmar\?t=([\w\-]+)", json.dumps(conf or {}))
        comprobar("movil1: el correo de confirmación trae el enlace", bool(tok), json.dumps(conf)[:300])
        if tok:
            API.json("POST", "/api/confirmar", {"token": tok.group(1)})
        ficha = next((x for x in API.json("GET", "/api/clientes")[1]["clientes"] if x["email"] == correo), None)
    else:   # por defecto: alta directa, apto al instante y sin correo de confirmación
        comprobar("movil1: con la casilla marcada es apto al instante (alta directa)", ficha and ficha["apto_marketing"] and not ficha.get("pendiente"), str(ficha)[:200])
        comprobar("movil1: en alta directa no se manda correo de confirmación",
                  not any(m["para"] == correo and not str(m.get("asunto", "")).startswith("Publicidad:") for m in API.json("GET", "/api/promociones/simulador")[1]["correos"]))
    comprobar("movil1: el permiso queda guardado con su prueba y es apto", ficha and ficha["apto_marketing"] and ficha["permisos"][0]["texto"], str(ficha)[:200])
    comprobar("solo movil1 dio correo: hay 1 cliente con ese correo y ninguno más de la prueba",
              sum(1 for x in API.json("GET", "/api/clientes")[1]["clientes"] if x["email"].startswith("e2e")) == 1)

    # ===== 3. cocina (1280 px y 360 px) mueve los pedidos; los móviles lo ven =====
    ctx_k, kitchen = await cocina_login(browser, "escritorio", "cocina-1280")
    await kitchen.p.wait_for_function("document.querySelectorAll('section[data-e=nuevo] article.ped').length===7", timeout=15000)
    comprobar("cocina 1280: los 7 pedidos aparecen en «Nuevos»", True)
    comprobar("cocina 1280: se ven las notas y las mesas",
              "E2E movil2" in await kitchen.p.locator("#tablero").inner_text() and "mesa" in (await kitchen.p.locator("#tablero").inner_text()).lower())
    await kitchen.foto("cocina-1280-nuevos")
    kitchen.sin_errores("cocina 1280")
    ctx_k2, kitchen2 = await cocina_login(browser, "movil", "cocina-360")
    await kitchen2.p.wait_for_selector("article.ped")
    await kitchen2.foto("cocina-360-nuevos")
    comprobar("cocina 360: los botones de pasar de estado se pueden tocar (alto ≥ 40px)",
              (await kitchen2.p.locator("button.paso").first.bounding_box())["height"] >= 40)
    await ctx_k2.close()

    ids = {m: x["id"] for m, x in por_mesa.items()}
    for m in sorted(ids):
        await mover(kitchen, ids[m], "preparando")
    comprobar("cocina: todos pasan a «En preparación»", all(x["estado"] == "preparando" for x in pedidos()))
    await kitchen.p.wait_for_function("document.querySelectorAll('section[data-e=preparando] article.ped').length===7")
    comprobar("cocina 1280: en preparación se ven los ingredientes numerados", await kitchen.p.locator("ol.montaje").count() >= 1)
    await kitchen.foto("cocina-1280-preparando")
    # los móviles se enteran solos (consultan cada 5 s)
    for nom, (ctx, pg, *_resto) in sesiones.items():
        await pg.p.wait_for_function("document.querySelector('.env[data-e]').dataset.e==='preparando'", timeout=15000)
        comprobar(f"{nom}: ve «En preparación» sin recargar", "en preparación" in (await pg.p.locator(".env[data-pedido]").first.inner_text()).lower())
    for m in sorted(ids):
        await mover(kitchen, ids[m], "listo")
    await sesiones["movil1"][1].p.wait_for_function("document.querySelector('#toast').classList.contains('show') && /listo/i.test(document.querySelector('#toast').textContent)", timeout=15000)
    comprobar("movil1: el aviso «¡Pedido N listo!» sale en pantalla",
              "listo" in (await sesiones["movil1"][1].p.locator("#toast").inner_text()).lower())
    await sesiones["movil1"][1].foto("movil1-listo")
    # no hay reseña antes de servido
    comprobar("movil2: antes de servir NO hay botón de reseña", await sesiones["movil2"][1].p.locator(".env a.resena").count() == 0)
    for m in sorted(ids):
        await mover(kitchen, ids[m], "entregado")
    comprobar("cocina: todos servidos", all(x["estado"] == "entregado" for x in pedidos()))

    # ===== 4. reseña de Google: mismo botón y mismo enlace para todos, solo en «Servido» =====
    hrefs = set()
    for nom, (ctx, pg, *_resto) in sesiones.items():
        await pg.p.wait_for_function("document.querySelector('.env[data-e=entregado]')", timeout=15000)
        a = pg.p.locator(".env[data-e=entregado] a.resena").first
        await a.wait_for(state="visible", timeout=5000)
        hrefs.add(await a.get_attribute("href"))
        comprobar(f"{nom}: «Servido» + botón «Dejar una reseña en Google»", "reseña" in (await a.inner_text()).lower())
    comprobar("la reseña es el MISMO enlace para los 7 clientes (sin filtrar ni incentivar)", hrefs == {RESENA}, str(hrefs))
    textos = " ".join([await sesiones["movil1"][1].p.locator("#enviados").inner_text()]).lower()
    comprobar("la carta no pregunta si gustó ni ofrece nada por reseñar", not re.search(r"descuento|regalo|premio por|te ha gustado|valora|puntúa|estrellas", textos.replace("con 8: un detalle de la casa", "")), textos[:200])
    await sesiones["movil1"][1].p.locator("#barra").scroll_into_view_if_needed()
    await sesiones["movil1"][1].foto("movil1-servido-resena")
    await sesiones["movil1"][1].sin_desborde("pedido servido con reseña")
    async with sesiones["movil1"][0].expect_page() as nueva_pag:
        await sesiones["movil1"][1].p.locator(".env[data-e=entregado] a.resena").first.click()
    popup = await nueva_pag.value
    comprobar("clic en la reseña abre el enlace de Google", popup.url == RESENA, popup.url)
    await popup.close()

    # ===== 5. tarjeta de sellos: móvil la crea tras el pedido servido; el sello llega solo =====
    m2 = sesiones["movil2"][1]
    await m2.p.locator("#tarjetaNueva").click()
    await m2.p.wait_for_url(re.compile(r"/tarjeta\?t="), timeout=15000)
    codigo = m2.p.url.split("t=")[1]
    await m2.p.wait_for_selector("#qr:not([hidden])", timeout=15000)
    sellos = await m2.p.locator("#sellos").inner_text()
    comprobar("tarjeta 360: el pedido ya servido sella en el acto (1 sello)", await esperar(lambda: API.json("GET", "/api/tarjeta?t=" + codigo)[1].get("sellos") == 1, 10), sellos)
    comprobar("tarjeta 360: se ve el QR y el código", await m2.p.locator("#qr").is_visible() and bool((await m2.p.locator("#codigo").inner_text()).strip()))
    await m2.sin_desborde("tarjeta")
    await m2.foto("tarjeta-360")
    cuerpo = (await m2.p.locator("body").inner_text()).lower()
    comprobar("tarjeta 360: ofrece Apple y Google Wallet (modo prueba)", "apple wallet" in cuerpo and "google wallet" in cuerpo, cuerpo[:300])
    comprobar("tarjeta 360: es anónima (no pide ni enseña correo)", "@" not in cuerpo and "correo" not in cuerpo.replace("sin correo", ""))
    m2.sin_errores("tarjeta")
    ctx_t, tpc = await nueva(browser, "escritorio", "tarjeta-1280")
    await tpc.p.goto(f"{URL}/tarjeta?t={codigo}")
    await tpc.p.wait_for_selector("#qr:not([hidden])")
    await tpc.sin_desborde("tarjeta")
    await tpc.foto("tarjeta-1280")
    await ctx_t.close()

    # ===== 6. backoffice a 1280 y 360 px =====
    for tipo, nom in (("escritorio", "admin-1280"), ("movil", "admin-360")):
        ctx_a, adm = await admin_login(browser, tipo, nom)
        for tab, esperado in (("boc", "Nuevo plato"), ("pic", "Nueva ración"), ("ing", "Nuevo ingrediente"), ("mes", "Mesas"),
                              ("sel", "Tarjeta de sellos"), ("pro", "Promociones"), ("cif", "Cifras"), ("exp", "Exportar pedidos"),
                              ("onl", "Pedidos online"), ("res", "Reservas")):
            await adm.p.locator(f'.tab[data-tab="{tab}"]').click()
            await adm.p.wait_for_function("!document.querySelector('#vista').innerText.includes('Cargando')", timeout=15000)
            await adm.p.wait_for_function("s=>document.querySelector('#vista').innerText.toLowerCase().includes(s.toLowerCase())", arg=esperado, timeout=15000)
            await adm.sin_desborde(f"pestaña {tab}")
            await adm.foto(f"{nom}-{tab}")
        adm.sin_errores("backoffice")
        if tipo == "escritorio":
            # Cifras reales de lo que acabamos de hacer
            await adm.p.locator('.tab[data-tab="cif"]').click()
            await adm.p.wait_for_selector("[data-kpi=qr]")
            kpi = {k: (await adm.p.locator(f"[data-kpi={k}] b").first.inner_text()).strip() for k in ("qr", "tarjetas", "resenas", "repiten")}
            comprobar("Cifras: 1 clic a la reseña, 1 tarjeta, pedidos por QR 6 de 7 (85,7 %)", kpi["resenas"] == "1" and kpi["tarjetas"] == "1" and kpi["qr"].startswith("85,7"), str(kpi))
            # Caja: buscar la tarjeta por su código y sellar a mano
            await adm.p.locator('.tab[data-tab="sel"]').click()
            await adm.p.wait_for_selector("#selCodigo")
            await adm.p.locator("#selCodigo").fill(codigo)
            await adm.p.locator('[data-sel="buscar"]').click()
            await adm.p.wait_for_function("document.querySelector('#vista').innerText.includes('1 de 8 sellos')", timeout=10000)
            comprobar("Caja: encuentra la tarjeta (1 de 8 sellos)", True)
            await adm.p.locator("#selImporte").fill("12")
            await adm.p.locator('[data-sel="sellar"]').click()
            await adm.p.wait_for_function("document.querySelector('#vista').innerText.includes('2 de 8 sellos')", timeout=10000)
            comprobar("Caja: «Sellar en caja» suma el sello (2 de 8)", API.json("GET", "/api/tarjeta?t=" + codigo)[1]["sellos"] == 2)
            await adm.foto("admin-1280-caja")
        await ctx_a.close()

    # ===== 7. backoffice cambia un precio y la carta lo refleja =====
    ctx_a, adm = await admin_login(browser, "escritorio", "admin-precio")
    campo = adm.p.locator('input[data-campo="p"][data-tipo="boc"]').first
    antes = await campo.input_value()
    await campo.fill("9.99")
    await campo.dispatch_event("change")
    await adm.p.locator("#guardar").click()
    await adm.p.wait_for_function("document.querySelector('#guardar').disabled", timeout=15000)
    ctx_c, carta = await nueva(browser, "movil", "carta-precio")
    await carta.p.goto(f"{URL}/?mesa=1")
    await carta.p.wait_for_selector("#lista [data-b]")
    comprobar("backoffice → carta: el precio nuevo (9,99 €) sale en la carta", "9,99" in await carta.p.locator("#lista [data-b]").first.inner_text())
    await campo.fill(antes)
    await campo.dispatch_event("change")
    await adm.p.locator("#guardar").click()
    await adm.p.wait_for_function("document.querySelector('#guardar').disabled", timeout=15000)

    # ===== 8. cerrar pedidos desde el backoffice: la carta lo avisa y no deja enviar =====
    await adm.p.locator("#aceptar").click()
    await adm.p.wait_for_function("document.querySelector('#aceptar').textContent.includes('CERRADOS')", timeout=10000)
    await carta.p.reload()
    await carta.p.wait_for_selector("#lista [data-b]")
    await carta.p.locator("#lista [data-b]").first.click()
    await carta.p.locator("#add").click()
    await carta.p.wait_for_selector("#cerrado:not([hidden])", timeout=10000)
    comprobar("cerrado: la carta dice que no se aceptan pedidos", "no se aceptan pedidos" in await carta.p.locator("#cerrado").inner_text())
    await carta.p.locator("#verPedido").click()
    comprobar("cerrado: «Enviar a cocina» queda desactivado", await carta.p.locator("#enviar").is_disabled())
    await carta.foto("movil-cerrado")
    await adm.p.locator("#aceptar").click()
    await adm.p.wait_for_function("document.querySelector('#aceptar').textContent.includes('abiertos')", timeout=10000)
    await ctx_c.close()

    # ===== 9. promoción redactada en el backoffice: solo llega a quien dio permiso, con baja =====
    await adm.p.locator('.tab[data-tab="pro"]').click()
    await adm.p.wait_for_selector("#proTitulo")
    await adm.p.locator("#proTitulo").fill("Martes de plato")
    await adm.p.locator("#proTexto").fill("Dos platos por el precio de uno este martes.")
    comprobar("promociones: el canal de correo está disponible (modo prueba)", await adm.p.locator("#proEmail").is_enabled())
    await adm.p.locator('[data-pro="enviar"]').click()
    mail = await esperar(lambda: next((m for m in API.json("GET", "/api/promociones/simulador")[1]["correos"] if m["para"] == correo and str(m.get("asunto", "")).startswith("Publicidad:")), None), 20)
    comprobar("promociones: el cliente con permiso recibe el correo", bool(mail))
    mail = mail or {}
    comprobar("promociones: el asunto empieza por «Publicidad:» y lleva el enlace de baja",
              str(mail.get("asunto", "")).startswith("Publicidad:") and "/baja?t=" in json.dumps(mail), json.dumps(mail)[:300])
    destinos = [m["para"] for m in API.json("GET", "/api/promociones/simulador")[1]["correos"] if str(m.get("asunto", "")).startswith("Publicidad:")]
    comprobar("promociones: solo ese correo recibió algo", destinos.count(correo) == 1 and all(d == correo for d in destinos), str(destinos))
    await adm.foto("admin-1280-promociones")
    await ctx_a.close()

    token = re.search(r"/baja\?t=([\w\-]+)", json.dumps(mail))
    ctx_b, baja = await nueva(browser, "movil", "baja-360")
    if token:
        await baja.p.goto(f"{URL}/baja?t={token.group(1)}")
        comprobar("baja 360: abrir el enlace NO da de baja (pide confirmar)", next(x for x in API.json("GET", "/api/clientes")[1]["clientes"] if x["email"] == correo)["apto_marketing"])
        await baja.sin_desborde("página de baja")
        await baja.foto("baja-360")
        await baja.p.locator("#ok").click()
        await esperar(lambda: not next(x for x in API.json("GET", "/api/clientes")[1]["clientes"] if x["email"] == correo)["apto_marketing"], 10)
        comprobar("baja 360: tras confirmar, el cliente deja de ser apto y queda la prueba", not next(x for x in API.json("GET", "/api/clientes")[1]["clientes"] if x["email"] == correo)["apto_marketing"])
    else:
        comprobar("baja: el correo trae el token", False)
    await ctx_b.close()

    # ===== 10. cierre =====
    for nom, (ctx, pg, *_r) in sesiones.items():
        await ctx.close()
    kitchen.sin_errores("cocina 1280 (sesión entera)")
    await ctx_k.close()


async def main():
    async with async_playwright() as pw:
        await principal(pw)
    print(f"\n{total - len(fallos)} de {total} comprobaciones OK")
    if fallos:
        print("FALLARON:\n  " + "\n  ".join(fallos))
        sys.exit(1)


asyncio.run(main())

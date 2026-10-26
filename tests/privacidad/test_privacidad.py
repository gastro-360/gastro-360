# SPDX-License-Identifier: EUPL-1.2
"""Privacidad: el navegador no debe hablar con nadie que no sea el propio servidor. Lo lanza tests/privacidad.sh.
Recorre la carta (360 px, hace un pedido), la cocina (1280 px) y el backoffice (1280 px, todas las pestañas), además de la tarjeta
de sellos y la baja, registrando TODAS las peticiones del navegador (también las de service workers). Falla si alguna va a otro host,
si la consola muestra errores o violaciones de la política CSP, o si una página HTML no lleva sus cabeceras de seguridad.
CARTA_URL (con http://localhost:PUERTO: contexto seguro, así también se registra el service worker), CARTA_CLAVE."""
import asyncio, os, sys, urllib.request
from urllib.parse import urlparse
from playwright.async_api import async_playwright

URL = os.environ["CARTA_URL"].rstrip("/")
CLAVE = os.environ["CARTA_CLAVE"]
PROPIO = urlparse(URL).netloc
MOVIL = dict(viewport={"width": 360, "height": 740}, device_scale_factor=2, is_mobile=True, has_touch=True, locale="es-ES")
ESCRITORIO = dict(viewport={"width": 1280, "height": 800}, locale="es-ES")
PESTANAS = (("boc", "Nuevo plato"), ("pic", "Nueva ración"), ("ing", "Nuevo ingrediente"), ("mes", "Mesas"),
            ("sel", "Tarjeta de sellos"), ("pro", "Promociones"), ("cif", "Cifras"), ("exp", "Exportar pedidos"))

hosts, problemas = {}, []


def vigilar(ctx, escenario):
    def peticion(r):
        u = urlparse(r.url)
        if u.scheme in ("data", "blob", "about"):
            return
        hosts.setdefault(u.netloc, set()).add(escenario)
        if u.netloc != PROPIO:
            problemas.append(f"[{escenario}] petición a otro host: {r.url}")
    ctx.on("request", peticion)

    def pagina(p):
        p.on("pageerror", lambda e: problemas.append(f"[{escenario}] error JS: {e}"))
        p.on("console", lambda m: m.type in ("error", "warning") and problemas.append(f"[{escenario}] consola {m.type}: {m.text}"))
        p.on("requestfailed", lambda r: "ERR_ABORTED" not in str(r.failure) and problemas.append(f"[{escenario}] red: {r.url} {r.failure}"))
    ctx.on("page", pagina)
    return pagina


async def nueva(browser, tipo, escenario):
    ctx = await browser.new_context(**(MOVIL if tipo == "movil" else ESCRITORIO))
    pagina = vigilar(ctx, escenario)
    p = await ctx.new_page()
    return ctx, p


async def esperar(p, expresion, seg=15):
    """Espera a que la expresión JS sea verdadera. Se evalúa por el protocolo del navegador: wait_for_function usaría eval(), que la CSP prohíbe."""
    for _ in range(int(seg / 0.2)):
        if await p.evaluate(expresion):
            return
        await asyncio.sleep(0.2)
    raise TimeoutError(expresion)


async def entrar(p, ruta):
    await p.goto(f"{URL}{ruta}")
    await p.locator("#clave").fill(CLAVE)
    await p.locator("#formLogin button[type=submit]").click()


async def carta(browser):
    ctx, p = await nueva(browser, "movil", "carta-360")
    await p.goto(f"{URL}/?mesa=3")
    await p.wait_for_selector("#lista [data-b]")
    await p.locator("#lista [data-b]").first.click()
    await p.locator("#add").click()
    await esperar(p, "document.querySelector('#lineas').children.length>=1")
    await p.locator("#verPedido").click()
    await p.locator("#enviar").click()
    await p.wait_for_selector("#dlgEnviar[open]")
    await p.locator("#dlgOk").click()
    await p.wait_for_selector(".env[data-pedido]", timeout=15000)
    await p.evaluate("navigator.serviceWorker && navigator.serviceWorker.ready")
    await asyncio.sleep(1)
    await ctx.close()


async def cocina(browser):
    ctx, p = await nueva(browser, "escritorio", "cocina-1280")
    await entrar(p, "/cocina")
    await p.wait_for_selector("#tablero .col")
    await p.wait_for_selector("button[data-mover]", timeout=15000)
    await asyncio.sleep(2)
    await ctx.close()


async def backoffice(browser):
    ctx, p = await nueva(browser, "escritorio", "backoffice-1280")
    await entrar(p, "/admin")
    await p.wait_for_selector("#vista .grupo, #vista .cab")
    for tab, esperado in PESTANAS:
        await p.locator(f'.tab[data-tab="{tab}"]').click()
        await esperar(p, "!document.querySelector('#vista').innerText.includes('Cargando')")
        await esperar(p, f"document.querySelector('#vista').innerText.toLowerCase().includes({esperado.lower()!r})")
    if not await p.evaluate("typeof window.qrcode === 'function'"):
        problemas.append("[backoffice-1280] la librería de QR no se ha cargado desde el propio servidor")
    await ctx.close()


async def sueltas(browser):
    ctx, p = await nueva(browser, "movil", "tarjeta-baja-360")
    await p.goto(f"{URL}/tarjeta")
    await esperar(p, "document.querySelector('#msg').innerText.length>0 && document.querySelector('#msg').innerText!=='Cargando tu tarjeta…'")
    if not await p.evaluate("typeof window.qrcode === 'function'"):
        problemas.append("[tarjeta-baja-360] la librería de QR no se ha cargado desde el propio servidor")
    await p.goto(f"{URL}/baja?t=x")
    await p.wait_for_selector("#msg")
    await ctx.close()


def cabeceras():
    print("\nCabeceras de las páginas HTML (HEAD):")
    for ruta in ("/", "/admin", "/cocina", "/tarjeta", "/baja?t=x", "/ruta-que-no-existe"):
        req = urllib.request.Request(URL + ruta, method="HEAD")
        try:
            r = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as e:
            r = e
        h = {k.lower(): v for k, v in r.headers.items()}
        csp = h.get("content-security-policy", "")
        print(f"  {ruta:22} {r.status}  CSP={'sí' if csp else 'NO'}  Referrer-Policy={h.get('referrer-policy')}  nosniff={h.get('x-content-type-options')}")
        if "text/html" in h.get("content-type", ""):
            for k, v in (("content-security-policy", None), ("referrer-policy", "no-referrer"), ("x-content-type-options", "nosniff")):
                if not h.get(k) or (v and h[k] != v):
                    problemas.append(f"{ruta}: falta o es incorrecta la cabecera {k}")
            if "unsafe-eval" in csp or "default-src 'self'" not in csp or "connect-src 'self'" not in csp or "img-src 'self' data:" not in csp:
                problemas.append(f"{ruta}: CSP no es la restrictiva esperada: {csp}")
            if "script-src" in csp and "'unsafe-inline'" in csp.split("script-src")[1].split(";")[0]:
                problemas.append(f"{ruta}: script-src admite 'unsafe-inline'")
    if r:  # la última (404) también es HTML
        pass


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for paso in (carta, cocina, backoffice, sueltas):
            print(f"== {paso.__name__}", flush=True)
            try:
                await paso(browser)
            except Exception as e:  # noqa: BLE001
                problemas.append(f"{paso.__name__}: el recorrido no se pudo completar: {type(e).__name__}: {str(e)[:300]}")
        await browser.close()
    cabeceras()
    print("\nHosts vistos por el navegador (host: escenarios):")
    for h, esc in sorted(hosts.items()):
        print(f"  {h}  <- {', '.join(sorted(esc))}" + ("" if h == PROPIO else "   <-- AJENO"))
    if problemas:
        print(f"\nFALLO: {len(problemas)} problema(s)")
        for p in problemas:
            print("  -", p)
        sys.exit(1)
    print(f"\nOK: el navegador solo habló con {PROPIO}; consola limpia; cabeceras correctas")


asyncio.run(main())

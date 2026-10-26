# SPDX-License-Identifier: EUPL-1.2
"""Prepara la carpeta web/ para subir a Netlify como app instalable (PWA).
Copia la carta, las fotos y el logo, y añade: manifiesto, iconos, service worker (funciona sin conexión)
y las etiquetas para iPhone/Android. Ejecutar cada vez que cambie la carta:  python preparar_netlify.py
"""
import html as _html, json, os, shutil
from PIL import Image, ImageDraw
import alergenos
import idiomas
import restaurante
import seguridad
import tema

BASE = os.path.dirname(os.path.abspath(__file__))
R = restaurante.DIR            # restaurante activo: variable RESTAURANTE (por defecto demo)
MARCA = restaurante.marca()
LOGO = os.path.join(restaurante.MARCA_DIR, MARCA["logo"])
DST = restaurante.WEB
VERSION = f"{restaurante.NOMBRE}-v7"   # cambiar para forzar que los móviles descarguen la versión nueva

if os.path.exists(DST):
    shutil.rmtree(DST)
os.makedirs(f"{DST}/img")
if os.path.isdir(f"{R}/fotos"):
    shutil.copytree(f"{R}/fotos", f"{DST}/fotos")
else:
    os.makedirs(f"{DST}/fotos")
shutil.copy(f"{R}/fotos.js", DST)
shutil.copy(f"{R}/datos.js", DST)   # copia fija para alojamiento estático (Netlify); el servidor la genera al vuelo
shutil.copy(LOGO, f"{DST}/img/{MARCA['logo']}")
with open(f"{DST}/alergenos.js", "w", encoding="utf-8") as f:   # los 14 alérgenos con nombre e icono, y los textos fijos
    f.write("window.ALERGENOS = " + json.dumps(alergenos.publicos(), ensure_ascii=False) + ";\n")
shutil.copy(os.path.join(BASE, "idiomas.js"), DST)   # los ocho idiomas: el script y un diccionario por idioma (i18n/<idioma>.js), todo alojado aquí
os.makedirs(f"{DST}/i18n")
for _l in idiomas.IDIOMAS:
    with open(f"{DST}/i18n/{_l}.js", "w", encoding="utf-8") as f:
        f.write(f"(window.I18N_DIC=window.I18N_DIC||{{}}).{_l}=" + json.dumps(idiomas.diccionario(_l), ensure_ascii=False) + ";\n")
shutil.copytree(os.path.join(BASE, "estatico"), f"{DST}/estatico")   # CSS, JS y fuentes compartidos (fuentes en local: el navegador no pide nada fuera)
with open(f"{DST}/tema.css", "w", encoding="utf-8") as f:   # tokens de diseño desde marca.json (el servidor la genera al vuelo)
    f.write(tema.css(MARCA))
shutil.copytree(os.path.join(BASE, "vendor"), f"{DST}/vendor")   # librerías de terceros alojadas aquí: el navegador no pide nada fuera

# Iconos: el logo sobre el color de fondo de la marca, con margen para el recorte de Android (maskable)
FONDO = tuple(int(MARCA["color_fondo"][i:i + 2], 16) for i in (1, 3, 5)) + (255,)
logo = Image.open(LOGO).convert("RGBA")
for tam, margen, nombre in [(192, .08, "icon-192.png"), (512, .08, "icon-512.png"),
                            (512, .2, "icon-maskable-512.png"), (180, .06, "apple-touch-icon.png")]:
    ic = Image.new("RGBA", (tam, tam), FONDO)
    lado = int(tam * (1 - 2 * margen))
    ic.alpha_composite(logo.resize((lado, lado), Image.LANCZOS), ((tam - lado) // 2, (tam - lado) // 2))
    ic.convert("RGB").save(f"{DST}/img/{nombre}")

# Referencia para crear fotos de ingredientes con ChatGPT (la usa la guía del backoffice)
# (un restaurante nuevo, sin fotos de capas todavía, no la tiene hasta que suba la primera)
muestras = [MARCA["foto_referencia"]] if MARCA.get("foto_referencia") else \
    sorted(f for f in os.listdir(f"{R}/fotos") if f.endswith(".lechuga.webp")) if os.path.isdir(f"{R}/fotos") else []
if muestras:
    capa = Image.open(f"{R}/fotos/{muestras[0]}").convert("RGBA")
    ref = Image.new("RGBA", (1600, 900), (255, 255, 255, 255))
    ancho = 1440
    capa = capa.resize((ancho, round(capa.height * ancho / capa.width)), Image.LANCZOS)
    ref.alpha_composite(capa, ((1600 - ancho) // 2, (900 - capa.height) // 2))
    ref.convert("RGB").save(f"{DST}/img/referencia_capa.jpg", quality=90)

json.dump({
    "name": f"{MARCA['nombre']} · Carta",
    "short_name": MARCA["nombre_corto"],
    "description": idiomas.tr(MARCA["descripcion"], "es"),
    "lang": "es",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": MARCA["color_fondo"],
    "theme_color": MARCA["color_fondo"],
    "icons": [
        {"src": "img/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "img/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "img/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}, open(f"{DST}/manifest.webmanifest", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# Service worker: guarda la carta y las fotos para que abra al instante y funcione sin conexión
archivos = ["./", "index.html", "datos.js", "fotos.js", "alergenos.js", "idiomas.js", "tema.css", "estatico/comun.js", "estatico/base.css", "estatico/carta.css", "estatico/fuentes/fuentes.css", "estatico/fuentes/inter-latin-wght-normal.woff2", "estatico/fuentes/inter-latin-ext-wght-normal.woff2"] + [f"i18n/{l}.js" for l in idiomas.IDIOMAS] + ["manifest.webmanifest", f"img/{MARCA['logo']}", "img/icon-192.png"] + \
           [f"fotos/{f}" for f in sorted(os.listdir(f"{DST}/fotos"))]
with open(f"{DST}/sw.js", "w", encoding="utf-8") as f:
    f.write(f"""const CACHE = "{VERSION}";
const ARCHIVOS = {json.dumps(archivos)};
self.addEventListener("install", e => {{ self.skipWaiting(); e.waitUntil(caches.open(CACHE).then(c => c.addAll(ARCHIVOS))); }});
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {{
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  // El backoffice, la cocina, la baja de publicidad y la API nunca pasan por la caché
  if (url.origin === self.location.origin && (url.pathname.startsWith("/admin") || url.pathname.startsWith("/cocina") || url.pathname.startsWith("/baja") || url.pathname.startsWith("/api/"))) return;
  // La carta y sus datos (precios, productos): primero la red, para ver los cambios; sin conexión, la copia guardada
  const esCarta = e.request.mode === "navigate" || url.pathname.endsWith("/datos.js") || url.pathname.endsWith("/fotos.js");
  if (esCarta) {{
    const clave = e.request.mode === "navigate" ? "index.html" : url.pathname.split("/").pop();
    e.respondWith(fetch(e.request).then(r => {{ if (r.ok) {{ const cp = r.clone(); caches.open(CACHE).then(c => c.put(clave, cp)); }} return r; }}).catch(() => caches.match(clave)));
    return;
  }}
  // Fotos y demás: la copia guardada y, si no está, la red
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request).then(res => {{
    if (res.ok && (e.request.url.startsWith(self.location.origin))) {{ const cp = res.clone(); caches.open(CACHE).then(c => c.put(e.request, cp)); }}
    return res;
  }})));
}});
""")

# index.html con las etiquetas de app
html = restaurante.plantilla(open(os.path.join(BASE, "index.html"), encoding="utf-8").read())
cabeza = f"""<meta name="theme-color" content="{MARCA['color_fondo']}">
<meta name="description" content="{_html.escape(idiomas.tr(MARCA['descripcion'], 'es'), quote=True)}">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" type="image/png" href="img/icon-192.png">
<link rel="apple-touch-icon" href="img/apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="{_html.escape(MARCA['nombre_corto'], quote=True)}">
<style>html,body{{margin:0}}:root{{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);box-sizing:border-box}}@media (display-mode:standalone){{.pantalla{{display:none!important}}}}</style>
"""
html = html.replace("<title>", cabeza + "<title>", 1)
html = "<!doctype html>\n<html lang=\"es\">\n<head>\n" + html.replace("<header class=\"top\">", "</head>\n<body>\n<header class=\"top\">", 1)
html = html.rstrip() + """
<script>if("serviceWorker" in navigator)addEventListener("load",()=>navigator.serviceWorker.register("sw.js").catch(()=>{}));</script>
</body>
</html>
"""
open(f"{DST}/index.html", "w", encoding="utf-8").write(html)

# Cabeceras de Netlify: que index.html y sw.js no se queden viejos en caché, y las mismas de seguridad que pone el servidor
seg = "  Content-Security-Policy: " + seguridad.csp(html) + "\n" + "".join(f"  {k}: {v}\n" for k, v in seguridad.CABECERAS_FIJAS)
open(f"{DST}/_headers", "w", encoding="utf-8").write("/index.html\n  Cache-Control: no-cache\n" + seg +
                                                    "/sw.js\n  Cache-Control: no-cache\n/\n  Cache-Control: no-cache\n" + seg)
total = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(DST) for f in fs)
print(f"web/ lista: {sum(len(fs) for _, _, fs in os.walk(DST))} archivos, {total / 1e6:.1f} MB")

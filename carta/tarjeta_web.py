# SPDX-License-Identifier: EUPL-1.2
"""Rutas HTTP de la tarjeta de sellos: página del cliente, descarga a Apple/Google Wallet, servicio web de PassKit,
ajustes y caja del backoffice. servidor.py las llama antes de sus rutas; cada función devuelve True si ha respondido."""
import html, json, os, re, time
from email.utils import formatdate, parsedate_to_datetime
from urllib.parse import parse_qs, urlparse

import idiomas, restaurante, sellos, wallet, wallet_apple, wallet_google

altas = {}   # ip -> [epoch de tarjetas creadas]; freno para que nadie llene la base de datos
APPLE = "/wallet/apple/v1/"
PKPASS = "application/vnd.apple.pkpass"


def base_url(h):
    """Dirección pública del local (para el QR del pase y el aviso de Apple): URL_PUBLICA, la de los QR de las mesas o la de la petición."""
    if os.environ.get("URL_PUBLICA"):
        return os.environ["URL_PUBLICA"].rstrip("/")
    try:
        with open(os.path.join(restaurante.DIR, "datos.json"), encoding="utf-8") as f:
            url = json.load(f).get("urlQR") or ""
    except (OSError, ValueError):
        url = ""
    m = re.match(r"https?://[^/]+", url)
    if m:
        return m.group(0)
    proto = h.headers.get("X-Forwarded-Proto") or "http"
    return f"{proto}://{h.headers.get('Host') or 'localhost'}"


def canales():
    return {"apple": wallet_apple.modo(), "google": wallet_google.modo()}


def publico(e):
    return {k: e[k] for k in ("id", "sellos", "sellos_meta", "premio", "premios_disponibles")}


def _idioma(h):
    return idiomas.de_peticion(h.headers)


def _t(h, clave, **p):
    """Texto de la interfaz en el idioma de la petición."""
    return idiomas.t(clave, _idioma(h), **p)


def _sesion_fuera(h):
    h.responder(401, {"error": _t(h, "tarjeta.error.sesion")})
    return True


def idioma_pagina(h, q):
    """Idioma de la página /tarjeta: ?lang= si es uno de los ocho; si no, el de la tarjeta (?t=) si existe; si no, el de la petición
    (Accept-Language: la página se abre por navegación y no lleva X-Idioma)."""
    e = sellos.estado((q.get("t") or [""])[0])
    return idiomas.valido((q.get("lang") or [""])[0]) or (e["idioma"] if e else None) or _idioma(h)


def _pagina(h, idioma):
    h.responder(200, pagina(idioma), "text/html; charset=utf-8", cabeceras=[("Cache-Control", "no-store")])


def _apple_auth(h, serie):
    m = re.fullmatch(r"ApplePass (\S+)", h.headers.get("Authorization") or "")
    return bool(m and sellos.auth_valido(serie, m.group(1)))


def _apple(h, metodo, ruta, query):
    """Servicio web de PassKit: /wallet/apple/v1/…"""
    partes = ruta[len(APPLE):].split("/")
    tipo, _ = wallet_apple.identificadores()
    if wallet_apple.modo() is None:
        h.responder(404, {"error": _t(h, "tarjeta.error.apple_no")})
        return True
    if partes == ["log"] and metodo == "POST":
        try:
            h.cuerpo_json()
        except Exception:   # noqa: BLE001
            pass
        h.responder(200, {})
        return True
    if len(partes) == 5 and partes[0] == "devices" and partes[2] == "registrations" and partes[3] == tipo:
        dispositivo, serie = partes[1], partes[4]
        if not sellos.id_valido(serie) or not _apple_auth(h, serie):
            h.responder(401, {})
            return True
        if metodo == "POST":
            try:
                token = h.cuerpo_json().get("pushToken")
            except Exception:   # noqa: BLE001
                token = None
            if not isinstance(token, str) or not 1 <= len(token) <= 200 or not re.fullmatch(r"[\w.-]{1,128}", dispositivo):
                h.responder(400, {})
                return True
            h.responder(201 if sellos.registrar_dispositivo(dispositivo, token, serie) else 200, {})
            return True
        if metodo == "DELETE":
            sellos.quitar_dispositivo(dispositivo, serie)
            h.responder(200, {})
            return True
    if len(partes) == 4 and partes[0] == "devices" and partes[2] == "registrations" and partes[3] == tipo and metodo == "GET":
        try:
            desde = float((query.get("passesUpdatedSince") or [""])[0]) if query.get("passesUpdatedSince") else None
        except ValueError:
            desde = None
        ids, marca = sellos.tarjetas_de_dispositivo(partes[1], desde)
        if not ids:
            h.responder(204, b"")
        else:
            h.responder(200, {"serialNumbers": ids, "lastUpdated": repr(marca)})
        return True
    if len(partes) == 3 and partes[0] == "passes" and partes[1] == tipo and metodo == "GET":
        serie = partes[2]
        if not sellos.id_valido(serie) or not _apple_auth(h, serie):
            h.responder(401, {})
            return True
        e = sellos.estado(serie)
        if not e:
            h.responder(404, {})
            return True
        modificado = int(e["actualizado"])
        visto = h.headers.get("If-Modified-Since")
        if visto:
            try:
                if parsedate_to_datetime(visto).timestamp() >= modificado:
                    h.responder(304, b"")
                    return True
            except (TypeError, ValueError):
                pass
        h.responder(200, wallet_apple.construir(serie, base_url(h)), PKPASS, cabeceras=[("Last-Modified", formatdate(modificado, usegmt=True))])
        return True
    h.responder(404, {})
    return True


def get(h, ruta):
    q = parse_qs(urlparse(h.path).query)
    if ruta.startswith(APPLE):
        return _apple(h, "GET", ruta, q)
    if ruta == "/api/sellos":
        c = sellos.config()
        h.responder(200, {"activo": c["activo"], "sellos_meta": c["sellos_meta"], "premio": c["premio"],
                          "premios": sellos.premios(c), "importe_minimo": c["importe_minimo"], "canales": canales()})
        return True
    if ruta in ("/tarjeta", "/tarjeta/"):
        _pagina(h, idioma_pagina(h, q))
        return True
    if ruta == "/api/tarjeta":
        e = sellos.estado((q.get("t") or [""])[0], idiomas.valido((q.get("lang") or [""])[0]) or _idioma(h))
        h.responder(*((200, publico(e)) if e else (404, {"error": _t(h, "tarjeta.error.no_encontrada")})))
        return True
    m = re.fullmatch(r"/tarjeta/([A-Za-z0-9_-]{16})(\.pkpass|/google)", ruta)
    if m:
        tid, que = m.groups()
        if que == ".pkpass":
            if wallet_apple.modo() is None:
                h.responder(404, {"error": _t(h, "tarjeta.error.apple_no")})
            else:
                datos = wallet_apple.construir(tid, base_url(h))
                h.responder(*((200, datos, PKPASS, [("Content-Disposition", 'attachment; filename="sellos.pkpass"')]) if datos else (404, {"error": _t(h, "tarjeta.error.no_encontrada")})))
        else:
            url = wallet_google.enlace_guardar(tid, base_url(h)) if wallet_google.modo() else None
            if url:
                h.responder(302, b"", "text/plain", [("Location", url)])
            else:
                h.responder(404, {"error": _t(h, "tarjeta.error.google_no")})
        return True
    if ruta == "/api/sellos/config":
        if not h.autenticado():
            return _sesion_fuera(h)
        h.responder(200, {**{k: v for k, v in sellos.config().items() if k != "wallet"}, "canales": canales(), "premios": sellos.premios(sellos.config()),
                          "identificadores": {"apple": wallet_apple.identificadores(real=True) is not None}})
        return True
    if ruta == "/api/sellos/tarjeta":
        if not h.autenticado():
            return _sesion_fuera(h)
        tid = sellos.extraer_id((q.get("t") or [""])[0])
        e = sellos.estado(tid, _idioma(h)) if tid else None
        if not e:
            h.responder(404, {"error": _t(h, "tarjeta.error.codigo")})
        else:
            h.responder(200, {**publico(e), "canjes": e["canjes"], "movimientos": sellos.movimientos(tid)[-10:]})
        return True
    if ruta == "/api/sellos/tarjetas":
        if not h.autenticado():
            return _sesion_fuera(h)
        h.responder(200, sellos.listar((q.get("q") or [""])[0]))
        return True
    if ruta == "/api/wallet/simulador":
        if not h.autenticado():
            return _sesion_fuera(h)
        if not wallet.modo_prueba():
            h.responder(404, {"error": _t(h, "tarjeta.error.solo_prueba")})
            return True
        h.responder(200, {"registro": list(wallet.REGISTRO), "apple_ca": wallet_apple.ca_publica() if wallet_apple.modo() else None,
                          "google_clave_publica": wallet_google.clave_publica() if wallet_google.modo() else None})
        return True
    return False


def post(h, ruta):
    if ruta.startswith(APPLE):
        return _apple(h, "POST", ruta, {})
    if ruta == "/api/tarjeta":
        if not sellos.config()["activo"]:
            h.responder(404, {"error": _t(h, "tarjeta.error.inactiva")})
            return True
        ip, ahora = h.ip(), time.time()
        recientes = [t for t in altas.get(ip, []) if ahora - t < 3600]
        if len(recientes) >= 30:
            h.responder(429, {"error": _t(h, "tarjeta.error.demasiadas")})
            return True
        altas[ip] = recientes + [ahora]
        t = sellos.crear_tarjeta(_idioma(h))
        h.responder(200, publico(sellos.estado(t["id"])))
        return True
    if ruta in ("/api/sellos/canjear", "/api/sellos/sellar"):
        if not h.autenticado():
            return _sesion_fuera(h)
        try:
            cuerpo = h.cuerpo_json()
            tid = sellos.extraer_id(cuerpo.get("t"))
        except Exception:   # noqa: BLE001
            tid = None
        if not tid or not sellos.estado(tid):
            h.responder(404, {"error": _t(h, "tarjeta.error.codigo")})
            return True
        if ruta.endswith("canjear"):
            ok, e = sellos.canjear(tid)
            if not ok:
                h.responder(409, {"error": _t(h, "tarjeta.error.sin_premio", sellos=e["sellos"], meta=e["sellos_meta"]), **publico(e)})
                return True
            resultado = "canjeado"
        else:
            resultado, e = sellos.sellar(tid, cuerpo.get("importe"), "caja")
            if resultado != "sellado":
                msg = _t(h, {"importe_bajo": "tarjeta.error.importe_bajo", "tope": "tarjeta.error.tope", "desactivado": "tarjeta.error.desactivado"}.get(resultado, "tarjeta.error.no_sellado"))
                h.responder(409, {"error": msg, "resultado": resultado, **publico(e)})
                return True
        wallet.notificar_en_segundo_plano(tid)
        h.responder(200, {"resultado": resultado, **publico(e)})
        return True
    return False


def put(h, ruta):
    if ruta != "/api/sellos/config":
        return False
    if not h.autenticado():
        return _sesion_fuera(h)
    try:
        nuevos = sellos.guardar_config(h.cuerpo_json())
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        h.responder(400, {"error": idiomas.mensaje(e, _idioma(h)) if str(e) else _t(h, "sellos.error.ajustes")})
        return True
    h.responder(200, nuevos)
    return True


def delete(h, ruta):
    return _apple(h, "DELETE", ruta, {}) if ruta.startswith(APPLE) else False


PAGINA = """<!doctype html><html lang="@@LANG@@"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>@@TITULO@@</title>
<link rel="stylesheet" href="/estatico/fuentes/fuentes.css"><link rel="stylesheet" href="/tema.css"><link rel="stylesheet" href="/estatico/base.css">
<style>body{padding:var(--s-5) var(--s-4);display:grid;justify-items:center}
main{width:100%;max-width:440px;display:grid;gap:var(--s-4)}p{margin:0}
.sellos{display:grid;grid-template-columns:repeat(auto-fill,minmax(52px,1fr));gap:var(--s-2)}
.sello{aspect-ratio:1;border-radius:50%;border:2px dashed var(--acento-texto);display:grid;place-items:center;font-size:22px;color:var(--sobre-acento)}
.sello.on{background:var(--acento);border-style:solid}
.qr{background:#fff;border-radius:var(--r);padding:var(--s-3);justify-self:center;line-height:0}.qr svg{width:180px;height:180px}
.botones{display:grid;gap:var(--s-2)}.botones a{display:inline-flex;align-items:center;justify-content:center;min-height:var(--objetivo);padding:0 var(--s-4);border-radius:var(--r-ctl);background:var(--primario);color:var(--sobre-primario);font-weight:600;text-decoration:none}
.aviso{background:var(--superficie-2);border:1px solid var(--linea);border-radius:var(--r-ctl);padding:var(--s-2) var(--s-3)}small{color:var(--tinta-2)}</style></head><body><main>
<h1>@@TITULO@@</h1>
<p id="msg">@@CARGANDO@@</p>
<div class="sellos" id="sellos"></div>
<div class="aviso" id="premio" hidden></div>
<div class="qr" id="qr" hidden></div>
<small id="codigo"></small>
<div class="botones" id="botones" hidden></div>
<small>@@PIE@@</small>
</main>
<script src="/vendor/qrcode-generator/qrcode.min.js"></script>
<script>
const SLUG={{js:slug}},$=id=>document.getElementById(id),T=@@T@@,f=(k,p)=>T[k].replace(/\\{(\\w+)\\}/g,(_,x)=>p[x]);
const tid=new URLSearchParams(location.search).get('t')||(()=>{try{return JSON.parse(localStorage.getItem(SLUG+'_tarjeta'))}catch(_){return null}})();
function svgQR(t){if(!window.qrcode)return'';const q=qrcode(0,'M');q.addData(t);q.make();const n=q.getModuleCount();let d='';
 for(let y=0;y<n;y++)for(let x=0;x<n;x++)if(q.isDark(y,x))d+='M'+x+' '+y+'h1v1h-1z';
 return '<svg viewBox="0 0 '+n+' '+n+'" shape-rendering="crispEdges"><path d="'+d+'"/></svg>'}
async function pinta(){
 if(!tid){$('msg').textContent=T.no_existe;return}
 const r=await fetch('/api/tarjeta?lang=@@LANG@@&t='+encodeURIComponent(tid));
 if(!r.ok){$('msg').textContent=T.no_encuentro;return}
 const e=await r.json();try{localStorage.setItem(SLUG+'_tarjeta',JSON.stringify(e.id))}catch(_){}
 $('msg').textContent=f('progreso',{sellos:e.sellos,meta:e.sellos_meta,premio:e.premio});
 $('sellos').innerHTML=Array.from({length:e.sellos_meta},(_,i)=>'<div class="sello'+(i<Math.min(e.sellos,e.sellos_meta)?' on':'')+'">'+(i<Math.min(e.sellos,e.sellos_meta)?'★':'')+'</div>').join('');
 const p=$('premio');p.hidden=!e.premios_disponibles;p.textContent=f('premio_disponible',{premio:e.premio});
 $('qr').hidden=false;$('qr').innerHTML=svgQR(e.id);$('codigo').textContent=f('codigo',{id:e.id});
 const c=(await (await fetch('/api/sellos')).json()).canales||{},b=[];
 if(c.apple)b.push('<a href="/tarjeta/'+e.id+'.pkpass">'+T.apple+'</a>');
 if(c.google)b.push('<a href="/tarjeta/'+e.id+'/google">'+T.google+'</a>');
 $('botones').hidden=!b.length;$('botones').innerHTML=b.join('')}
pinta().catch(()=>{$('msg').textContent=T.fallo});
</script></body></html>"""


CLAVES_PAGINA = ("no_existe", "no_encuentro", "progreso", "premio_disponible", "codigo", "apple", "google", "fallo")


def pagina(idioma):
    """Página de la tarjeta (bytes) en `idioma`: se rellena en servidor, no carga idiomas.js."""
    idioma = idiomas.valido(idioma) or idiomas.FUENTE
    textos = {k: idiomas.t("tarjeta.pagina." + k, idioma) for k in CLAVES_PAGINA}
    esc = lambda txt: html.escape(txt, quote=False)
    html_ = (PAGINA.replace("@@LANG@@", idioma).replace("@@TITULO@@", esc(idiomas.t("tarjeta.pagina.titulo", idioma, nombre="{{nombre}}")))
             .replace("@@CARGANDO@@", esc(idiomas.t("tarjeta.pagina.cargando", idioma))).replace("@@PIE@@", esc(idiomas.t("tarjeta.pagina.pie", idioma)))
             .replace("@@T@@", json.dumps(textos, ensure_ascii=False).replace("</", "<\\/")))
    return restaurante.plantilla(html_).encode("utf-8")

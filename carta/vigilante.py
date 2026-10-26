# SPDX-License-Identifier: EUPL-1.2
"""Vigilante: comprueba /salud cada pocos segundos y avisa por Telegram si la carta cae y cuando se recupera.
Solo biblioteca estándar. Corre como servicio aparte (`vigilante` en docker-compose.yml), así sigue vivo aunque `app` se caiga.

Variables de entorno:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   a quién avisar (secretos: solo en .env). Sin ellas solo escribe en el log.
  TELEGRAM_API_URL     por defecto https://api.telegram.org (en pruebas, un simulador)
  VIGILANTE_URL        por defecto http://app:8080/salud
  VIGILANTE_INTERVALO  segundos entre comprobaciones (30)
  VIGILANTE_FALLOS     comprobaciones seguidas fallidas antes de avisar de la caída (3)
  VIGILANTE_NOMBRE     cómo se llama en los avisos (RESTAURANTE o «carta»)
"""
import json, os, sys, time, urllib.error, urllib.request
from datetime import datetime


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} vigilante: {msg}", flush=True)


def comprobar(url, timeout=5):
    """(ok, detalle): ok solo si /salud contesta 200 con {"ok": true}."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            cuerpo = json.loads(r.read().decode("utf-8", "replace") or "{}")
            return (r.status == 200 and cuerpo.get("ok") is True), f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        try:
            problemas = json.loads(e.read().decode("utf-8", "replace")).get("problemas")
        except Exception:
            problemas = None
        return False, f"HTTP {e.code}" + (f" ({'; '.join(map(str, problemas))})" if problemas else "")
    except Exception as e:
        return False, f"sin respuesta ({type(e).__name__})"


class Telegram:
    def __init__(self, token, chat_id, api="https://api.telegram.org"):
        self.token, self.chat_id, self.api = token, chat_id, api.rstrip("/")

    @property
    def configurado(self):
        return bool(self.token and self.chat_id)

    def enviar(self, texto):
        """True si Telegram lo aceptó. Nunca escribe el token en el log."""
        if not self.configurado:
            log("Telegram sin configurar (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID): aviso solo en el log")
            return False
        req = urllib.request.Request(
            f"{self.api}/bot{self.token}/sendMessage",
            data=json.dumps({"chat_id": self.chat_id, "text": texto}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status == 200
        except Exception as e:
            log(f"no se pudo avisar por Telegram ({type(e).__name__})")
            return False


def duracion(seg):
    seg = int(seg)
    return f"{seg // 3600} h {seg % 3600 // 60} min" if seg >= 3600 else f"{seg // 60} min {seg % 60} s"


class Vigilante:
    """Máquina de estados: tras `fallos` comprobaciones malas seguidas avisa de la caída (una vez); en la primera buena
    posterior avisa de la recuperación. Si Telegram no acepta un aviso, se reintenta en la siguiente comprobación."""

    def __init__(self, url, telegram, nombre="carta", fallos=3, reloj=time.time):
        self.url, self.tg, self.nombre, self.fallos, self.reloj = url, telegram, nombre, max(1, fallos), reloj
        self.malas = 0
        self.caida_desde = None      # instante de la primera comprobación mala de la racha caída
        self.aviso_caida = False     # ya se avisó de esta caída
        self.pendiente_recuperacion = False

    def paso(self):
        ok, detalle = comprobar(self.url)
        ahora = self.reloj()
        if ok:
            if self.malas:
                log(f"recuperada tras {self.malas} fallos")
            self.malas = 0
            if self.aviso_caida:
                self.pendiente_recuperacion = True
            else:
                self.caida_desde = None
            if self.pendiente_recuperacion:
                texto = f"✅ {self.nombre}: recuperada. Estuvo caída {duracion(ahora - self.caida_desde)}."
                if self.tg.enviar(texto) or not self.tg.configurado:
                    self.aviso_caida = self.pendiente_recuperacion = False
                    self.caida_desde = None
                    log("aviso de recuperación " + ("enviado" if self.tg.configurado else "solo en el log"))
        else:
            if self.malas == 0 and self.caida_desde is None:
                self.caida_desde = ahora
            self.malas += 1
            self.pendiente_recuperacion = False
            log(f"fallo {self.malas}/{self.fallos}: {detalle}")
            if self.malas >= self.fallos and not self.aviso_caida:
                texto = f"🔴 {self.nombre}: CAÍDA. {self.url} no responde bien ({detalle})."
                if self.tg.enviar(texto) or not self.tg.configurado:
                    self.aviso_caida = True
                    log("aviso de caída " + ("enviado" if self.tg.configurado else "solo en el log"))
        return ok


def desde_entorno():
    e = os.environ.get
    tg = Telegram(e("TELEGRAM_BOT_TOKEN", ""), e("TELEGRAM_CHAT_ID", ""), e("TELEGRAM_API_URL") or "https://api.telegram.org")
    nombre = e("VIGILANTE_NOMBRE") or e("RESTAURANTE") or "carta"
    return Vigilante(e("VIGILANTE_URL") or "http://app:8080/salud", tg, nombre, int(e("VIGILANTE_FALLOS") or 3)), float(e("VIGILANTE_INTERVALO") or 30)


if __name__ == "__main__":
    v, intervalo = desde_entorno()
    log(f"vigilando {v.url} cada {intervalo:g} s (aviso tras {v.fallos} fallos); Telegram " + ("configurado" if v.tg.configurado else "SIN configurar"))
    if v.tg.configurado:
        v.tg.enviar(f"👀 {v.nombre}: vigilancia activada.")
    while True:
        v.paso()
        time.sleep(intervalo)

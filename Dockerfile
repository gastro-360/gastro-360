FROM python:3.12-slim

# Pillow, numpy y scipy: solo para subir fotos desde el backoffice y generar los iconos de la app (el servidor en sí es solo biblioteca estándar)
# curl: solo para el aviso (push) a Apple Wallet con HTTP/2 cuando haya credenciales reales (openssl ya viene en la imagen)
RUN apt-get update && apt-get install -y --no-install-recommends curl && apt-get clean \
 && pip install --no-cache-dir pillow numpy scipy \
 && useradd --uid 1000 --create-home app \
 && mkdir /datos /app && chown app:app /datos /app

WORKDIR /app
COPY --chown=app:app carta/ carta/
COPY --chown=app:app tests/ tests/
# Semilla (y lo que usan las pruebas): la carta de cada restaurante tal como está en git. Se copia al volumen /datos solo si allí aún no existe.
COPY --chown=app:app restaurantes/ /app/restaurantes/
COPY --chown=app:app docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    CARTA_RESTAURANTES=/datos/restaurantes \
    CARTA_WEB=/app/web \
    PUERTO=8080
USER app
VOLUME /datos
EXPOSE 8080
HEALTHCHECK --interval=20s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/salud', timeout=4).status == 200 else 1)"
ENTRYPOINT ["/entrypoint.sh"]

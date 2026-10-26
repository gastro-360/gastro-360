# fonts-wqy-microhei: fuente libre (Apache-2.0 o GPL-3.0) solo para que Chromium pinte los ideogramas chinos en las pruebas; no entra en la imagen de producción.
# Imagen SOLO de pruebas E2E (nunca es la de producción): Playwright + Chromium headless sobre la misma base que la app.
# Se usa en lugar de la imagen oficial mcr.microsoft.com/playwright/python (~2 GB) y de `playwright install --with-deps`
# (arrastra paquetes de fuentes) para ocupar poco disco: solo las bibliotecas que necesita el Chromium headless.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
      libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 libx11-6 libxcb1 libxext6 fonts-liberation fonts-wqy-microhei \
 && pip install --no-cache-dir playwright==1.59.0 \
 && playwright install --only-shell chromium \
 && apt-get clean && rm -rf /var/lib/apt/lists/* /root/.cache/pip
WORKDIR /e2e

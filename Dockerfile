# Imagen oficial de Playwright: ya trae Python, Chromium y todas las
# dependencias del sistema (fonts, libs gráficas, etc.) necesarias para
# correr el navegador en headless dentro de un contenedor sin pantalla.
FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

WORKDIR /app

# Instalamos dependencias de Python primero para aprovechar la cache de Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# El navegador Chromium ya viene preinstalado en la imagen base, pero por si
# la versión de requirements.txt no coincidiera exactamente, nos aseguramos:
RUN playwright install chromium

COPY . .

# Variables por defecto (se pueden sobreescribir desde las Variables del
# servicio en Railway)
ENV PLAYWRIGHT_HEADLESS=true
ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]

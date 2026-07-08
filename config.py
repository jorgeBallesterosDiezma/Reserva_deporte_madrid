import os

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
# Chat autorizado a usar el bot (el tuyo). Evita que un desconocido use tu bot
# si el token se filtra o alguien lo descubre.
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])

# --- deportesweb.madrid.es ---
DEPORTES_USUARIO = os.environ["DEPORTES_USUARIO"]
DEPORTES_CONTRASENA = os.environ["DEPORTES_CONTRASENA"]

# En Render (sin pantalla) esto DEBE ser True. Solo pon "false" si pruebas en tu
# propio ordenador y quieres ver el navegador.
PLAYWRIGHT_HEADLESS = os.environ.get("PLAYWRIGHT_HEADLESS", "true").lower() != "false"

# Ruta del fichero donde se persisten las reservas (pendientes/completadas/error).
# ⚠️ En el plan gratuito de Render el disco es efímero: si el servicio se reinicia
# o se redeploya, este fichero se pierde. Si quieres que sobreviva, añade un
# "Persistent Disk" en Render y apunta esta ruta a esa carpeta montada.
RESERVAS_JSON_PATH = os.environ.get("RESERVAS_JSON_PATH", "reservas.json")

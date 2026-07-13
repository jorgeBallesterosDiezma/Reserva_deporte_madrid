import os

try:
    from dotenv import load_dotenv
    # Busca el .env en la misma carpeta que este config.py, sin importar
    # desde qué directorio se lance el script (evita problemas si VS Code
    # lo ejecuta con un cwd distinto).
    _ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(dotenv_path=_ENV_PATH)
except ImportError:
    pass  # en Railway no hace falta: las variables ya vienen inyectadas en el entorno

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
# Chat autorizado a usar el bot (el tuyo). Evita que un desconocido use tu bot
# si el token se filtra o alguien lo descubre.
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])

# --- deportesweb.madrid.es ---
DEPORTES_USUARIO = os.environ["DEPORTES_USUARIO"]
DEPORTES_CONTRASENA = os.environ["DEPORTES_CONTRASENA"]

# En Railway (sin pantalla) esto DEBE ser True. Solo pon "false" si pruebas
# en tu propio ordenador y quieres ver el navegador.
PLAYWRIGHT_HEADLESS = os.environ.get("PLAYWRIGHT_HEADLESS", "true").lower() != "false"

# Ruta del fichero donde se persisten las reservas (pendientes/completadas/error).
# Por defecto se crea "reservas.json" en el directorio de trabajo del proceso
# (en Docker/Railway eso es /app). Si defines esta variable de entorno tú
# mismo, asegúrate de que apunta a un ARCHIVO, no a una carpeta (por ejemplo
# nunca la pongas a "/", que es un directorio y provoca IsADirectoryError).
RESERVAS_JSON_PATH = os.environ.get("RESERVAS_JSON_PATH", "reservas.json")

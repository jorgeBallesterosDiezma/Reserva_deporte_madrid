# Bot de Telegram para reservas en deportesweb.madrid.es

## Qué hace

- Hablas con el bot en Telegram (`/nueva`) y te va preguntando polideportivo,
  actividad, subtítulo, hora y fecha de la clase que quieres reservar.
- Al confirmar, guarda la reserva y programa una tarea que:
  1. Duerme hasta 2 minutos antes de la apertura (49h antes de la clase).
  2. Hace login en deportesweb.
  3. Espera al instante exacto de apertura con polling fino.
  4. Recarga, navega hasta la actividad y reserva si hay plazas.
  5. Te avisa por Telegram en cada paso importante y del resultado final.
- `/listar` muestra todas las reservas con su estado (pendiente / completada / error / cancelada).
- `/eliminar <id>` cancela una reserva pendiente.
- Si Render reinicia el proceso, al arrancar vuelve a programar automáticamente
  las reservas que seguían pendientes (lee `reservas.json`).

## 1. Crear el bot de Telegram

1. Habla con [@BotFather](https://t.me/BotFather) en Telegram, crea un bot con
   `/newbot` y guarda el **token**.
2. Averigua tu **chat_id**: escríbele algo a tu bot y visita
   `https://api.telegram.org/bot<TOKEN>/getUpdates` — ahí aparece `chat.id`.

## 2. Variables de entorno necesarias

| Variable               | Descripción                                      |
|------------------------|---------------------------------------------------|
| `TELEGRAM_BOT_TOKEN`   | Token de BotFather                                |
| `TELEGRAM_CHAT_ID`     | Tu chat_id (el bot solo responde a este chat)     |
| `DEPORTES_USUARIO`     | Usuario de deportesweb.madrid.es                  |
| `DEPORTES_CONTRASENA`  | Contraseña de deportesweb.madrid.es               |
| `PLAYWRIGHT_HEADLESS`  | `true` en Render (obligatorio, no hay pantalla)   |

Nunca subas estos valores al repositorio; en Render se configuran como
"Environment Variables" del servicio (marcadas `sync: false` en `render.yaml`
para que las escribas tú manualmente en el panel, no en el yaml).

## 3. Desplegar en Render

1. Sube esta carpeta a un repositorio de GitHub.
2. En Render: **New > Blueprint**, apunta al repo (usará `render.yaml`) — o
   crea manualmente un **Background Worker** (no "Web Service") con:
   - Build command: `pip install -r requirements.txt && playwright install --with-deps chromium`
   - Start command: `python bot.py`
3. Rellena las variables de entorno en el panel de Render.
4. Despliega. Al arrancar, el bot te mandará "🤖 Bot de reservas iniciado y listo."

## 4. Importante sobre persistencia

En el plan gratuito/starter de Render, el disco es **efímero**: si Render
reinicia el contenedor (deploy, caída, etc.), se pierde `reservas.json` y con
él el historial y las reservas que estuvieran a medio esperar.
Si quieres que sobreviva a reinicios, añade un **Persistent Disk** en Render
y define `RESERVAS_JSON_PATH` apuntando a una ruta dentro de ese disco
(p. ej. `/data/reservas.json`).

## 5. Probar en local antes de desplegar

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

export TELEGRAM_BOT_TOKEN=xxxx
export TELEGRAM_CHAT_ID=123456789
export DEPORTES_USUARIO=tu_usuario
export DEPORTES_CONTRASENA=tu_contraseña
export PLAYWRIGHT_HEADLESS=false   # para ver el navegador mientras pruebas

python bot.py
```

Nota: como pruebas de verdad requieren esperar hasta 49h antes de una clase
real, para probar el flujo de Playwright en sí (sin esperar días) puedes
llamar directamente a `reserva_madrid.ejecutar_flujo_completo` con un
`ClaseObjetivo` cuya fecha/hora hagan que la "apertura" ya haya pasado —
así el bot saltará directo a login + reserva sin esperas largas.

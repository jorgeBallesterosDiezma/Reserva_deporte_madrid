import asyncio
import datetime as dt
import logging

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
import storage
from reserva_madrid import (
    construir_objetivo,
    ejecutar_flujo_completo,
    calcular_apertura_reserva,
    ZONA_HORARIA,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

POLIDEPORTIVO, ACTIVIDAD, SUBTITULO, HORA, FECHA, CONFIRMAR = range(6)

# tareas en curso, para poder cancelarlas: {reserva_id: asyncio.Task}
TAREAS_ACTIVAS: dict[str, asyncio.Task] = {}


def _autorizado(update: Update) -> bool:
    return update.effective_chat.id == TELEGRAM_CHAT_ID


async def _no_autorizado(update: Update):
    await update.message.reply_text("No tienes permiso para usar este bot.")


# ---------------------------------------------------------------------------
# Conversación: /nueva
# ---------------------------------------------------------------------------

async def nueva_reserva_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _autorizado(update):
        await _no_autorizado(update)
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "Vamos a programar una reserva.\n¿En qué polideportivo? (ej: Moratalaz)",
        reply_markup=ReplyKeyboardRemove(),
    )
    return POLIDEPORTIVO


async def recibir_polideportivo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["polideportivo"] = update.message.text.strip()
    await update.message.reply_text("¿Nombre exacto de la actividad? (ej: Entrenamiento por intervalos)")
    return ACTIVIDAD


async def recibir_actividad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nombre_actividad"] = update.message.text.strip()
    await update.message.reply_text(
        "¿Subtítulo de la actividad para desambiguar? Envía '-' si no aplica."
    )
    return SUBTITULO


async def recibir_subtitulo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    context.user_data["subtitulo"] = None if texto == "-" else texto
    await update.message.reply_text("¿A qué hora? Formato HH:MM (ej: 11:00)")
    return HORA


async def recibir_hora(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    try:
        dt.datetime.strptime(texto, "%H:%M")
    except ValueError:
        await update.message.reply_text("Formato no válido. Usa HH:MM, por ejemplo 11:00.")
        return HORA
    context.user_data["hora_texto"] = texto
    await update.message.reply_text("¿Qué día es la clase? Formato YYYY-MM-DD (ej: 2026-07-10)")
    return FECHA


async def recibir_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    try:
        dt.datetime.strptime(texto, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text("Formato no válido. Usa YYYY-MM-DD, por ejemplo 2026-07-10.")
        return FECHA
    context.user_data["fecha_iso"] = texto

    ud = context.user_data
    objetivo = construir_objetivo(
        polideportivo=ud["polideportivo"],
        nombre_actividad=ud["nombre_actividad"],
        hora_texto=ud["hora_texto"],
        fecha_iso=ud["fecha_iso"],
        subtitulo=ud["subtitulo"],
    )
    apertura = calcular_apertura_reserva(objetivo)

    resumen = (
        "Resumen de la reserva:\n"
        f"🏟 Polideportivo: {ud['polideportivo']}\n"
        f"🏋 Actividad: {ud['nombre_actividad']}\n"
        f"🏷 Subtítulo: {ud['subtitulo'] or '(ninguno)'}\n"
        f"🕒 Hora: {ud['hora_texto']}\n"
        f"📅 Fecha: {ud['fecha_iso']}\n"
        f"🚪 Apertura de reserva: {apertura.strftime('%d/%m/%Y %H:%M:%S')}\n\n"
        "¿Confirmo y la dejo programada?"
    )
    await update.message.reply_text(
        resumen,
        reply_markup=ReplyKeyboardMarkup([["Confirmar", "Cancelar"]], one_time_keyboard=True, resize_keyboard=True),
    )
    return CONFIRMAR


async def confirmar_reserva(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip().lower()
    if texto != "confirmar":
        await update.message.reply_text("Reserva descartada.", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()
        return ConversationHandler.END

    ud = context.user_data
    datos = {
        "chat_id": update.effective_chat.id,
        "polideportivo": ud["polideportivo"],
        "nombre_actividad": ud["nombre_actividad"],
        "subtitulo": ud["subtitulo"],
        "hora_texto": ud["hora_texto"],
        "fecha_iso": ud["fecha_iso"],
    }
    reserva = await storage.crear_reserva(datos)
    await update.message.reply_text(
        f"✅ Reserva programada con id `{reserva['id']}`. Te iré avisando por aquí.\n"
        f"Usa /listar para ver el estado.",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown",
    )
    context.user_data.clear()

    _programar_tarea(context.application, reserva)
    return ConversationHandler.END


async def cancelar_conversacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Cancelado.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Comandos de consulta / gestión
# ---------------------------------------------------------------------------

FILTROS_LISTAR = {
    "todas": "Todas",
    "pendiente": "Pendientes",
    "completada": "Completadas",
    "error": "Con error",
}


def _reserva_vigente(r: dict, ahora: dt.datetime) -> bool:
    """Para las completadas, solo la mostramos si la clase todavía no ha pasado."""
    if r["status"] != "completada":
        return True
    inicio_clase = dt.datetime.strptime(
        f"{r['fecha_iso']} {r['hora_texto']}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=ZONA_HORARIA)
    return inicio_clase >= ahora


async def _texto_listado(filtro: str) -> str:
    reservas = await storage.listar_reservas()
    ahora = dt.datetime.now(ZONA_HORARIA)

    if filtro != "todas":
        reservas = [r for r in reservas if r["status"] == filtro]

    reservas = [r for r in reservas if _reserva_vigente(r, ahora)]

    if not reservas:
        return f"No hay reservas ({FILTROS_LISTAR[filtro].lower()})."

    lineas = [f"*{FILTROS_LISTAR[filtro]}:*"]
    for r in reservas:
        lineas.append(
            f"📅`{r['id']}` [{r['status']}] {r['nombre_actividad']} - {r['hora_texto']} {r['fecha_iso']}"
            + (f"\n   ⚠️ {r['detalle']}" if r.get("detalle") else "") + (f"\n ")
        )
    return "\n".join(lineas)


def _teclado_listar() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Todas", callback_data="listar:todas"),
                InlineKeyboardButton("Pendientes", callback_data="listar:pendiente"),
            ],
            [
                InlineKeyboardButton("Completadas", callback_data="listar:completada"),
                InlineKeyboardButton("Con error", callback_data="listar:error"),
            ],
        ]
    )


async def listar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _autorizado(update):
        await _no_autorizado(update)
        return

    # Permite tanto "/listar" (con botones) como "/listar pendiente" directo.
    if context.args:
        filtro = context.args[0].lower().rstrip("s")  # admite plural: "pendientes" -> "pendiente"
        if filtro not in FILTROS_LISTAR:
            await update.message.reply_text(
                "Filtro no válido. Usa: todas, pendientes, completadas o error."
            )
            return
        texto = await _texto_listado(filtro)
        await update.message.reply_text(texto, parse_mode="Markdown")
        return

    await update.message.reply_text("¿Qué quieres ver?", reply_markup=_teclado_listar())


async def listar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.message.chat.id != TELEGRAM_CHAT_ID:
        await query.answer("No tienes permiso para usar este bot.", show_alert=True)
        return

    await query.answer()
    filtro = query.data.split(":", 1)[1]
    texto = await _texto_listado(filtro)
    await query.edit_message_text(
        texto, parse_mode="Markdown", reply_markup=_teclado_listar()
    )


async def eliminar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _autorizado(update):
        await _no_autorizado(update)
        return

    if not context.args:
        await update.message.reply_text("Uso: /eliminar <id> (usa /listar para ver los ids)")
        return

    reserva_id = context.args[0]
    tarea = TAREAS_ACTIVAS.pop(reserva_id, None)
    if tarea and not tarea.done():
        tarea.cancel()

    await storage.actualizar_estado(reserva_id, "cancelada")
    await update.message.reply_text(f"Reserva {reserva_id} cancelada.")


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/nueva - programar una reserva\n"
        "/listar - ver reservas (con botones para filtrar: todas/pendientes/completadas/error)\n"
        "/listar <filtro> - directo, ej: /listar pendientes\n"
        "/eliminar <id> - cancelar una reserva pendiente\n"
        "/cancelar - cancelar la conversación en curso"
    )


# ---------------------------------------------------------------------------
# Planificación de tareas en segundo plano
# ---------------------------------------------------------------------------

def _programar_tarea(application: Application, reserva: dict):
    async def runner():
        chat_id = reserva["chat_id"]

        async def notificar(mensaje: str):
            try:
                await application.bot.send_message(chat_id=chat_id, text=mensaje, parse_mode="Markdown")
            except Exception:
                logger.exception("No se pudo enviar mensaje de notificación")

        objetivo = construir_objetivo(
            polideportivo=reserva["polideportivo"],
            nombre_actividad=reserva["nombre_actividad"],
            hora_texto=reserva["hora_texto"],
            fecha_iso=reserva["fecha_iso"],
            subtitulo=reserva["subtitulo"],
        )
        try:
            await ejecutar_flujo_completo(objetivo, notificar)
            await storage.actualizar_estado(reserva["id"], "completada")
            await notificar("🎉 ¡Reserva completada con éxito!")
        except asyncio.CancelledError:
            await storage.actualizar_estado(reserva["id"], "cancelada")
            raise
        except Exception as e:
            logger.exception("Error ejecutando la reserva %s", reserva["id"])
            await storage.actualizar_estado(reserva["id"], "error", detalle=str(e))
            await notificar(f"❌ Error al reservar: {e}")
        finally:
            TAREAS_ACTIVAS.pop(reserva["id"], None)

    tarea = application.create_task(runner())
    TAREAS_ACTIVAS[reserva["id"]] = tarea


async def _reprogramar_pendientes(application: Application):
    """Al arrancar (o reiniciar), vuelve a programar lo que seguía pendiente."""
    reservas = await storage.listar_reservas()
    ahora = dt.datetime.now(ZONA_HORARIA)
    for r in reservas:
        if r["status"] != "pendiente":
            continue
        inicio_clase = dt.datetime.strptime(
            f"{r['fecha_iso']} {r['hora_texto']}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=ZONA_HORARIA)
        if inicio_clase < ahora:
            await storage.actualizar_estado(r["id"], "caducada")
            continue
        logger.info("Reprogramando reserva pendiente %s tras reinicio", r["id"])
        _programar_tarea(application, r)


async def _post_init(application: Application):
    await _reprogramar_pendientes(application)
    await application.bot.send_message(
        chat_id=TELEGRAM_CHAT_ID, text="🤖 Bot de reservas iniciado y listo."
    )


def main():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("nueva", nueva_reserva_inicio)],
        states={
            POLIDEPORTIVO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_polideportivo)],
            ACTIVIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_actividad)],
            SUBTITULO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_subtitulo)],
            HORA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_hora)],
            FECHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_fecha)],
            CONFIRMAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirmar_reserva)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_conversacion)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("listar", listar))
    application.add_handler(CallbackQueryHandler(listar_callback, pattern=r"^listar:"))
    application.add_handler(CommandHandler("eliminar", eliminar))
    application.add_handler(CommandHandler("start", ayuda))
    application.add_handler(CommandHandler("ayuda", ayuda))

    application.run_polling()


if __name__ == "__main__":
    main()

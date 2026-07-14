from dataclasses import dataclass
import datetime as dt
from zoneinfo import ZoneInfo
from typing import Callable, Awaitable
from playwright.async_api import async_playwright, Page, expect, TimeoutError as PlaywrightTimeoutError
import asyncio

from config import DEPORTES_USUARIO, DEPORTES_CONTRASENA, PLAYWRIGHT_HEADLESS

TIMEOUT_MS_CORTO = 6000
TIMEOUT_MS_COLAPSO = 3000

HORAS_ANTELACION_RESERVA = 49
MARGEN_ANTES_LOGIN_SEGUNDOS = 2 * 60  # el login arranca 2 minutos antes de la apertura
INTERVALO_POLLING_LARGO_SEGUNDOS = 1
INTERVALO_POLLING_FINO_SEGUNDOS = 0.2
SEGUNDOS_PARA_POLLING_FINO = 5  # en los últimos 5s, polling más agresivo

# Las horas de las actividades son siempre hora de Madrid. El servidor donde
# corre el bot (Railway, Docker, etc.) normalmente lleva el reloj en UTC, así
# que fijamos la zona horaria explícitamente en vez de fiarnos del reloj del
# sistema — si no, los cálculos de "cuándo abre la reserva" se desincronizan
# 1-2 horas según la época del año (horario de verano/invierno).
ZONA_HORARIA = ZoneInfo("Europe/Madrid")

Notificador = Callable[[str], Awaitable[None]]


@dataclass
class ClaseObjetivo:
    polideportivo: str
    nombre_actividad: str
    subtitulo: str | None
    hora_texto: str
    fecha_datepicker: str  # dd/mm/yyyy
    inicio_clase: dt.datetime  # fecha+hora real de la clase (con tzinfo Europe/Madrid)


def construir_objetivo(
    polideportivo: str,
    nombre_actividad: str,
    hora_texto: str,
    fecha_iso: str,
    subtitulo: str | None = None,
) -> ClaseObjetivo:
    fecha = dt.datetime.strptime(fecha_iso, "%Y-%m-%d").date()
    hora = dt.datetime.strptime(hora_texto, "%H:%M").time()
    inicio_clase = dt.datetime.combine(fecha, hora, tzinfo=ZONA_HORARIA)
    return ClaseObjetivo(
        polideportivo=polideportivo,
        nombre_actividad=nombre_actividad,
        subtitulo=subtitulo,
        hora_texto=hora_texto,
        fecha_datepicker=fecha.strftime("%d/%m/%Y"),
        inicio_clase=inicio_clase,
    )


def calcular_apertura_reserva(objetivo: ClaseObjetivo) -> dt.datetime:
    return objetivo.inicio_clase - dt.timedelta(hours=HORAS_ANTELACION_RESERVA)


async def esperar_hasta_dos_minutos_antes(objetivo: ClaseObjetivo, notificar: Notificador):
    apertura = calcular_apertura_reserva(objetivo)
    momento_login = apertura - dt.timedelta(seconds=MARGEN_ANTES_LOGIN_SEGUNDOS)
    ahora = dt.datetime.now(ZONA_HORARIA)

    segundos_espera = (momento_login - ahora).total_seconds()

    if segundos_espera > 0:
        await notificar(
            f"😴 Esperando hasta {momento_login.strftime('%d/%m/%Y %H:%M:%S')} "
            f"(2 min antes de la apertura) para hacer login..."
        )
        await asyncio.sleep(segundos_espera)
    else:
        await notificar("⚠️ Ya estamos dentro del margen de 2 minutos. Continuando sin esperar.")


async def esperar_hasta_apertura_exacta(objetivo: ClaseObjetivo):
    apertura = calcular_apertura_reserva(objetivo)

    while True:
        ahora = dt.datetime.now(ZONA_HORARIA)
        restante = (apertura - ahora).total_seconds()

        if restante <= 0:
            break

        if restante <= SEGUNDOS_PARA_POLLING_FINO:
            await asyncio.sleep(INTERVALO_POLLING_FINO_SEGUNDOS)
        else:
            await asyncio.sleep(INTERVALO_POLLING_LARGO_SEGUNDOS)


async def login(page: Page, usuario: str, contrasena: str):
    await page.goto("https://deportesweb.madrid.es")
    await page.click("article.navigation-section-widget-collection-item")

    try:
        await page.wait_for_selector("#form1", timeout=TIMEOUT_MS_CORTO)
    except PlaywrightTimeoutError:
        raise RuntimeError("Fallo al entrar a login")

    await page.fill("#ContentFixedSection_uLogin_txtIdentificador", usuario)
    await page.fill("#ContentFixedSection_uLogin_txtContrasena", contrasena)
    await page.click("#ContentFixedSection_uLogin_btnLogin")

    try:
        await expect(page).to_have_url("https://deportesweb.madrid.es/DeportesWeb/Home")
    except PlaywrightTimeoutError:
        raise RuntimeError("Fallo al loguearse")


async def navegar_a_oferta(page: Page, objetivo: ClaseObjetivo):
    await page.get_by_text(objetivo.polideportivo, exact=False).click()
    await page.get_by_text("Oferta de actividades por día y centro").click()

    selector_dia = f'td[data-day="{objetivo.fecha_datepicker}"]'
    locator_dia = page.locator(selector_dia)

    try:
        await locator_dia.wait_for(state="visible", timeout=5000)
        await locator_dia.click()
        await page.wait_for_load_state("networkidle")
    except PlaywrightTimeoutError:
        raise RuntimeError(f"❌ No se pudo pulsar el día {objetivo.fecha_datepicker}.")


async def localizar_actividad(page: Page, actividad: str, subtitulo: str | None):
    paneles = page.locator(".panel.panel-default")
    total = await paneles.count()

    candidatos = []

    for i in range(total):
        panel = paneles.nth(i)

        h4_nombre = panel.locator(".media-body h4.media-heading").first
        nombre_actual = (await h4_nombre.text_content() or "").strip()
        if nombre_actual != actividad.strip():
            continue

        if subtitulo:
            p_subtitulo = panel.locator(".media-body p").first
            subtitulo_actual = (await p_subtitulo.text_content() or "").strip()
            if subtitulo.strip() not in subtitulo_actual:
                continue

        candidatos.append(panel)

    return candidatos


async def reservar_clase(page: Page, objetivo: ClaseObjetivo, notificar: Notificador):
    candidatos = await localizar_actividad(page, objetivo.nombre_actividad, objetivo.subtitulo)

    if len(candidatos) == 0:
        raise Exception(
            f"No se encontró la actividad '{objetivo.nombre_actividad}'"
            + (f" con subtítulo '{objetivo.subtitulo}'" if objetivo.subtitulo else "")
        )
    if len(candidatos) > 1:
        raise Exception(
            f"Se encontraron {len(candidatos)} coincidencias para '{objetivo.nombre_actividad}'"
            f" (subtítulo='{objetivo.subtitulo}'). Añade o corrige el subtítulo para desambiguar."
        )

    caja_sola = candidatos[0]

    bloque_hora = caja_sola.locator(
        "li.media", has=page.locator("h4.media-heading", has_text=objetivo.hora_texto)
    )

    if await bloque_hora.count() == 0:
        raise Exception(f"La hora {objetivo.hora_texto} no está disponible para {objetivo.nombre_actividad}.")
    if await bloque_hora.count() > 1:
        raise Exception(f"Se encontraron varios horarios que coinciden con '{objetivo.hora_texto}'.")

    span_plazas = bloque_hora.locator("span").first
    texto_plazas = await span_plazas.text_content()
    plazas_disponibles = int(texto_plazas.strip())

    await notificar(f"ℹ️ {plazas_disponibles} plazas libres detectadas.")

    if plazas_disponibles <= 0:
        raise Exception(
            f"No se puede reservar. Quedan 0 plazas libres para "
            f"{objetivo.nombre_actividad} a las {objetivo.hora_texto}."
        )

    await notificar(f"✅ ¡Hay plazas disponibles ({plazas_disponibles})! Pulsando para reservar...")
    await bloque_hora.locator("a").click()
    try:
        await expect(page).to_have_url(
            " https://deportesweb.madrid.es/DeportesWeb/Modulos/VentaServicios/CarritoConfirmar"
        )
    except PlaywrightTimeoutError:
        raise RuntimeError("Fallo al entrar a la página de confirmación de reserva")

    li_metodo = page.locator("li.list-group-item").filter(has_text="Monedero")
    radio = li_metodo.locator("input[type='radio']")
    await radio.click()
    await page.click("#ContentFixedSection_uCarritoConfirmar_btnConfirmCart")
<<<<<<< HEAD
=======
    try:
        await page.wait_for_load_state("networkidle")
    except PlaywrightTimeoutError:
        raise RuntimeError("Fallo al confirmar el pago")

    # Verificación final: solo damos la reserva por buena si aparece el
    # texto "Confirmado" (con el icono de check verde) en la página.
>>>>>>> e7179febf101d542e53c12ebf1854f10025de541
    try:
        await page.wait_for_load_state("networkidle")
    except PlaywrightTimeoutError:
        raise RuntimeError("Fallo al confirmar el pago")

    # Verificación final: solo damos la reserva por buena si aparece el
    # texto "Confirmado" (con el icono de check verde) en la página.
  #  try:
   #     await page.get_by_text("Confirmado", exact=True).wait_for(
    #        state="visible", timeout=TIMEOUT_MS_CORTO
    #    )
    #except PlaywrightTimeoutError:
    #    raise RuntimeError(
    #        "No se encontró el mensaje 'Confirmado' tras enviar el pago; "
    #        "la reserva podría no haberse completado."
     #   )


async def ejecutar_flujo_completo(objetivo: ClaseObjetivo, notificar: Notificador):
    """
    Orquesta todo el proceso: espera gruesa -> login -> espera fina ->
    reload -> navegar -> reservar. Lanza excepción si algo falla.
    """
    apertura = calcular_apertura_reserva(objetivo)
    await notificar(
        f"📅 Reserva programada para *{objetivo.nombre_actividad}* "
        f"({objetivo.hora_texto}) el {objetivo.inicio_clase.strftime('%d/%m/%Y')}.\n"
        f"🕒 Apertura de reserva: {apertura.strftime('%d/%m/%Y %H:%M:%S')}"
    )

    await esperar_hasta_dos_minutos_antes(objetivo, notificar)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
        page = await browser.new_page()

        await login(page, DEPORTES_USUARIO, DEPORTES_CONTRASENA)
        await notificar("✅ Login realizado. Esperando el instante exacto de apertura...")

        await esperar_hasta_apertura_exacta(objetivo)

        await page.reload()
        await asyncio.sleep(10)
        await navegar_a_oferta(page, objetivo)

        await reservar_clase(page, objetivo, notificar)

        await asyncio.sleep(5)
        await browser.close()

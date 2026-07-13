import json
import asyncio
import uuid
import os
from typing import Optional

from config import RESERVAS_JSON_PATH

_lock = asyncio.Lock()


def _leer_sync() -> list[dict]:
    if not os.path.exists(RESERVAS_JSON_PATH):
        return []
    with open(RESERVAS_JSON_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _escribir_sync(reservas: list[dict]):
    with open(RESERVAS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(reservas, f, ensure_ascii=False, indent=2)


async def listar_reservas() -> list[dict]:
    async with _lock:
        return _leer_sync()


async def obtener_reserva(reserva_id: str) -> Optional[dict]:
    async with _lock:
        reservas = _leer_sync()
    for r in reservas:
        if r["id"] == reserva_id:
            return r
    return None


async def crear_reserva(datos: dict) -> dict:
    async with _lock:
        reservas = _leer_sync()
        datos = dict(datos)
        datos["id"] = uuid.uuid4().hex[:8]
        datos["status"] = "pendiente"
        reservas.append(datos)
        _escribir_sync(reservas)
        return datos


async def actualizar_estado(reserva_id: str, status: str, detalle: str | None = None):
    async with _lock:
        reservas = _leer_sync()
        for r in reservas:
            if r["id"] == reserva_id:
                r["status"] = status
                if detalle is not None:
                    r["detalle"] = detalle
        _escribir_sync(reservas)

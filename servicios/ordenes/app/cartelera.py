"""Llamada al servicio de eventos (canal síncrono, REST).

Órdenes no toca las tablas de eventos. Cuando necesita saber cómo es la sala de
una función se lo pide por HTTP, directo por la red interna y sin pasar por el
gateway. Es síncrono porque sin esa respuesta no podemos seguir: la persona
está esperando el mapa de butacas en la pantalla.
"""
import os

import httpx

EVENTOS_URL = os.environ.get("EVENTOS_URL", "http://eventos:8000")


class CarteleraNoDisponible(Exception):
    """El servicio de eventos no contestó o contestó con un error."""


def pedir_funcion(cliente, funcion_id):
    """Devuelve la función con sus sectores, o None si ese cliente no tiene esa función."""
    try:
        respuesta = httpx.get(
            f"{EVENTOS_URL}/interno/funciones/{funcion_id}",
            headers={"X-Cliente": cliente},
            timeout=3,
        )
    except httpx.HTTPError as error:
        raise CarteleraNoDisponible(str(error))
    if respuesta.status_code == 404:
        return None
    if respuesta.status_code != 200:
        raise CarteleraNoDisponible(f"eventos respondió {respuesta.status_code}")
    return respuesta.json()

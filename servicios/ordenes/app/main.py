"""Servicio de órdenes de TicketStar.

Maneja la compra: las sesiones que abre el sistema del cliente en nombre de sus
usuarios, la reserva de butacas, la confirmación y nuestra página de checkout.

Habla con los otros servicios de dos formas:
- síncrona: le pide por REST a eventos cómo es la sala de una función (cartelera.py)
- asíncrona: deja en RabbitMQ el aviso de cada orden confirmada (mensajes.py)
"""
import os
import socket
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from . import mensajes, reservas
from .base import conectar, crear_tablas, esperar_base
from .cartelera import CarteleraNoDisponible
from .checkout import NOMBRES, pagina_checkout

DURACION_SESION = timedelta(minutes=15)

# Dirección pública de cada cliente. {cliente} se reemplaza por el subdominio.
URL_PUBLICA = os.environ.get("URL_PUBLICA", "http://{cliente}.ticketstar.localhost")

# Para ver qué instancia atendió cada pedido cuando hay más de una
INSTANCIA = os.environ.get("INSTANCIA") or socket.gethostname()


@asynccontextmanager
async def lifespan(app):
    esperar_base()
    crear_tablas()
    detener = mensajes.arrancar_publicador()
    if reservas.SIN_CONTROL:
        print("OJO: RESERVA_SIN_CONTROL=1, la reserva NO está protegida (solo para la demo)", flush=True)
    yield
    detener.set()


app = FastAPI(title="TicketStar - ordenes", version="0.3.0", lifespan=lifespan)


@app.middleware("http")
async def marcar_instancia(request, call_next):
    respuesta = await call_next(request)
    respuesta.headers["X-Instancia"] = INSTANCIA
    return respuesta


@app.exception_handler(psycopg.OperationalError)
async def base_caida(request, exc):
    # Si se cae Postgres, el servicio sigue vivo y avisa en vez de tirar un error 500
    return JSONResponse(status_code=503, content={"detail": "La base de datos no está disponible en este momento"})


@app.exception_handler(CarteleraNoDisponible)
async def cartelera_caida(request, exc):
    return JSONResponse(status_code=503, content={"detail": "No pudimos consultar la cartelera en este momento"})


class NuevaSesion(BaseModel):
    usuario_externo: str = Field(min_length=1, max_length=100,
                                 description="El id del usuario en el sistema del cliente")
    email: str | None = Field(default=None, max_length=200)
    evento_id: int | None = None
    url_retorno: str | None = Field(default=None, max_length=500,
                                    description="A dónde mandamos a la persona cuando termina")


class NuevaReserva(BaseModel):
    sesion_id: uuid.UUID
    funcion_id: int
    butacas: list[str] = Field(min_length=1, max_length=reservas.MAX_BUTACAS,
                               description="Los códigos de las butacas, por ejemplo Platea-C-7")


def cliente_del_pedido(x_cliente):
    if not x_cliente:
        raise HTTPException(400, "Falta el cliente: hay que entrar por el subdominio del cliente")
    return x_cliente


def buscar_sesion(sesion_id, cliente):
    with conectar() as conn:
        return conn.execute(
            "SELECT id, usuario_externo, email, evento_id, url_retorno, creada, vence "
            "FROM sesiones WHERE id = %s AND cliente = %s",
            (sesion_id, cliente),
        ).fetchone()


@app.get("/salud")
def salud():
    base = "ok"
    try:
        with conectar() as conn:
            conn.execute("SELECT 1")
    except psycopg.OperationalError:
        base = "sin conexion"
    return {"servicio": "ordenes", "estado": "ok", "base": base, "cola": mensajes.estado["cola"],
            "instancia": INSTANCIA}


# --------------------------------------------------------------------------- sesiones de compra
@app.post("/v1/sesiones", status_code=201)
def abrir_sesion(datos: NuevaSesion, x_cliente: str | None = Header(default=None)):
    cliente = cliente_del_pedido(x_cliente)
    if datos.url_retorno and not datos.url_retorno.startswith(("http://", "https://")):
        raise HTTPException(422, "url_retorno tiene que empezar con http:// o https://")

    sesion_id = uuid.uuid4()
    vence = datetime.now(timezone.utc) + DURACION_SESION
    with conectar() as conn:
        conn.execute(
            "INSERT INTO sesiones (id, cliente, usuario_externo, email, evento_id, url_retorno, vence) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (sesion_id, cliente, datos.usuario_externo, datos.email, datos.evento_id,
             datos.url_retorno, vence),
        )
    return {
        "id": sesion_id,
        "vence": vence,
        "url_checkout": URL_PUBLICA.format(cliente=cliente) + f"/checkout/{sesion_id}",
    }


@app.get("/v1/sesiones/{sesion_id}")
def ver_sesion(sesion_id: uuid.UUID, x_cliente: str | None = Header(default=None)):
    cliente = cliente_del_pedido(x_cliente)
    sesion = buscar_sesion(sesion_id, cliente)
    if sesion is None:
        raise HTTPException(404, "No existe esa sesión")
    sesion["vencida"] = sesion["vence"] < datetime.now(timezone.utc)
    return sesion


# --------------------------------------------------------------------------- butacas y reservas
@app.get("/v1/funciones/{funcion_id}/butacas")
def ver_butacas(funcion_id: int, x_cliente: str | None = Header(default=None)):
    cliente = cliente_del_pedido(x_cliente)
    funcion = reservas.buscar_funcion(cliente, funcion_id)
    del funcion["cliente"]
    return {"funcion": funcion, "butacas": reservas.mapa_de_butacas(funcion_id)}


@app.post("/v1/reservas", status_code=201)
def reservar(datos: NuevaReserva, x_cliente: str | None = Header(default=None)):
    cliente = cliente_del_pedido(x_cliente)
    sesion = buscar_sesion(datos.sesion_id, cliente)
    if sesion is None:
        raise HTTPException(404, "No existe esa sesión")
    if sesion["vence"] < datetime.now(timezone.utc):
        raise HTTPException(409, "La sesión de compra venció. Hay que empezar de nuevo desde el sitio")
    reservas.buscar_funcion(cliente, datos.funcion_id)
    return reservas.reservar(cliente, datos.sesion_id, datos.funcion_id, sorted(set(datos.butacas)))


@app.get("/v1/reservas/{reserva_id}")
def ver_reserva(reserva_id: uuid.UUID, x_cliente: str | None = Header(default=None)):
    return reservas.buscar_reserva(cliente_del_pedido(x_cliente), reserva_id)


@app.delete("/v1/reservas/{reserva_id}", status_code=204)
def cancelar_reserva(reserva_id: uuid.UUID, x_cliente: str | None = Header(default=None)):
    reservas.cancelar(cliente_del_pedido(x_cliente), reserva_id)
    return Response(status_code=204)


@app.post("/v1/reservas/{reserva_id}/confirmar")
def confirmar_reserva(reserva_id: uuid.UUID, x_cliente: str | None = Header(default=None)):
    cliente = cliente_del_pedido(x_cliente)
    return reservas.confirmar(cliente, NOMBRES.get(cliente, cliente), reserva_id)


# --------------------------------------------------------------------------- órdenes
@app.get("/v1/ordenes")
def listar_ordenes(usuario_externo: str, x_cliente: str | None = Header(default=None)):
    cliente = cliente_del_pedido(x_cliente)
    return {"cliente": cliente, "ordenes": reservas.ordenes_de_usuario(cliente, usuario_externo)}


@app.get("/v1/ordenes/{orden_id}")
def ver_orden(orden_id: uuid.UUID, x_cliente: str | None = Header(default=None)):
    return reservas.buscar_orden(cliente_del_pedido(x_cliente), orden_id)


# --------------------------------------------------------------------------- checkout (forma A)
@app.get("/checkout/{sesion_id}", response_class=HTMLResponse)
def checkout(sesion_id: uuid.UUID, x_cliente: str | None = Header(default=None)):
    cliente = cliente_del_pedido(x_cliente)
    sesion = buscar_sesion(sesion_id, cliente)
    if sesion is None:
        return HTMLResponse(pagina_checkout(cliente, None), status_code=404)
    reserva, orden = reservas.compra_de_la_sesion(sesion_id)
    return pagina_checkout(cliente, sesion, reserva, orden)

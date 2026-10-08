"""Servicio de órdenes de TicketStar.

En esta entrega maneja las sesiones de compra: el sistema del cliente abre una
sesión en nombre de uno de sus usuarios y nosotros le devolvemos la URL de
nuestro checkout. Las reservas de butacas y las órdenes llegan en la Entrega 3.
"""
import os
import socket
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .base import conectar, esperar_base
from .checkout import pagina_checkout

DURACION_SESION = timedelta(minutes=15)

# Dirección pública de cada cliente. {cliente} se reemplaza por el subdominio.
URL_PUBLICA = os.environ.get("URL_PUBLICA", "http://{cliente}.ticketstar.localhost")

TABLAS = """
CREATE SCHEMA IF NOT EXISTS ordenes;

CREATE TABLE IF NOT EXISTS ordenes.sesiones (
    id              UUID PRIMARY KEY,
    cliente         TEXT NOT NULL,
    usuario_externo TEXT NOT NULL,
    email           TEXT,
    evento_id       INT,
    url_retorno     TEXT,
    creada          TIMESTAMPTZ NOT NULL DEFAULT now(),
    vence           TIMESTAMPTZ NOT NULL
);
"""


def crear_tablas():
    with conectar() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(1002)")
        conn.execute(TABLAS)


@asynccontextmanager
async def lifespan(app):
    esperar_base()
    crear_tablas()
    yield


app = FastAPI(title="TicketStar - ordenes", version="0.2.0", lifespan=lifespan)


@app.exception_handler(psycopg.OperationalError)
async def base_caida(request, exc):
    # Si se cae Postgres, el servicio sigue vivo y avisa en vez de tirar un error 500
    return JSONResponse(status_code=503, content={"detail": "La base de datos no está disponible en este momento"})


class NuevaSesion(BaseModel):
    usuario_externo: str = Field(min_length=1, max_length=100,
                                 description="El id del usuario en el sistema del cliente")
    email: str | None = Field(default=None, max_length=200)
    evento_id: int | None = None
    url_retorno: str | None = Field(default=None, max_length=500,
                                    description="A dónde mandamos a la persona cuando termina")


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
    return {"servicio": "ordenes", "estado": "ok", "base": base, "instancia": socket.gethostname()}


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


@app.get("/checkout/{sesion_id}", response_class=HTMLResponse)
def checkout(sesion_id: uuid.UUID, x_cliente: str | None = Header(default=None)):
    cliente = cliente_del_pedido(x_cliente)
    sesion = buscar_sesion(sesion_id, cliente)
    if sesion is None:
        return HTMLResponse(pagina_checkout(cliente, None), status_code=404)
    return pagina_checkout(cliente, sesion)

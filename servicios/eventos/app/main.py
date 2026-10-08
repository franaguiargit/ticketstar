"""Servicio de eventos de TicketStar.

Maneja la cartelera de cada cliente: los eventos y sus funciones.
Todo lo que devuelve está filtrado por cliente. El cliente no lo elige quien
llama: lo saca el gateway del subdominio y nos llega en el header X-Cliente.
"""
import socket
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from .base import conectar, esperar_base
from .datos_demo import crear_tablas_y_datos


@asynccontextmanager
async def lifespan(app):
    esperar_base()
    crear_tablas_y_datos()
    yield


app = FastAPI(title="TicketStar - eventos", version="0.2.0", lifespan=lifespan)


@app.exception_handler(psycopg.OperationalError)
async def base_caida(request, exc):
    # Si se cae Postgres, el servicio sigue vivo y avisa en vez de tirar un error 500
    return JSONResponse(status_code=503, content={"detail": "La base de datos no está disponible en este momento"})


def cliente_del_pedido(x_cliente):
    if not x_cliente:
        raise HTTPException(400, "Falta el cliente: hay que entrar por el subdominio del cliente")
    return x_cliente


@app.get("/salud")
def salud():
    base = "ok"
    try:
        with conectar() as conn:
            conn.execute("SELECT 1")
    except psycopg.OperationalError:
        base = "sin conexion"
    return {"servicio": "eventos", "estado": "ok", "base": base, "instancia": socket.gethostname()}


@app.get("/v1/eventos")
def listar_eventos(x_cliente: str | None = Header(default=None)):
    cliente = cliente_del_pedido(x_cliente)
    with conectar() as conn:
        eventos = conn.execute(
            "SELECT id, nombre, descripcion, lugar FROM eventos WHERE cliente = %s ORDER BY id",
            (cliente,),
        ).fetchall()
        funciones = conn.execute(
            "SELECT f.id, f.evento_id, f.fecha, f.capacidad "
            "FROM funciones f JOIN eventos e ON e.id = f.evento_id "
            "WHERE e.cliente = %s ORDER BY f.fecha",
            (cliente,),
        ).fetchall()

    for evento in eventos:
        evento["funciones"] = [
            {"id": f["id"], "fecha": f["fecha"], "capacidad": f["capacidad"]}
            for f in funciones
            if f["evento_id"] == evento["id"]
        ]
    return {"cliente": cliente, "eventos": eventos}


@app.get("/v1/eventos/{evento_id}")
def ver_evento(evento_id: int, x_cliente: str | None = Header(default=None)):
    cliente = cliente_del_pedido(x_cliente)
    with conectar() as conn:
        evento = conn.execute(
            "SELECT id, nombre, descripcion, lugar FROM eventos WHERE id = %s AND cliente = %s",
            (evento_id, cliente),
        ).fetchone()
        if evento is None:
            # Si el evento es de otro cliente contestamos lo mismo que si no existiera
            raise HTTPException(404, "No existe ese evento")
        evento["funciones"] = conn.execute(
            "SELECT id, fecha, capacidad FROM funciones WHERE evento_id = %s ORDER BY fecha",
            (evento_id,),
        ).fetchall()
    return evento

"""Servicio de eventos de TicketStar.

Maneja la cartelera de cada cliente: los eventos y sus funciones.
Todo lo que devuelve está filtrado por cliente. El cliente no lo elige quien
llama: lo saca el gateway del subdominio y nos llega en el header X-Cliente.

Las rutas /v1 son las que publica el gateway. Las /interno son para nuestros
otros servicios, que nos llaman directo por la red interna.
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


app = FastAPI(title="TicketStar - eventos", version="0.3.0", lifespan=lifespan)


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


@app.get("/interno/funciones/{funcion_id}")
def ver_funcion(funcion_id: int, x_cliente: str | None = Header(default=None)):
    """La usa el servicio de órdenes para saber cómo es la sala de una función y armar sus butacas."""
    cliente = cliente_del_pedido(x_cliente)
    with conectar() as conn:
        funcion = conn.execute(
            "SELECT f.id, f.fecha, f.capacidad, e.id AS evento_id, e.nombre AS evento, e.lugar "
            "FROM funciones f JOIN eventos e ON e.id = f.evento_id "
            "WHERE f.id = %s AND e.cliente = %s",
            (funcion_id, cliente),
        ).fetchone()
        if funcion is None:
            raise HTTPException(404, "No existe esa función")
        funcion["sectores"] = conn.execute(
            "SELECT nombre, filas, butacas_por_fila, precio FROM sectores WHERE evento_id = %s ORDER BY id",
            (funcion["evento_id"],),
        ).fetchall()
    return funcion

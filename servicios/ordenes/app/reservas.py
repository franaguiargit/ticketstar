"""Butacas, reservas y órdenes.

Acá está el punto de concurrencia del sistema: dos personas que quieren la
misma butaca al mismo tiempo. Se resuelve en la base, en tomar_butaca().
"""
import os
import string
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import cartelera
from .base import conectar

DURACION_RESERVA = timedelta(seconds=int(os.environ.get("SEGUNDOS_RESERVA", "600")))
MAX_BUTACAS = 6

# Solo para la demo de concurrencia. Con RESERVA_SIN_CONTROL=1 se usa la versión
# ingenua de la reserva, para poder mostrar el problema. Normalmente va apagado.
SIN_CONTROL = os.environ.get("RESERVA_SIN_CONTROL", "0") == "1"

DATOS_RESERVA = (
    "SELECT r.id, r.sesion_id, r.butacas, r.total, r.estado, r.creada, r.vence, "
    "r.vence < now() AND r.estado = 'activa' AS vencida, "
    "f.id AS funcion_id, f.evento, f.lugar, f.fecha "
    "FROM reservas r JOIN funciones f ON f.id = r.funcion_id "
)
DATOS_ORDEN = (
    "SELECT o.id, upper(left(o.id::text, 8)) AS codigo, o.reserva_id, o.usuario_externo, o.email, "
    "o.butacas, o.total, o.creada, "
    "f.id AS funcion_id, f.evento, f.lugar, f.fecha "
    "FROM ordenes o JOIN funciones f ON f.id = o.funcion_id "
)


# --------------------------------------------------------------------------- funciones y butacas
def armar_butacas(funcion):
    """Con los sectores que manda eventos arma la lista de butacas: Platea-A-1, Platea-A-2..."""
    butacas = []
    for sector in funcion["sectores"]:
        for n in range(sector["filas"]):
            fila = string.ascii_uppercase[n] if sector["filas"] <= 26 else str(n + 1)
            for numero in range(1, sector["butacas_por_fila"] + 1):
                butacas.append((funcion["id"], f"{sector['nombre']}-{fila}-{numero}", len(butacas),
                                sector["nombre"], fila, numero, sector["precio"]))
    return butacas


def leer_funcion(funcion_id):
    with conectar() as conn:
        return conn.execute(
            "SELECT id, cliente, evento_id, evento, lugar, fecha FROM funciones WHERE id = %s",
            (funcion_id,),
        ).fetchone()


def buscar_funcion(cliente, funcion_id):
    """Devuelve la función. La primera vez que nos piden una le preguntamos a eventos
    cómo es la sala y guardamos sus butacas; después ya no hace falta volver a llamarlo."""
    funcion = leer_funcion(funcion_id)
    if funcion is None:
        datos = cartelera.pedir_funcion(cliente, funcion_id)
        if datos is None:
            raise HTTPException(404, "No existe esa función")
        with conectar() as conn:
            # Si dos pedidos cargan la misma función a la vez, el segundo no duplica nada
            conn.execute(
                "INSERT INTO funciones (id, cliente, evento_id, evento, lugar, fecha) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (datos["id"], cliente, datos["evento_id"], datos["evento"], datos["lugar"], datos["fecha"]),
            )
            conn.cursor().executemany(
                "INSERT INTO butacas (funcion_id, codigo, posicion, sector, fila, numero, precio) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                armar_butacas(datos),
            )
        funcion = leer_funcion(funcion_id)
    if funcion["cliente"] != cliente:
        # Si la función es de otro cliente contestamos lo mismo que si no existiera
        raise HTTPException(404, "No existe esa función")
    return funcion


def mapa_de_butacas(funcion_id):
    with conectar() as conn:
        # Una reserva vencida ya no cuenta: esa butaca se muestra libre
        return conn.execute(
            "SELECT codigo, sector, fila, numero, precio, "
            "CASE WHEN estado = 'reservada' AND vence < now() THEN 'libre' ELSE estado END AS estado "
            "FROM butacas WHERE funcion_id = %s ORDER BY posicion",
            (funcion_id,),
        ).fetchall()


# --------------------------------------------------------------------------- el punto de concurrencia
def tomar_butaca(conn, funcion_id, codigo, reserva_id, vence):
    """Marca la butaca como reservada SOLO si en ese momento está libre (o su reserva ya venció).

    Es una sola sentencia. Postgres bloquea la fila mientras la cambia, así que si
    llegan dos pedidos juntos por la misma butaca, el segundo espera a que termine
    el primero, vuelve a mirar la condición, ve que ya no está libre y no la toca.
    Devuelve el precio si la pudo tomar, o None si ya la tiene otro.
    """
    butaca = conn.execute(
        "UPDATE butacas SET estado = 'reservada', reserva_id = %s, vence = %s "
        "WHERE funcion_id = %s AND codigo = %s "
        "AND (estado = 'libre' OR (estado = 'reservada' AND vence < now())) "
        "RETURNING precio",
        (reserva_id, vence, funcion_id, codigo),
    ).fetchone()
    return butaca["precio"] if butaca else None


def tomar_butaca_sin_control(conn, funcion_id, codigo, reserva_id, vence):
    """La versión ingenua. La dejamos SOLO para mostrar el problema en la demo.

    Primero mira si la butaca está libre y después la marca. Son dos pasos, y entre
    uno y otro se puede meter otro pedido que también la vio libre: terminan los
    dos creyendo que la butaca es suya.
    """
    butaca = conn.execute(
        "SELECT precio, estado, vence FROM butacas WHERE funcion_id = %s AND codigo = %s",
        (funcion_id, codigo),
    ).fetchone()
    libre = butaca["estado"] == "libre" or (
        butaca["estado"] == "reservada" and butaca["vence"] < datetime.now(timezone.utc))
    if not libre:
        return None
    conn.execute(
        "UPDATE butacas SET estado = 'reservada', reserva_id = %s, vence = %s "
        "WHERE funcion_id = %s AND codigo = %s",
        (reserva_id, vence, funcion_id, codigo),
    )
    return butaca["precio"]


def reservar(cliente, sesion_id, funcion_id, codigos):
    """Aparta las butacas pedidas por un rato. O quedan todas reservadas o no queda ninguna."""
    tomar = tomar_butaca_sin_control if SIN_CONTROL else tomar_butaca
    reserva_id = uuid.uuid4()
    vence = datetime.now(timezone.utc) + DURACION_RESERVA
    total = 0
    with conectar() as conn:
        existen = conn.execute(
            "SELECT codigo FROM butacas WHERE funcion_id = %s AND codigo = ANY(%s)",
            (funcion_id, codigos),
        ).fetchall()
        faltan = set(codigos) - {butaca["codigo"] for butaca in existen}
        if faltan:
            raise HTTPException(422, f"No existe la butaca {sorted(faltan)[0]} en esa función")

        # Siempre en el mismo orden, así dos reservas que comparten butacas no se quedan
        # esperándose una a la otra
        for codigo in sorted(codigos):
            precio = tomar(conn, funcion_id, codigo, reserva_id, vence)
            if precio is None:
                # Al salir con un error se deshace todo lo de esta reserva
                raise HTTPException(409, f"La butaca {codigo} ya no está disponible")
            total += precio

        conn.execute(
            "INSERT INTO reservas (id, cliente, sesion_id, funcion_id, butacas, total, vence) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (reserva_id, cliente, sesion_id, funcion_id, sorted(codigos), total, vence),
        )
    return buscar_reserva(cliente, reserva_id)


# --------------------------------------------------------------------------- reservas y órdenes
def buscar_reserva(cliente, reserva_id):
    with conectar() as conn:
        reserva = conn.execute(
            DATOS_RESERVA + "WHERE r.id = %s AND r.cliente = %s", (reserva_id, cliente)
        ).fetchone()
    if reserva is None:
        raise HTTPException(404, "No existe esa reserva")
    return reserva


def cancelar(cliente, reserva_id):
    """Suelta las butacas de una reserva que todavía no se pagó."""
    with conectar() as conn:
        reserva = conn.execute(
            "SELECT funcion_id, butacas, estado FROM reservas WHERE id = %s AND cliente = %s FOR UPDATE",
            (reserva_id, cliente),
        ).fetchone()
        if reserva is None:
            raise HTTPException(404, "No existe esa reserva")
        if reserva["estado"] == "confirmada":
            raise HTTPException(409, "Esa reserva ya está confirmada")
        for codigo in reserva["butacas"]:
            # Solo si la butaca sigue siendo de esta reserva (si venció, puede tenerla otro)
            conn.execute(
                "UPDATE butacas SET estado = 'libre', reserva_id = NULL, vence = NULL "
                "WHERE funcion_id = %s AND codigo = %s AND reserva_id = %s AND estado = 'reservada'",
                (reserva["funcion_id"], codigo, reserva_id),
            )
        conn.execute("UPDATE reservas SET estado = 'cancelada' WHERE id = %s", (reserva_id,))


def confirmar(cliente, cliente_nombre, reserva_id):
    """Confirma la compra: las butacas pasan a vendidas, se crea la orden y se deja el
    aviso para los otros servicios. Todo en una transacción: queda todo hecho o nada.

    Por ahora el pago es simulado. Cuando esté el servicio de pagos, esto lo va a
    disparar el aviso de la pasarela.
    """
    with conectar() as conn:
        # FOR UPDATE: si llegan dos confirmaciones de la misma reserva (un doble clic),
        # la segunda espera a la primera y encuentra la reserva ya confirmada
        reserva = conn.execute(
            "SELECT r.sesion_id, r.funcion_id, r.butacas, r.total, r.estado, s.usuario_externo, s.email "
            "FROM reservas r JOIN sesiones s ON s.id = r.sesion_id "
            "WHERE r.id = %s AND r.cliente = %s FOR UPDATE OF r",
            (reserva_id, cliente),
        ).fetchone()
        if reserva is None:
            raise HTTPException(404, "No existe esa reserva")
        if reserva["estado"] == "cancelada":
            raise HTTPException(409, "Esa reserva fue cancelada")
        if reserva["estado"] == "confirmada":
            return conn.execute(DATOS_ORDEN + "WHERE o.reserva_id = %s", (reserva_id,)).fetchone()

        for codigo in reserva["butacas"]:
            vendida = conn.execute(
                "UPDATE butacas SET estado = 'vendida', vence = NULL "
                "WHERE funcion_id = %s AND codigo = %s AND reserva_id = %s "
                "AND estado = 'reservada' AND vence >= now()",
                (reserva["funcion_id"], codigo, reserva_id),
            ).rowcount
            if not vendida:
                raise HTTPException(409, "La reserva venció. Hay que elegir las butacas de nuevo")

        orden_id = uuid.uuid4()
        conn.execute("UPDATE reservas SET estado = 'confirmada' WHERE id = %s", (reserva_id,))
        conn.execute(
            "INSERT INTO ordenes (id, cliente, reserva_id, sesion_id, usuario_externo, email, "
            "funcion_id, butacas, total) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (orden_id, cliente, reserva_id, reserva["sesion_id"], reserva["usuario_externo"],
             reserva["email"], reserva["funcion_id"], reserva["butacas"], reserva["total"]),
        )
        orden = conn.execute(DATOS_ORDEN + "WHERE o.id = %s", (orden_id,)).fetchone()

        # El aviso se guarda en la misma transacción que la orden. Si RabbitMQ está
        # caído la compra no falla: el mensaje queda acá y sale cuando vuelve.
        conn.execute(
            "INSERT INTO mensajes (id, tipo, datos) VALUES (%s, 'orden.confirmada', %s)",
            (uuid.uuid4(), Jsonb({
                "orden_id": str(orden_id),
                "codigo": orden["codigo"],
                "cliente": cliente,
                "cliente_nombre": cliente_nombre,
                "usuario_externo": orden["usuario_externo"],
                "email": orden["email"],
                "evento": orden["evento"],
                "lugar": orden["lugar"],
                "fecha": orden["fecha"].isoformat(),
                "butacas": orden["butacas"],
                "total": orden["total"],
            })),
        )
    return orden


def buscar_orden(cliente, orden_id):
    with conectar() as conn:
        orden = conn.execute(DATOS_ORDEN + "WHERE o.id = %s AND o.cliente = %s", (orden_id, cliente)).fetchone()
    if orden is None:
        raise HTTPException(404, "No existe esa orden")
    return orden


def ordenes_de_usuario(cliente, usuario_externo):
    with conectar() as conn:
        return conn.execute(
            DATOS_ORDEN + "WHERE o.cliente = %s AND o.usuario_externo = %s ORDER BY o.creada DESC",
            (cliente, usuario_externo),
        ).fetchall()


def compra_de_la_sesion(sesion_id):
    """Para el checkout: la reserva que la sesión tiene abierta y la orden, si ya compró."""
    with conectar() as conn:
        reserva = conn.execute(
            DATOS_RESERVA + "WHERE r.sesion_id = %s AND r.estado = 'activa' AND r.vence > now() "
            "ORDER BY r.creada DESC LIMIT 1", (sesion_id,)
        ).fetchone()
        orden = conn.execute(
            DATOS_ORDEN + "WHERE o.sesion_id = %s ORDER BY o.creada DESC LIMIT 1", (sesion_id,)
        ).fetchone()
    return reserva, orden

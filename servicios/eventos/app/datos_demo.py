"""Crea las tablas del servicio y carga la cartelera y las salas de los clientes de prueba."""
from datetime import datetime, timedelta

from .base import conectar

TABLAS = """
CREATE SCHEMA IF NOT EXISTS eventos;

CREATE TABLE IF NOT EXISTS eventos.eventos (
    id          SERIAL PRIMARY KEY,
    cliente     TEXT NOT NULL,
    nombre      TEXT NOT NULL,
    descripcion TEXT,
    lugar       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eventos.funciones (
    id        SERIAL PRIMARY KEY,
    evento_id INT NOT NULL REFERENCES eventos.eventos (id),
    fecha     TIMESTAMP NOT NULL,
    capacidad INT NOT NULL CHECK (capacidad > 0)
);

-- Cómo es la sala de cada evento. Con butacas numeradas, cada sector tiene
-- tantas filas de tantas butacas. El campo general (sin numerar) todavía no está.
CREATE TABLE IF NOT EXISTS eventos.sectores (
    id               SERIAL PRIMARY KEY,
    evento_id        INT NOT NULL REFERENCES eventos.eventos (id),
    nombre           TEXT NOT NULL,
    filas            INT NOT NULL CHECK (filas > 0),
    butacas_por_fila INT NOT NULL CHECK (butacas_por_fila > 0),
    precio           INT NOT NULL CHECK (precio >= 0)
);

CREATE INDEX IF NOT EXISTS eventos_por_cliente ON eventos.eventos (cliente);
"""

# (cliente, nombre, descripción, lugar, capacidad, funciones como (días desde hoy, hora))
EVENTOS_DEMO = [
    ("teatro-avenida", "Hamlet", "La obra de Shakespeare, con la compañía estable del teatro.",
     "Sala principal", 480, [(7, 21), (8, 21), (14, 20)]),
    ("teatro-avenida", "La casa de Bernarda Alba", "El drama de García Lorca.",
     "Sala principal", 480, [(10, 20), (17, 20)]),
    ("teatro-avenida", "Noche de stand up", "Cuatro comediantes en una misma noche.",
     "Sala chica", 150, [(5, 22)]),
    ("club-atletico", "Final del torneo", "Partido final de la primera división local.",
     "Estadio del club", 8000, [(12, 17)]),
    ("club-atletico", "Recital de verano", "Bandas locales en el campo de deportes.",
     "Campo de deportes", 3000, [(30, 19)]),
]


# Sectores de cada sala: (nombre, filas, butacas por fila, precio en pesos)
SALAS_DEMO = {
    ("teatro-avenida", "Sala principal"): [("Platea", 12, 20, 18000), ("Pullman", 8, 20, 12000),
                                           ("Palcos", 4, 20, 25000)],
    ("teatro-avenida", "Sala chica"): [("Platea", 10, 15, 9000)],
}


def cargar_sectores(conn):
    """Va aparte de la cartelera porque los sectores se agregaron en la Entrega 3:
    quien ya tenía la base cargada de antes también los necesita."""
    if conn.execute("SELECT count(*) AS n FROM eventos.sectores").fetchone()["n"]:
        return
    for (cliente, lugar), sectores in SALAS_DEMO.items():
        eventos = conn.execute(
            "SELECT id FROM eventos.eventos WHERE cliente = %s AND lugar = %s", (cliente, lugar)
        ).fetchall()
        for evento in eventos:
            for nombre, filas, butacas_por_fila, precio in sectores:
                conn.execute(
                    "INSERT INTO eventos.sectores (evento_id, nombre, filas, butacas_por_fila, precio) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (evento["id"], nombre, filas, butacas_por_fila, precio),
                )
    print("Sectores de prueba cargados", flush=True)


def crear_tablas_y_datos():
    with conectar() as conn:
        # Si arrancan dos instancias a la vez, este lock hace que una sola cree las tablas
        conn.execute("SELECT pg_advisory_xact_lock(1001)")
        conn.execute(TABLAS)

        ya_cargado = conn.execute("SELECT count(*) AS n FROM eventos.eventos").fetchone()["n"]
        if not ya_cargado:
            hoy = datetime.now().replace(minute=0, second=0, microsecond=0)
            for cliente, nombre, descripcion, lugar, capacidad, funciones in EVENTOS_DEMO:
                evento_id = conn.execute(
                    "INSERT INTO eventos.eventos (cliente, nombre, descripcion, lugar) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (cliente, nombre, descripcion, lugar),
                ).fetchone()["id"]
                for dias, hora in funciones:
                    fecha = (hoy + timedelta(days=dias)).replace(hour=hora)
                    conn.execute(
                        "INSERT INTO eventos.funciones (evento_id, fecha, capacidad) VALUES (%s, %s, %s)",
                        (evento_id, fecha, capacidad),
                    )
            print("Cartelera de prueba cargada", flush=True)

        cargar_sectores(conn)

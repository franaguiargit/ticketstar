"""Crea las tablas del servicio y carga la cartelera de los dos clientes de prueba."""
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


def crear_tablas_y_datos():
    with conectar() as conn:
        # Si arrancan dos instancias a la vez, este lock hace que una sola cree las tablas
        conn.execute("SELECT pg_advisory_xact_lock(1001)")
        conn.execute(TABLAS)

        ya_cargado = conn.execute("SELECT count(*) AS n FROM eventos.eventos").fetchone()["n"]
        if ya_cargado:
            return

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

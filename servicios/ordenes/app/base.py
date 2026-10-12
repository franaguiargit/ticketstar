"""Conexión a Postgres del servicio de órdenes y sus tablas (esquema propio: ordenes)."""
import os
import time

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://ticketstar:ticketstar@localhost:5432/ticketstar"
)

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

-- Copia de los datos de cada función que nos pasó el servicio de eventos.
-- La guardamos para no tener que preguntarle de nuevo en cada pedido.
CREATE TABLE IF NOT EXISTS ordenes.funciones (
    id        INT PRIMARY KEY,
    cliente   TEXT NOT NULL,
    evento_id INT NOT NULL,
    evento    TEXT NOT NULL,
    lugar     TEXT NOT NULL,
    fecha     TIMESTAMP NOT NULL
);

-- Una fila por butaca de cada función. El estado de la butaca vive acá.
CREATE TABLE IF NOT EXISTS ordenes.butacas (
    funcion_id INT NOT NULL REFERENCES ordenes.funciones (id),
    codigo     TEXT NOT NULL,
    posicion   INT NOT NULL,
    sector     TEXT NOT NULL,
    fila       TEXT NOT NULL,
    numero     INT NOT NULL,
    precio     INT NOT NULL,
    estado     TEXT NOT NULL DEFAULT 'libre' CHECK (estado IN ('libre', 'reservada', 'vendida')),
    reserva_id UUID,
    vence      TIMESTAMPTZ,
    PRIMARY KEY (funcion_id, codigo)
);

CREATE TABLE IF NOT EXISTS ordenes.reservas (
    id         UUID PRIMARY KEY,
    cliente    TEXT NOT NULL,
    sesion_id  UUID NOT NULL REFERENCES ordenes.sesiones (id),
    funcion_id INT NOT NULL REFERENCES ordenes.funciones (id),
    butacas    TEXT[] NOT NULL,
    total      INT NOT NULL,
    estado     TEXT NOT NULL DEFAULT 'activa' CHECK (estado IN ('activa', 'confirmada', 'cancelada')),
    creada     TIMESTAMPTZ NOT NULL DEFAULT now(),
    vence      TIMESTAMPTZ NOT NULL
);

-- reserva_id es único: de una reserva sale una sola orden, pase lo que pase.
CREATE TABLE IF NOT EXISTS ordenes.ordenes (
    id              UUID PRIMARY KEY,
    cliente         TEXT NOT NULL,
    reserva_id      UUID NOT NULL UNIQUE REFERENCES ordenes.reservas (id),
    sesion_id       UUID NOT NULL REFERENCES ordenes.sesiones (id),
    usuario_externo TEXT NOT NULL,
    email           TEXT,
    funcion_id      INT NOT NULL REFERENCES ordenes.funciones (id),
    butacas         TEXT[] NOT NULL,
    total           INT NOT NULL,
    creada          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Avisos para los otros servicios. Se guardan junto con la orden y después un
-- hilo aparte los publica en RabbitMQ. "publicado" queda vacío hasta que salen.
CREATE TABLE IF NOT EXISTS ordenes.mensajes (
    id        UUID PRIMARY KEY,
    tipo      TEXT NOT NULL,
    datos     JSONB NOT NULL,
    creado    TIMESTAMPTZ NOT NULL DEFAULT now(),
    publicado TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ordenes_por_usuario ON ordenes.ordenes (cliente, usuario_externo);
"""


def conectar():
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=3,
        options="-c search_path=ordenes",
    )


def esperar_base(intentos=30):
    """Cuando se levanta todo junto, Postgres puede tardar unos segundos en aceptar conexiones."""
    for intento in range(1, intentos + 1):
        try:
            with psycopg.connect(DATABASE_URL, connect_timeout=3):
                return
        except psycopg.OperationalError:
            print(f"Esperando a la base ({intento}/{intentos})...", flush=True)
            time.sleep(1)
    raise RuntimeError("No se pudo conectar a la base de datos")


def crear_tablas():
    with conectar() as conn:
        # Si arrancan dos instancias a la vez, este lock hace que una sola cree las tablas
        conn.execute("SELECT pg_advisory_xact_lock(1002)")
        conn.execute(TABLAS)

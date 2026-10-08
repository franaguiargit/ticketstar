"""Conexión a Postgres del servicio de eventos.

Todos los servicios usan el mismo Postgres, pero cada uno tiene su propio
esquema (eventos, ordenes, ...) y no toca las tablas de los otros.
"""
import os
import time

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://ticketstar:ticketstar@localhost:5432/ticketstar"
)


def conectar():
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=3,
        options="-c search_path=eventos",
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

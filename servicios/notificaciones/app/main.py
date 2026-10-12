"""Servicio de notificaciones de TicketStar.

No tiene API: es un proceso que escucha una cola de RabbitMQ y, por cada orden
confirmada, le manda a la persona el mail con sus entradas.

Es asíncrono porque nadie está mirando la pantalla esperando el mail. Si este
servicio está apagado, los avisos se juntan en la cola y se mandan cuando vuelve.
"""
import json
import os
import smtplib
import time
from email.message import EmailMessage

import pika
import psycopg

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://ticketstar:ticketstar@localhost:5432/ticketstar"
)
RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://ticketstar:ticketstar@rabbitmq:5672/")
SMTP_HOST = os.environ.get("SMTP_HOST", "mail")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "1025"))
REMITENTE = os.environ.get("REMITENTE", "entradas@ticketstar.example")

EXCHANGE = "ticketstar"
COLA = "notificaciones"

TABLAS = """
CREATE SCHEMA IF NOT EXISTS notificaciones;

-- Los avisos que ya procesamos. RabbitMQ puede entregar el mismo aviso más de
-- una vez, y con esto no mandamos el mail repetido.
CREATE TABLE IF NOT EXISTS notificaciones.enviados (
    mensaje_id   TEXT PRIMARY KEY,
    tipo         TEXT NOT NULL,
    cliente      TEXT NOT NULL,
    destinatario TEXT,
    asunto       TEXT NOT NULL,
    enviado      TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def conectar():
    return psycopg.connect(DATABASE_URL, connect_timeout=3, options="-c search_path=notificaciones")


def esperar_base(intentos=30):
    for intento in range(1, intentos + 1):
        try:
            with conectar() as conn:
                conn.execute("SELECT pg_advisory_xact_lock(1003)")
                conn.execute(TABLAS)
                return
        except psycopg.OperationalError:
            print(f"Esperando a la base ({intento}/{intentos})...", flush=True)
            time.sleep(1)
    raise RuntimeError("No se pudo conectar a la base de datos")


# "2026-10-15T21:00:00" -> "15/10 a las 21:00"
def formatear_fecha(iso):
    fecha, hora = iso.split("T")
    _, mes, dia = fecha.split("-")
    return f"{dia}/{mes} a las {hora[:5]}"


def armar_mail(orden):
    mail = EmailMessage()
    mail["From"] = f"{orden['cliente_nombre']} <{REMITENTE}>"
    mail["To"] = orden["email"]
    mail["Subject"] = f"Tus entradas para {orden['evento']} (compra {orden['codigo']})"
    total = f"{orden['total']:,}".replace(",", ".")
    mail.set_content(
        f"¡Gracias por tu compra en {orden['cliente_nombre']}!\n\n"
        f"Evento: {orden['evento']}\n"
        f"Función: {formatear_fecha(orden['fecha'])}, {orden['lugar']}\n"
        f"Butacas: {', '.join(orden['butacas'])}\n"
        f"Total: ${total}\n"
        f"Código de compra: {orden['codigo']}\n\n"
        "Venta de entradas powered by TicketStar\n"
    )
    return mail


def procesar(mensaje_id, tipo, orden):
    """Manda el mail de una orden, salvo que ese aviso ya lo hayamos procesado antes."""
    mail = armar_mail(orden) if orden.get("email") else None
    with conectar() as conn:
        nuevo = conn.execute(
            "INSERT INTO enviados (mensaje_id, tipo, cliente, destinatario, asunto) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (mensaje_id) DO NOTHING RETURNING mensaje_id",
            (mensaje_id, tipo, orden["cliente"], orden.get("email"),
             mail["Subject"] if mail else "(sin mail)"),
        ).fetchone()
        if nuevo is None:
            print(f"El aviso {mensaje_id} ya estaba procesado, no se manda de nuevo", flush=True)
        elif mail is None:
            print(f"La orden {orden['codigo']} no tiene mail, no se manda nada", flush=True)
        else:
            # Si el mail falla, sale por error y se deshace el INSERT de arriba
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
                smtp.send_message(mail)
            print(f"Mail enviado a {orden['email']}: {mail['Subject']}", flush=True)


def al_recibir(canal, entrega, propiedades, cuerpo):
    mensaje_id = propiedades.message_id or f"sin-id-{entrega.delivery_tag}"
    try:
        orden = json.loads(cuerpo)
        procesar(mensaje_id, entrega.routing_key, orden)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        # Un aviso mal armado no se arregla reintentando: lo dejamos en el log y seguimos
        print(f"Aviso {mensaje_id} descartado, viene mal armado: {error!r}", flush=True)
    except (OSError, smtplib.SMTPException, psycopg.OperationalError) as error:
        # Falló el mail o la base: no confirmamos y el aviso vuelve a la cola
        print(f"No se pudo procesar el aviso {mensaje_id} ({error!r}), se reintenta", flush=True)
        time.sleep(5)
        canal.basic_nack(entrega.delivery_tag, requeue=True)
        return
    # Recién acá le decimos a RabbitMQ que lo saque de la cola
    canal.basic_ack(entrega.delivery_tag)


def escuchar():
    conexion = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    canal = conexion.channel()
    canal.exchange_declare(EXCHANGE, exchange_type="topic", durable=True)
    # La cola es durable: si se reinicia RabbitMQ, los avisos pendientes no se pierden
    canal.queue_declare(COLA, durable=True)
    canal.queue_bind(COLA, EXCHANGE, routing_key="orden.confirmada")
    canal.basic_qos(prefetch_count=1)  # de a uno por vez
    canal.basic_consume(COLA, al_recibir)
    print("Escuchando la cola de notificaciones", flush=True)
    canal.start_consuming()


if __name__ == "__main__":
    esperar_base()
    while True:
        try:
            escuchar()
        except (pika.exceptions.AMQPError, OSError):
            print("RabbitMQ no está disponible, reintento en 3 segundos", flush=True)
            time.sleep(3)

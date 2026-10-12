"""Publica en RabbitMQ los avisos para los otros servicios (canal asíncrono).

Los avisos se guardan primero en la tabla ordenes.mensajes, junto con la orden.
Un hilo aparte va sacando los que todavía no salieron y los publica. Así la
compra no depende de que RabbitMQ esté andando en ese momento.
"""
import json
import os
import threading

import pika
import psycopg

from .base import conectar

RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://ticketstar:ticketstar@rabbitmq:5672/")
EXCHANGE = "ticketstar"

# Para mostrar en /salud cómo está la conexión con la cola
estado = {"cola": "conectando"}


def publicar_pendientes(canal):
    with conectar() as conn:
        # SKIP LOCKED: si hay varias instancias de órdenes, no agarran el mismo mensaje
        pendientes = conn.execute(
            "SELECT id, tipo, datos FROM mensajes WHERE publicado IS NULL "
            "ORDER BY creado LIMIT 20 FOR UPDATE SKIP LOCKED"
        ).fetchall()
        for mensaje in pendientes:
            # mandatory: si todavía no hay ninguna cola escuchando ese tipo de mensaje,
            # RabbitMQ lo devuelve, esto falla y el mensaje queda pendiente
            canal.basic_publish(
                exchange=EXCHANGE,
                routing_key=mensaje["tipo"],
                body=json.dumps(mensaje["datos"]),
                properties=pika.BasicProperties(
                    message_id=str(mensaje["id"]),
                    content_type="application/json",
                    delivery_mode=2,  # que el mensaje se guarde en disco
                ),
                mandatory=True,
            )
            conn.execute("UPDATE mensajes SET publicado = now() WHERE id = %s", (mensaje["id"],))


def publicador(detener):
    """Corre en un hilo aparte mientras el servicio está vivo."""
    while not detener.is_set():
        conexion = None
        try:
            conexion = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
            canal = conexion.channel()
            canal.exchange_declare(EXCHANGE, exchange_type="topic", durable=True)
            canal.confirm_delivery()  # RabbitMQ nos confirma cada mensaje que recibe
            while not detener.is_set():
                publicar_pendientes(canal)
                estado["cola"] = "ok"
                conexion.process_data_events(time_limit=1)
        except pika.exceptions.UnroutableError:
            estado["cola"] = "sin nadie escuchando"
            print("Todavía no hay ninguna cola para los avisos, quedan pendientes", flush=True)
        except (pika.exceptions.AMQPError, OSError):
            estado["cola"] = "sin conexion"
            print("RabbitMQ no está disponible, los avisos quedan pendientes", flush=True)
        except psycopg.OperationalError:
            pass
        finally:
            if conexion is not None and conexion.is_open:
                conexion.close()
        detener.wait(3)


def arrancar_publicador():
    detener = threading.Event()
    threading.Thread(target=publicador, args=(detener,), daemon=True).start()
    return detener

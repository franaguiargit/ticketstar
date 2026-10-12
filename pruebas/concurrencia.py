"""Prueba del caso de concurrencia: muchos pedidos a la vez por la misma butaca.

    python pruebas/concurrencia.py
    python pruebas/concurrencia.py --gateway http://127.0.0.1:8080 --pedidos 50 --rondas 10

En cada ronda elige una butaca libre, abre una sesión de compra por cada pedido
y los larga todos juntos contra POST /v1/reservas. Tiene que quedarse con la
butaca uno solo (201) y el resto recibir un 409. Al final cancela las reservas
que hizo, para dejar la sala como estaba.

No usa librerías, solo lo que trae Python. Va todo por el gateway, igual que
los pedidos de un cliente.
"""
import argparse
import json
import random
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

parser = argparse.ArgumentParser(description="Prueba de concurrencia de la reserva de butacas")
parser.add_argument("--gateway", default="http://127.0.0.1", help="dónde está el gateway (por defecto http://127.0.0.1)")
parser.add_argument("--cliente", default="teatro-avenida", help="subdominio del cliente")
parser.add_argument("--pedidos", type=int, default=20, help="cuántos pedidos se largan a la vez en cada ronda")
parser.add_argument("--rondas", type=int, default=5, help="cuántas butacas distintas se prueban")
args = parser.parse_args()

# Nos conectamos a la dirección del gateway y el cliente va en el Host, que es lo
# mismo que hace el navegador cuando entra a teatro-avenida.ticketstar.localhost.
# Así no dependemos de que la máquina resuelva ese nombre fuera del navegador.
puerto = urllib.parse.urlsplit(args.gateway).port
HOST = f"{args.cliente}.ticketstar.localhost" + (f":{puerto}" if puerto else "")


def pedir(metodo, ruta, cuerpo=None):
    """Devuelve (código de estado, respuesta, instancia que atendió)."""
    pedido = urllib.request.Request(
        args.gateway + ruta,
        method=metodo,
        data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
        headers={"Host": HOST, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(pedido, timeout=30) as respuesta:
            texto = respuesta.read()
            return respuesta.status, json.loads(texto) if texto else {}, respuesta.headers.get("X-Instancia")
    except urllib.error.HTTPError as error:
        texto = error.read()
        try:
            datos = json.loads(texto)
        except ValueError:
            datos = {"detail": texto.decode(errors="replace")[:200]}
        return error.code, datos, error.headers.get("X-Instancia")
    except OSError as error:
        return 0, {"detail": str(error)}, None


def abrir_sesiones(etiqueta):
    sesiones = []
    for n in range(args.pedidos):
        estado, sesion, _ = pedir("POST", "/v1/sesiones", {"usuario_externo": f"prueba-{etiqueta}-{n}"})
        if estado != 201:
            sys.exit(f"No se pudo abrir una sesión de compra: {estado} {sesion}")
        sesiones.append(sesion["id"])
    return sesiones


def largar_juntos(funcion_id, sesiones, butacas_de):
    """Manda un pedido de reserva por sesión, todos al mismo tiempo."""
    barrera = threading.Barrier(len(sesiones))
    salidas = []

    def reservar(n):
        barrera.wait()  # todos los hilos esperan acá y salen juntos
        salidas.append(time.perf_counter())
        return pedir("POST", "/v1/reservas",
                     {"sesion_id": sesiones[n], "funcion_id": funcion_id, "butacas": butacas_de(n)})

    with ThreadPoolExecutor(len(sesiones)) as hilos:
        resultados = list(hilos.map(reservar, range(len(sesiones))))
    return resultados, (max(salidas) - min(salidas)) * 1000


def resumir(resultados):
    ganadores = [datos for estado, datos, _ in resultados if estado == 201]
    rechazos = sum(1 for estado, _, _ in resultados if estado == 409)
    otros = Counter(estado for estado, _, _ in resultados if estado not in (201, 409))
    return ganadores, rechazos, otros


def estado_de(funcion_id, codigos):
    _, mapa, _ = pedir("GET", f"/v1/funciones/{funcion_id}/butacas")
    return {butaca["codigo"]: butaca["estado"] for butaca in mapa["butacas"] if butaca["codigo"] in codigos}


# --------------------------------------------------------------------------- preparación
estado, cartelera, _ = pedir("GET", "/v1/eventos")
if estado != 200:
    sys.exit(f"No se pudo leer la cartelera en {args.gateway} ({estado} {cartelera.get('detail')}). "
             "¿Está levantado TicketStar? Si el gateway no está en el puerto 80, usar --gateway.")

funcion = libres = None
for evento in cartelera["eventos"]:
    for candidata in evento["funciones"]:
        estado, mapa, _ = pedir("GET", f"/v1/funciones/{candidata['id']}/butacas")
        if estado != 200:
            sys.exit(f"No se pudo leer el mapa de butacas: {estado} {mapa.get('detail')}")
        libres = [butaca["codigo"] for butaca in mapa["butacas"] if butaca["estado"] == "libre"]
        if len(libres) >= args.rondas + 3:
            funcion = mapa["funcion"]
            break
    if funcion:
        break
if funcion is None:
    sys.exit("No hay ninguna función con butacas libres suficientes para la prueba")

print("Prueba de concurrencia de TicketStar")
print(f"Cliente: {args.cliente} · {funcion['evento']}, función {funcion['id']} · "
      f"{args.pedidos} pedidos a la vez en cada ronda\n")

random.shuffle(libres)
problemas = 0
hechas = []           # las reservas que quedaron hechas, para cancelarlas al final
instancias = Counter()

# --------------------------------------------------------------------------- rondas de una butaca
for ronda in range(1, args.rondas + 1):
    butaca = libres.pop()
    sesiones = abrir_sesiones(ronda)
    resultados, milisegundos = largar_juntos(funcion["id"], sesiones, lambda n: [butaca])
    ganadores, rechazos, otros = resumir(resultados)
    instancias.update(instancia for _, _, instancia in resultados if instancia)
    hechas += ganadores

    bien = len(ganadores) == 1 and not otros and estado_de(funcion["id"], [butaca])[butaca] == "reservada"
    problemas += not bien
    linea = (f"Ronda {ronda}: butaca {butaca:<13} reservas hechas: {len(ganadores):<3} "
             f"rechazos (409): {rechazos:<3}")
    if otros:
        linea += f" otros: {dict(otros)} "
    print(linea + (" OK" if bien else " PROBLEMA") + f"   (salieron en {milisegundos:.0f} ms)")
    if len(ganadores) > 1:
        print(f"         -> {len(ganadores)} pedidos distintos creen que la butaca {butaca} es suya")

# --------------------------------------------------------------------------- ronda de a pares
# Tres butacas y pedidos de a dos que se pisan entre sí: (a, b), (b, c) y (c, a).
# Como cualquier par comparte una butaca con los otros, puede quedar una sola
# reserva, y la butaca que no entró en esa reserva tiene que seguir libre.
a, b, c = libres.pop(), libres.pop(), libres.pop()
pares = [[a, b], [b, c], [c, a]]
sesiones = abrir_sesiones("pares")
resultados, milisegundos = largar_juntos(funcion["id"], sesiones, lambda n: pares[n % 3])
ganadores, rechazos, otros = resumir(resultados)
instancias.update(instancia for _, _, instancia in resultados if instancia)
hechas += ganadores
estados = estado_de(funcion["id"], [a, b, c])
reservadas = sorted(codigo for codigo, estado in estados.items() if estado == "reservada")
bien = len(ganadores) == 1 and not otros and reservadas == sorted(ganadores[0]["butacas"])
problemas += not bien
print(f"\nRonda de a pares: butacas {a}, {b} y {c}, cada pedido quiere dos")
print(f"         reservas hechas: {len(ganadores)}   rechazos (409): {rechazos}"
      + (f"   otros: {dict(otros)}" if otros else "")
      + f"   quedaron reservadas: {', '.join(reservadas) or 'ninguna'}"
      + ("   OK" if bien else "   PROBLEMA"))

# --------------------------------------------------------------------------- cierre
if len(instancias) > 1:
    detalle = ", ".join(f"{nombre} ({cuantos})" for nombre, cuantos in sorted(instancias.items()))
    print(f"\nLos pedidos los atendieron {len(instancias)} instancias de órdenes: {detalle}")

for reserva in hechas:
    pedir("DELETE", f"/v1/reservas/{reserva['id']}")

print()
if problemas:
    print(f"RESULTADO: MAL. En {problemas} de {args.rondas + 1} rondas una butaca quedó para más de un pedido.")
    sys.exit(1)
print(f"RESULTADO: BIEN. En las {args.rondas + 1} rondas cada butaca quedó para un solo pedido.")

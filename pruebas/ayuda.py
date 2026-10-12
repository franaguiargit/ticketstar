"""Direcciones y funciones que comparten las pruebas."""
import os
import time

PUERTO = os.environ.get("PUERTO_GATEWAY", "80")
_sufijo = "" if PUERTO == "80" else f":{PUERTO}"

# Lo que abre el navegador
URL_TEATRO = f"http://teatro-avenida.ticketstar.localhost{_sufijo}"
SITIO_TEATRO = os.environ.get("SITIO_TEATRO", "http://localhost:3001")
CASILLA = os.environ.get("CASILLA_MAIL", "http://localhost:8025")
GATEWAY = f"http://127.0.0.1{_sufijo}"

# Si órdenes se levantó con una reserva corta (SEGUNDOS_RESERVA=3), se prueba el vencimiento
SEGUNDOS_RESERVA = int(os.environ.get("SEGUNDOS_RESERVA", "600"))


class Cliente:
    """Llama a la API de un cliente por el gateway, como lo haría su sistema.

    Los pedidos van a la dirección del gateway con el subdominio en el Host. Es lo
    mismo que entrar por <cliente>.ticketstar.localhost, pero no depende de que
    la máquina resuelva ese nombre fuera del navegador.
    """

    def __init__(self, api, nombre):
        self.api = api
        self.nombre = nombre
        self.host = f"{nombre}.ticketstar.localhost{_sufijo}"

    def pedir(self, metodo, ruta, datos=None, headers=None):
        return self.api.fetch(GATEWAY + ruta, method=metodo, data=datos,
                              headers={"Host": self.host, **(headers or {})})

    def get(self, ruta, **kw):
        return self.pedir("GET", ruta, **kw)

    def post(self, ruta, datos=None, **kw):
        return self.pedir("POST", ruta, datos, **kw)

    def delete(self, ruta):
        return self.pedir("DELETE", ruta)

    # ---- atajos para armar los casos
    def abrir_sesion(self, usuario="prueba", evento_id=None, email=None):
        respuesta = self.post("/v1/sesiones", {"usuario_externo": usuario, "evento_id": evento_id, "email": email})
        assert respuesta.status == 201, respuesta.text()
        return respuesta.json()

    def una_funcion(self):
        """La primera función del cliente que tiene butacas para vender."""
        for evento in self.get("/v1/eventos").json()["eventos"]:
            for funcion in evento["funciones"]:
                if self.butacas(funcion["id"]):
                    return funcion["id"]
        raise AssertionError(f"{self.nombre} no tiene funciones con butacas")

    def butacas(self, funcion_id):
        respuesta = self.get(f"/v1/funciones/{funcion_id}/butacas")
        assert respuesta.status == 200, respuesta.text()
        return {butaca["codigo"]: butaca["estado"] for butaca in respuesta.json()["butacas"]}

    def libres(self, funcion_id, cuantas):
        libres = [codigo for codigo, estado in self.butacas(funcion_id).items() if estado == "libre"]
        assert len(libres) >= cuantas, "No quedan butacas libres para la prueba"
        # Del final de la sala, para no chocar con las que eligen las pruebas de navegador
        return libres[-cuantas:]

    def reservar(self, sesion, funcion_id, butacas):
        return self.post("/v1/reservas", {"sesion_id": sesion["id"], "funcion_id": funcion_id, "butacas": butacas})


def esperar_mail(api, texto, segundos=15):
    """El mail sale por la cola, así que no llega al instante: lo esperamos un rato."""
    limite = time.time() + segundos
    while time.time() < limite:
        for mail in api.get(CASILLA + "/api/v1/messages").json()["messages"]:
            if texto in mail["Subject"]:
                return mail
        time.sleep(0.5)
    raise AssertionError(f"No llegó ningún mail con '{texto}' en {segundos} segundos")

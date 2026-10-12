"""Las reglas del diseño que no se tienen que romper, probadas por la API.

Que un cliente no vea nada de otro, que al sistema solo se entre por el gateway
y que una reserva quede entera o no quede.
"""
import time

import pytest

from ayuda import GATEWAY, SEGUNDOS_RESERVA


# --------------------------------------------------------------------------- cada cliente ve lo suyo
def test_cada_cliente_tiene_su_cartelera(teatro, club):
    del_teatro = {evento["id"] for evento in teatro.get("/v1/eventos").json()["eventos"]}
    del_club = {evento["id"] for evento in club.get("/v1/eventos").json()["eventos"]}
    assert del_teatro and del_club and not (del_teatro & del_club)


def test_el_cliente_sale_del_subdominio_y_no_del_header(teatro):
    # Aunque alguien mande su propio X-Cliente, el gateway lo pisa con el del subdominio
    respuesta = teatro.get("/v1/eventos", headers={"X-Cliente": "club-atletico"})
    assert respuesta.json()["cliente"] == "teatro-avenida"


def test_un_cliente_no_puede_tocar_la_compra_de_otro(teatro, club):
    funcion_id = teatro.una_funcion()
    sesion = teatro.abrir_sesion("socio-aislado")
    butaca = teatro.libres(funcion_id, 1)
    reserva = teatro.reservar(sesion, funcion_id, butaca).json()

    # Desde el subdominio del club, nada de eso existe
    assert club.get(f"/v1/funciones/{funcion_id}/butacas").status == 404
    assert club.reservar(sesion, funcion_id, butaca).status == 404
    assert club.get(f"/v1/reservas/{reserva['id']}").status == 404
    assert club.post(f"/v1/reservas/{reserva['id']}/confirmar").status == 404
    assert club.delete(f"/v1/reservas/{reserva['id']}").status == 404
    assert club.get(f"/checkout/{sesion['id']}").status == 404

    # Y para el teatro sigue todo como estaba
    assert teatro.get(f"/v1/reservas/{reserva['id']}").json()["estado"] == "activa"
    assert teatro.delete(f"/v1/reservas/{reserva['id']}").status == 204


def test_las_ordenes_de_un_cliente_no_aparecen_en_otro(teatro, club):
    funcion_id = teatro.una_funcion()
    sesion = teatro.abrir_sesion("socio-compartido")
    reserva = teatro.reservar(sesion, funcion_id, teatro.libres(funcion_id, 1)).json()
    orden = teatro.post(f"/v1/reservas/{reserva['id']}/confirmar").json()

    del_teatro = teatro.get("/v1/ordenes?usuario_externo=socio-compartido").json()["ordenes"]
    assert orden["id"] in [o["id"] for o in del_teatro]
    # El club puede tener un usuario con el mismo id, pero no ve las compras del teatro
    assert club.get("/v1/ordenes?usuario_externo=socio-compartido").json()["ordenes"] == []
    assert club.get(f"/v1/ordenes/{orden['id']}").status == 404


# --------------------------------------------------------------------------- el gateway es la única entrada
def test_las_rutas_internas_no_salen_por_el_gateway(teatro, api):
    # /interno/funciones es la ruta que usa órdenes para hablar con eventos por adentro
    assert teatro.get("/interno/funciones/1").status == 404
    assert teatro.get("/salud").status == 404
    assert api.get(GATEWAY + "/interno/funciones/1").status == 404


def test_un_subdominio_que_no_es_cliente_no_entra(api):
    respuesta = api.get(GATEWAY + "/v1/eventos", headers={"Host": "otro.ticketstar.localhost"})
    assert respuesta.status == 404


# --------------------------------------------------------------------------- la reserva
def test_la_reserva_es_todo_o_nada(teatro):
    funcion_id = teatro.una_funcion()
    ocupada, libre = teatro.libres(funcion_id, 2)
    primera = teatro.reservar(teatro.abrir_sesion("socio-a"), funcion_id, [ocupada]).json()

    # Pide una butaca libre junto con una que ya tiene otro: no se queda con ninguna
    respuesta = teatro.reservar(teatro.abrir_sesion("socio-b"), funcion_id, [libre, ocupada])
    assert respuesta.status == 409
    assert ocupada in respuesta.json()["detail"]
    assert teatro.butacas(funcion_id)[libre] == "libre"

    teatro.delete(f"/v1/reservas/{primera['id']}")


def test_confirmar_dos_veces_da_la_misma_orden(teatro):
    funcion_id = teatro.una_funcion()
    butaca = teatro.libres(funcion_id, 1)
    reserva = teatro.reservar(teatro.abrir_sesion("socio-doble-clic"), funcion_id, butaca).json()

    primera = teatro.post(f"/v1/reservas/{reserva['id']}/confirmar")
    segunda = teatro.post(f"/v1/reservas/{reserva['id']}/confirmar")
    assert primera.status == segunda.status == 200
    assert primera.json()["id"] == segunda.json()["id"]
    assert teatro.butacas(funcion_id)[butaca[0]] == "vendida"
    # Una butaca vendida ya no se puede reservar ni soltar
    assert teatro.reservar(teatro.abrir_sesion("socio-tarde"), funcion_id, butaca).status == 409
    assert teatro.delete(f"/v1/reservas/{reserva['id']}").status == 409


def test_pedidos_mal_armados(teatro):
    funcion_id = teatro.una_funcion()
    sesion = teatro.abrir_sesion("socio-raro")
    assert teatro.reservar(sesion, funcion_id, ["Platea-ZZ-999"]).status == 422    # butaca que no existe
    assert teatro.reservar(sesion, funcion_id, []).status == 422                   # sin butacas
    assert teatro.reservar(sesion, 999999, ["Platea-A-1"]).status == 404           # función que no existe
    muchas = teatro.libres(funcion_id, 7)
    assert teatro.reservar(sesion, funcion_id, muchas).status == 422               # más de 6 por compra
    assert teatro.butacas(funcion_id)[muchas[0]] == "libre"


@pytest.mark.skipif(SEGUNDOS_RESERVA > 10, reason="para probarlo hay que levantar órdenes con SEGUNDOS_RESERVA=3")
def test_una_reserva_que_no_se_paga_se_vence(teatro):
    funcion_id = teatro.una_funcion()
    butaca = teatro.libres(funcion_id, 1)
    vieja = teatro.reservar(teatro.abrir_sesion("socio-lento"), funcion_id, butaca).json()
    assert teatro.butacas(funcion_id)[butaca[0]] == "reservada"

    time.sleep(SEGUNDOS_RESERVA + 1)

    # Pasado el tiempo la butaca vuelve a estar libre y se la puede llevar otra persona
    assert teatro.butacas(funcion_id)[butaca[0]] == "libre"
    assert teatro.get(f"/v1/reservas/{vieja['id']}").json()["vencida"] is True
    nueva = teatro.reservar(teatro.abrir_sesion("socio-rapido"), funcion_id, butaca)
    assert nueva.status == 201

    # El primero llega tarde a pagar: su reserva ya no vale y la butaca sigue siendo del segundo
    assert teatro.post(f"/v1/reservas/{vieja['id']}/confirmar").status == 409
    assert teatro.post(f"/v1/reservas/{nueva.json()['id']}/confirmar").status == 200
    assert teatro.butacas(funcion_id)[butaca[0]] == "vendida"

"""La compra completa por la forma A, en un navegador de verdad.

Sitio del teatro -> nuestro checkout -> elegir butacas -> reservar -> pagar ->
llega el mail -> vuelta al sitio del teatro, que muestra la compra.
"""
import re

from playwright.sync_api import expect

from ayuda import SITIO_TEATRO, esperar_mail


def test_compra_completa(page, api, teatro):
    # La cartelera la muestra el sitio del teatro, pero los datos vienen de TicketStar
    page.goto(SITIO_TEATRO)
    expect(page.get_by_role("heading", name="Hamlet")).to_be_visible()
    expect(page.get_by_text("Final del torneo")).to_have_count(0)  # eso es del club, acá no aparece

    # Al comprar, el teatro abre la sesión y nos manda al checkout, en su subdominio
    page.locator(".evento", has_text="Noche de stand up").get_by_role("button", name="Comprar entradas").click()
    expect(page).to_have_url(re.compile(r"^http://teatro-avenida\.ticketstar\.localhost(:\d+)?/checkout/"))
    expect(page.get_by_role("heading", name="Noche de stand up")).to_be_visible()
    funcion_id = int(page.locator("#funcion").input_value())

    # Elegimos las dos primeras butacas libres del mapa
    libres = page.locator("button.butaca.libre")
    butacas = [libres.nth(0).get_attribute("data-codigo"), libres.nth(1).get_attribute("data-codigo")]
    for codigo in butacas:
        page.locator(f'button[data-codigo="{codigo}"]').click()
    expect(page.locator("#resumen")).to_contain_text("Total: $18.000")

    page.get_by_role("button", name="Reservar").click()
    expect(page.get_by_role("heading", name="Tus butacas están reservadas")).to_be_visible()
    expect(page.locator("#pago-butacas")).to_have_text(", ".join(sorted(butacas)))
    estados = teatro.butacas(funcion_id)
    assert [estados[codigo] for codigo in butacas] == ["reservada", "reservada"]

    # Si se recarga la página la reserva sigue ahí, porque el estado está en el servidor
    page.reload()
    expect(page.get_by_role("heading", name="Tus butacas están reservadas")).to_be_visible()

    page.get_by_role("button", name="Pagar").click()
    expect(page.get_by_role("heading", name="¡Listo! La compra está confirmada")).to_be_visible()
    codigo_compra = page.locator("#listo-codigo").inner_text()
    estados = teatro.butacas(funcion_id)
    assert [estados[codigo] for codigo in butacas] == ["vendida", "vendida"]

    # El mail no lo manda órdenes: sale por RabbitMQ y lo manda notificaciones
    mail = esperar_mail(api, codigo_compra)
    assert mail["To"][0]["Address"] == "ana@example.com"
    assert "Noche de stand up" in mail["Subject"]

    # De vuelta en el sitio del teatro, que le pide la compra a TicketStar y la muestra
    page.get_by_role("link", name="Volver a Teatro Avenida").click()
    expect(page).to_have_url(SITIO_TEATRO + "/mis-entradas")
    compra = page.locator(".evento", has_text=codigo_compra)
    expect(compra).to_contain_text("Noche de stand up")
    expect(compra).to_contain_text(butacas[0])


def test_cancelar_y_elegir_de_nuevo(page, teatro):
    page.goto(SITIO_TEATRO)
    page.locator(".evento", has_text="Noche de stand up").get_by_role("button", name="Comprar entradas").click()
    libre = page.locator("button.butaca.libre").first
    codigo = libre.get_attribute("data-codigo")
    funcion_id = int(page.locator("#funcion").input_value())
    libre.click()
    page.get_by_role("button", name="Reservar").click()
    expect(page.get_by_role("heading", name="Tus butacas están reservadas")).to_be_visible()

    page.get_by_role("button", name="Elegir otras butacas").click()
    expect(page.locator(f'button[data-codigo="{codigo}"]')).to_be_enabled()
    assert teatro.butacas(funcion_id)[codigo] == "libre"

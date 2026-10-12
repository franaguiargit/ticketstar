"""El caso de concurrencia visto desde dos navegadores.

Dos personas entran al checkout, eligen la misma butaca y tocan "Reservar" en
el mismo momento. Una se la queda y la otra recibe el aviso.
"""
import time

from playwright.sync_api import expect

from ayuda import SITIO_TEATRO


def entrar_al_checkout(browser):
    pagina = browser.new_context().new_page()
    pagina.goto(SITIO_TEATRO)
    pagina.locator(".evento", has_text="Hamlet").get_by_role("button", name="Comprar entradas").click()
    expect(pagina.locator("button.butaca").first).to_be_visible()
    return pagina


def test_dos_personas_eligen_la_misma_butaca(browser, teatro):
    ana = entrar_al_checkout(browser)
    beto = entrar_al_checkout(browser)
    funcion_id = int(ana.locator("#funcion").input_value())

    codigo = ana.locator("button.butaca.libre").first.get_attribute("data-codigo")
    ana.locator(f'button[data-codigo="{codigo}"]').click()
    beto.locator(f'button[data-codigo="{codigo}"]').click()

    # Los dos navegadores quedan programados para apretar "Reservar" a la misma hora
    hora = int(time.time() * 1000) + 1500
    for pagina in (ana, beto):
        pagina.evaluate(
            "hora => setTimeout(() => document.getElementById('reservar').click(), hora - Date.now())", hora)

    reservo = "Tus butacas están reservadas"
    expect(ana.get_by_role("heading", name=reservo).or_(ana.locator("#aviso:visible"))).to_be_visible()
    expect(beto.get_by_role("heading", name=reservo).or_(beto.locator("#aviso:visible"))).to_be_visible()

    # Una sola de las dos personas llegó a la pantalla de pago
    ganadores = [p for p in (ana, beto) if p.get_by_role("heading", name=reservo).is_visible()]
    assert len(ganadores) == 1
    perdedor = beto if ganadores[0] is ana else ana

    # La otra ve el aviso y la butaca le queda como ocupada en el mapa
    expect(perdedor.locator("#aviso")).to_contain_text(codigo)
    expect(perdedor.locator(f'button[data-codigo="{codigo}"]')).to_be_disabled()
    assert teatro.butacas(funcion_id)[codigo] == "reservada"

    # Y puede seguir comprando: elige otra butaca y la reserva sin problema
    perdedor.locator("button.butaca.libre").first.click()
    perdedor.get_by_role("button", name="Reservar").click()
    expect(perdedor.get_by_role("heading", name=reservo)).to_be_visible()

    # Dejamos la sala como estaba
    for pagina in (ana, beto):
        pagina.get_by_role("button", name="Elegir otras butacas").click()
        expect(pagina.locator("#paso-elegir")).to_be_visible()
    assert teatro.butacas(funcion_id)[codigo] == "libre"

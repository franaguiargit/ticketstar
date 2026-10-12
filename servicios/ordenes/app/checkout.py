"""Página de checkout que alojamos nosotros (forma A de integración).

El sitio del cliente manda a la persona acá con el id de la sesión de compra.
Acá elige la función y las butacas, las reserva y paga. La parte que corre en
el navegador está en checkout.js.
"""
import json
import pathlib
from datetime import datetime, timezone
from html import escape

from fastapi.encoders import jsonable_encoder

from .reservas import MAX_BUTACAS

NOMBRES = {"teatro-avenida": "Teatro Avenida", "club-atletico": "Club Atlético"}

SCRIPT = (pathlib.Path(__file__).parent / "checkout.js").read_text(encoding="utf-8")

ESTILO = """
body { font-family: Arial, sans-serif; background: #f3f4f6; margin: 0; color: #222; }
main { max-width: 660px; margin: 40px auto; background: #fff; padding: 28px 32px;
       border: 1px solid #ddd; border-radius: 8px; }
h1 { font-size: 22px; margin-top: 0; }
h2 { font-size: 18px; margin: 18px 0 8px; }
h3 { font-size: 14px; margin: 16px 0 6px; color: #444; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #eee; font-size: 14px; }
th { width: 110px; color: #555; }
select { font-size: 14px; padding: 4px 6px; }
.fila { white-space: nowrap; }
.letra { display: inline-block; width: 18px; font-size: 12px; color: #777; }
.butaca { width: 26px; height: 24px; margin: 1px; padding: 0; font-size: 10px; border-radius: 4px;
          border: 1px solid #7a9a7a; background: #e6f4e6; color: #234; cursor: pointer; }
.butaca.elegida { background: #1f3864; border-color: #1f3864; color: #fff; }
.butaca.reservada, .butaca.vendida { background: #ddd; border-color: #ccc; color: #999; cursor: default; }
.referencias { font-size: 12px; color: #555; margin: 12px 0; }
.referencias .butaca { display: inline-block; width: 14px; height: 14px; margin-left: 10px;
                       cursor: default; vertical-align: middle; }
.nota { background: #fff8e1; border: 1px solid #f0d58a; padding: 10px 12px; font-size: 14px; }
.aviso { background: #fdecea; border: 1px solid #f1b0a8; padding: 10px 12px; font-size: 14px; }
.vencida { color: #b00020; font-weight: bold; }
.boton { display: inline-block; margin-top: 8px; padding: 10px 16px; background: #1f3864; color: #fff;
         text-decoration: none; border: 0; border-radius: 4px; font-size: 14px; cursor: pointer; }
.boton:disabled { background: #9aa5b8; cursor: default; }
.boton.secundario { background: #fff; color: #1f3864; border: 1px solid #1f3864; }
footer { text-align: center; font-size: 12px; color: #888; margin-top: 12px; }
"""

PASOS = """
<p id="aviso" class="aviso" hidden></p>

<section id="paso-elegir" hidden>
  <h2 id="evento"></h2>
  <label>Función: <select id="funcion"></select></label>
  <div id="mapa"></div>
  <p class="referencias">
    <span class="butaca libre">&nbsp;</span> libre
    <span class="butaca elegida">&nbsp;</span> la que elegiste
    <span class="butaca vendida">&nbsp;</span> ocupada
  </p>
  <p id="resumen"></p>
  <button id="reservar" class="boton" disabled>Reservar</button>
</section>

<section id="paso-pagar" hidden>
  <h2>Tus butacas están reservadas</h2>
  <table>
    <tr><th>Función</th><td id="pago-evento"></td></tr>
    <tr><th>Butacas</th><td id="pago-butacas"></td></tr>
    <tr><th>Total</th><td id="pago-total"></td></tr>
  </table>
  <p>Te las guardamos por <b id="reloj"></b>. Si no pagás en ese tiempo, vuelven a quedar libres.</p>
  <p class="nota">Por ahora el pago es simulado: al tocar "Pagar" la compra se confirma.
  La pasarela de pago la conectamos más adelante.</p>
  <button id="pagar" class="boton">Pagar</button>
  <button id="cancelar" class="boton secundario">Elegir otras butacas</button>
</section>

<section id="paso-listo" hidden>
  <h2>¡Listo! La compra está confirmada</h2>
  <table>
    <tr><th>Compra</th><td id="listo-codigo"></td></tr>
    <tr><th>Función</th><td id="listo-evento"></td></tr>
    <tr><th>Butacas</th><td id="listo-butacas"></td></tr>
    <tr><th>Total</th><td id="listo-total"></td></tr>
  </table>
  <p id="listo-mail"></p>
  __VOLVER__
</section>
"""


def pagina_checkout(cliente, sesion, reserva=None, orden=None):
    nombre = escape(NOMBRES.get(cliente, cliente))
    script = ""

    if sesion is None:
        cuerpo = "<h1>No encontramos esa compra</h1><p>El link no es válido o es de otro sitio.</p>"
    else:
        volver = ""
        if sesion["url_retorno"]:
            volver = f'<a class="boton" href="{escape(sesion["url_retorno"])}">Volver a {nombre}</a>'

        segundos = (sesion["vence"] - datetime.now(timezone.utc)).total_seconds()
        if segundos <= 0 and orden is None:
            cuerpo = f"""
            <h1>Comprá tus entradas para {nombre}</h1>
            <p class="vencida">La sesión venció. Volvé al sitio y empezá la compra de nuevo.</p>
            {volver}
            """
        else:
            # Lo que necesita checkout.js va en un bloque de datos aparte, no mezclado con el código
            datos = json.dumps(jsonable_encoder({
                "sesion_id": sesion["id"],
                "evento_id": sesion["evento_id"],
                "max_butacas": MAX_BUTACAS,
                "reserva": reserva,
                "orden": orden,
            })).replace("<", "\\u003c")
            cuerpo = f"""
            <h1>Comprá tus entradas para {nombre}</h1>
            {PASOS.replace("__VOLVER__", volver)}
            <script id="datos" type="application/json">{datos}</script>
            """
            script = f"<script>{SCRIPT}</script>"

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Checkout - {nombre}</title>
<style>{ESTILO}</style>
</head>
<body>
<main>{cuerpo}</main>
<footer>Venta de entradas de {nombre} · powered by TicketStar</footer>
{script}
</body>
</html>"""

"""Página de checkout que alojamos nosotros (forma A de integración).

El sitio del cliente manda a la persona acá con el id de la sesión de compra.
Por ahora sólo muestra la sesión; elegir butacas y pagar llega en la Entrega 3.
"""
from datetime import datetime, timezone
from html import escape

NOMBRES = {"teatro-avenida": "Teatro Avenida", "club-atletico": "Club Atlético"}

ESTILO = """
body { font-family: Arial, sans-serif; background: #f3f4f6; margin: 0; color: #222; }
main { max-width: 560px; margin: 40px auto; background: #fff; padding: 28px 32px;
       border: 1px solid #ddd; border-radius: 8px; }
h1 { font-size: 22px; margin-top: 0; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #eee; font-size: 14px; }
th { width: 110px; color: #555; }
.nota { background: #fff8e1; border: 1px solid #f0d58a; padding: 10px 12px; font-size: 14px; }
.vencida { color: #b00020; font-weight: bold; }
.boton { display: inline-block; margin-top: 8px; padding: 10px 16px; background: #1f3864;
         color: #fff; text-decoration: none; border-radius: 4px; }
footer { text-align: center; font-size: 12px; color: #888; margin-top: 12px; }
"""


def pagina_checkout(cliente, sesion):
    nombre = escape(NOMBRES.get(cliente, cliente))

    if sesion is None:
        cuerpo = "<h1>No encontramos esa compra</h1><p>El link no es válido o es de otro sitio.</p>"
    else:
        segundos = (sesion["vence"] - datetime.now(timezone.utc)).total_seconds()
        if segundos <= 0:
            estado = '<p class="vencida">La sesión venció. Volvé al sitio y empezá la compra de nuevo.</p>'
        elif segundos < 60:
            estado = "<p>Te queda <b>menos de un minuto</b> para terminar la compra.</p>"
        else:
            estado = f"<p>Tenés <b>{int(segundos // 60)} minutos</b> para terminar la compra.</p>"

        volver = ""
        if sesion["url_retorno"]:
            volver = f'<a class="boton" href="{escape(sesion["url_retorno"])}">Volver a {nombre}</a>'

        cuerpo = f"""
        <h1>Comprá tus entradas para {nombre}</h1>
        {estado}
        <table>
          <tr><th>Usuario</th><td>{escape(sesion["usuario_externo"])}</td></tr>
          <tr><th>Evento</th><td>N° {escape(str(sesion["evento_id"] or "-"))}</td></tr>
          <tr><th>Sesión</th><td><code>{escape(str(sesion["id"]))}</code></td></tr>
        </table>
        <p class="nota">Acá la persona va a elegir las butacas y pagar.
        Esa parte la estamos haciendo para la Entrega 3.</p>
        {volver}
        """

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
</body>
</html>"""

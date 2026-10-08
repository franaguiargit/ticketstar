// Sitio de prueba del Teatro Avenida, que hace de cliente de TicketStar.
//
// Es otro sistema, de "otra empresa": corre en su propio docker compose y se
// conecta con TicketStar sólo por HTTP, como lo haría un teatro de verdad.
// Lo hicimos en Node y no en Python a propósito, para mostrar que la conexión
// no depende de en qué está hecho cada lado. No usa librerías, sólo lo que trae Node.

const http = require("node:http");

const PUERTO = Number(process.env.PUERTO || 3000);
// Dónde está la API de TicketStar (llamadas de servidor a servidor)
const TICKETSTAR_API = process.env.TICKETSTAR_API || "http://teatro-avenida.ticketstar.localhost";
// Dirección de este sitio, para que el checkout sepa a dónde volver
const URL_SITIO = process.env.URL_SITIO || "http://localhost:3001";

// El login del teatro todavía no está hecho, así que usamos siempre este usuario
const USUARIO = { id: "socio-1024", nombre: "Ana", email: "ana@example.com" };

async function llamarTicketStar(metodo, ruta, cuerpo) {
  let respuesta;
  try {
    respuesta = await fetch(TICKETSTAR_API + ruta, {
      method: metodo,
      headers: cuerpo ? { "Content-Type": "application/json" } : undefined,
      body: cuerpo ? JSON.stringify(cuerpo) : undefined,
      signal: AbortSignal.timeout(5000),
    });
  } catch {
    throw new Error("TicketStar no responde");
  }
  const datos = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) {
    const detalle = typeof datos.detail === "string" ? datos.detail : `error ${respuesta.status}`;
    throw new Error(detalle);
  }
  return datos;
}

function escapar(texto) {
  const reemplazos = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(texto ?? "").replace(/[&<>"']/g, (c) => reemplazos[c]);
}

// "2026-10-15T21:00:00" -> "15/10 a las 21:00"
function formatearFecha(iso) {
  const [fecha, hora] = iso.split("T");
  const [, mes, dia] = fecha.split("-");
  return `${dia}/${mes} a las ${hora.slice(0, 5)}`;
}

function pagina(titulo, contenido) {
  return `<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapar(titulo)}</title>
<style>
  body { font-family: Georgia, serif; margin: 0; background: #faf6f0; color: #2b2b2b; }
  header { background: #6d1a1a; color: #fff; padding: 18px 28px; }
  header h1 { margin: 0; font-size: 26px; }
  header p { margin: 4px 0 0; font-size: 14px; opacity: .85; }
  main { max-width: 760px; margin: 24px auto; padding: 0 16px; }
  .evento { background: #fff; border: 1px solid #e3d9cc; border-radius: 6px; padding: 14px 18px; margin-bottom: 14px; }
  .evento h3 { margin: 0 0 4px; font-size: 20px; }
  .lugar { color: #777; font-size: 14px; margin: 0 0 8px; }
  .funciones { font-size: 14px; margin: 6px 0 10px; }
  button { background: #6d1a1a; color: #fff; border: 0; padding: 8px 14px; border-radius: 4px; cursor: pointer; font-size: 14px; }
  .aviso { background: #fff3cd; border: 1px solid #e0c36a; padding: 12px 14px; border-radius: 6px; }
  footer { text-align: center; font-size: 12px; color: #888; margin: 30px 0; }
</style>
</head>
<body>
<header><h1>Teatro Avenida</h1><p>Hola, ${escapar(USUARIO.nombre)} · Mi cuenta</p></header>
<main>${contenido}</main>
<footer>Venta de entradas powered by TicketStar</footer>
</body>
</html>`;
}

async function paginaCartelera() {
  let contenido;
  try {
    const { eventos } = await llamarTicketStar("GET", "/v1/eventos");
    contenido = "<h2>Cartelera</h2>" + eventos.map((evento) => `
      <div class="evento">
        <h3>${escapar(evento.nombre)}</h3>
        <p class="lugar">${escapar(evento.lugar)} · ${escapar(evento.descripcion)}</p>
        <div class="funciones">Funciones: ${evento.funciones.map((f) => formatearFecha(f.fecha)).join(" · ")}</div>
        <form method="post" action="/comprar">
          <input type="hidden" name="evento_id" value="${evento.id}">
          <button>Comprar entradas</button>
        </form>
      </div>`).join("");
  } catch (error) {
    contenido = `<p class="aviso">No pudimos cargar la cartelera (${escapar(error.message)}).
      El resto del sitio sigue funcionando, probá de nuevo en un rato.</p>`;
  }
  return pagina("Teatro Avenida", contenido);
}

function leerFormulario(req) {
  return new Promise((resolve, reject) => {
    let cuerpo = "";
    req.on("data", (parte) => { cuerpo += parte; });
    req.on("end", () => resolve(new URLSearchParams(cuerpo)));
    req.on("error", reject);
  });
}

function responder(res, estado, html) {
  res.writeHead(estado, { "Content-Type": "text/html; charset=utf-8" });
  res.end(html);
}

const servidor = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/") {
      responder(res, 200, await paginaCartelera());
    } else if (req.method === "POST" && req.url === "/comprar") {
      const formulario = await leerFormulario(req);
      // Abrimos la compra en TicketStar en nombre de nuestro usuario y lo mandamos a su checkout
      const sesion = await llamarTicketStar("POST", "/v1/sesiones", {
        usuario_externo: USUARIO.id,
        email: USUARIO.email,
        evento_id: Number(formulario.get("evento_id")) || null,
        url_retorno: URL_SITIO + "/",
      });
      res.writeHead(303, { Location: sesion.url_checkout });
      res.end();
    } else if (req.method === "GET" && req.url === "/salud") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ sitio: "teatro-avenida", estado: "ok" }));
    } else {
      responder(res, 404, pagina("No encontrado", "<p>Esa página no existe.</p>"));
    }
  } catch (error) {
    responder(res, 502, pagina("Error", `<p class="aviso">No pudimos abrir la compra (${escapar(error.message)}).
      Probá de nuevo en un rato.</p><p><a href="/">Volver a la cartelera</a></p>`));
  }
});

servidor.listen(PUERTO, () => {
  console.log(`Sitio del Teatro Avenida escuchando en el puerto ${PUERTO}`);
  console.log(`Usa la API de TicketStar en ${TICKETSTAR_API}`);
});

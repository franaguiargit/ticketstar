// Checkout de TicketStar (forma A). Corre en el navegador de la persona y usa la
// misma API que usaría el sistema de un cliente, siempre por el gateway.

const datos = JSON.parse(document.getElementById("datos").textContent);
const $ = (id) => document.getElementById(id);

let funcionId = null;
let elegidas = new Set();
let botones = {};          // código de butaca -> su botón en el mapa
let precios = {};
let reserva = datos.reserva;
let reloj = null;
let refresco = null;

async function api(metodo, ruta, cuerpo) {
  try {
    const respuesta = await fetch(ruta, {
      method: metodo,
      headers: cuerpo ? { "Content-Type": "application/json" } : {},
      body: cuerpo ? JSON.stringify(cuerpo) : undefined,
    });
    const json = await respuesta.json().catch(() => ({}));
    return { estado: respuesta.status, datos: json };
  } catch {
    return { estado: 0, datos: { detail: "No hay conexión con TicketStar" } };
  }
}

const plata = (monto) => "$" + Number(monto).toLocaleString("es-AR");

// "2026-10-15T21:00:00" -> "15/10 a las 21:00"
function formatearFecha(iso) {
  const [fecha, hora] = iso.split("T");
  const [, mes, dia] = fecha.split("-");
  return `${dia}/${mes} a las ${hora.slice(0, 5)}`;
}

function avisar(texto) {
  $("aviso").textContent = texto || "";
  $("aviso").hidden = !texto;
}

function mostrar(paso) {
  clearInterval(refresco);
  clearInterval(reloj);
  for (const nombre of ["elegir", "pagar", "listo"]) {
    $("paso-" + nombre).hidden = nombre !== paso;
  }
}

// ---------------------------------------------------------------- paso 1: elegir las butacas
async function elegirButacas() {
  mostrar("elegir");
  if (!datos.evento_id) {
    avisar("Esta compra no tiene un evento elegido. Volvé al sitio y elegí qué querés ver.");
    return;
  }
  if (!$("funcion").options.length) {
    const r = await api("GET", "/v1/eventos/" + datos.evento_id);
    if (r.estado !== 200) {
      avisar(`No pudimos cargar las funciones (${r.datos.detail}). Probá de nuevo en un rato.`);
      return;
    }
    $("evento").textContent = `${r.datos.nombre} · ${r.datos.lugar}`;
    for (const funcion of r.datos.funciones) {
      $("funcion").add(new Option(formatearFecha(funcion.fecha), funcion.id));
    }
  }
  await cambiarFuncion();
  // El mapa se vuelve a pedir cada unos segundos para ver lo que van reservando los demás
  refresco = setInterval(cargarMapa, 4000);
}

async function cambiarFuncion() {
  funcionId = Number($("funcion").value);
  elegidas.clear();
  botones = {};
  $("mapa").innerHTML = "";
  await cargarMapa();
}

async function cargarMapa() {
  const r = await api("GET", `/v1/funciones/${funcionId}/butacas`);
  if (r.estado !== 200) {
    avisar(`No pudimos cargar las butacas (${r.datos.detail}).`);
    return;
  }
  if (!r.datos.butacas.length) {
    $("mapa").textContent = "Esta función todavía no tiene venta por butacas.";
  }
  for (const butaca of r.datos.butacas) {
    if (!botones[butaca.codigo]) agregarAlMapa(butaca);
    if (elegidas.has(butaca.codigo) && butaca.estado !== "libre") {
      elegidas.delete(butaca.codigo);
      avisar(`La butaca ${butaca.codigo} se la acaban de llevar. Elegí otra.`);
    }
    const boton = botones[butaca.codigo];
    boton.className = "butaca " + (elegidas.has(butaca.codigo) ? "elegida" : butaca.estado);
    boton.disabled = butaca.estado !== "libre";
  }
  actualizarResumen();
}

function agregarAlMapa(butaca) {
  const mapa = $("mapa");
  let fila = document.getElementById(`fila-${butaca.sector}-${butaca.fila}`);
  if (!fila) {
    if (!document.getElementById("sector-" + butaca.sector)) {
      const titulo = document.createElement("h3");
      titulo.id = "sector-" + butaca.sector;
      titulo.textContent = `${butaca.sector} · ${plata(butaca.precio)}`;
      mapa.append(titulo);
    }
    fila = document.createElement("div");
    fila.id = `fila-${butaca.sector}-${butaca.fila}`;
    fila.className = "fila";
    const letra = document.createElement("span");
    letra.className = "letra";
    letra.textContent = butaca.fila;
    fila.append(letra);
    mapa.append(fila);
  }
  const boton = document.createElement("button");
  boton.type = "button";
  boton.textContent = butaca.numero;
  boton.title = butaca.codigo;
  boton.dataset.codigo = butaca.codigo;
  boton.onclick = () => elegir(butaca.codigo);
  fila.append(boton);
  botones[butaca.codigo] = boton;
  precios[butaca.codigo] = butaca.precio;
}

function elegir(codigo) {
  avisar("");
  if (elegidas.has(codigo)) {
    elegidas.delete(codigo);
  } else if (elegidas.size >= datos.max_butacas) {
    avisar(`Podés elegir hasta ${datos.max_butacas} butacas por compra.`);
    return;
  } else {
    elegidas.add(codigo);
  }
  botones[codigo].className = "butaca " + (elegidas.has(codigo) ? "elegida" : "libre");
  actualizarResumen();
}

function actualizarResumen() {
  const lista = [...elegidas].sort();
  const total = lista.reduce((suma, codigo) => suma + precios[codigo], 0);
  $("resumen").textContent = lista.length
    ? `Elegiste ${lista.join(", ")}. Total: ${plata(total)}`
    : `Elegí hasta ${datos.max_butacas} butacas en el mapa.`;
  $("reservar").disabled = !lista.length;
}

$("funcion").onchange = () => { avisar(""); cambiarFuncion(); };

$("reservar").onclick = async () => {
  $("reservar").disabled = true;
  const r = await api("POST", "/v1/reservas", {
    sesion_id: datos.sesion_id,
    funcion_id: funcionId,
    butacas: [...elegidas],
  });
  if (r.estado === 201) {
    reserva = r.datos;
    avisar("");
    mostrarPago();
    return;
  }
  // Si otra persona llegó antes, la API contesta 409. Al volver a pedir el mapa, la
  // butaca que perdimos sale de la selección y se avisa cuál fue
  avisar("");
  await cargarMapa();
  if ($("aviso").hidden) avisar(r.datos.detail || "No pudimos hacer la reserva.");
};

// ---------------------------------------------------------------- paso 2: pagar
function mostrarPago() {
  mostrar("pagar");
  $("pago-evento").textContent = `${reserva.evento} · ${formatearFecha(reserva.fecha)}`;
  $("pago-butacas").textContent = reserva.butacas.join(", ");
  $("pago-total").textContent = plata(reserva.total);
  const vence = new Date(reserva.vence).getTime();
  const actualizarReloj = () => {
    const segundos = Math.max(0, Math.round((vence - Date.now()) / 1000));
    const minutos = String(Math.floor(segundos / 60)).padStart(2, "0");
    $("reloj").textContent = `${minutos}:${String(segundos % 60).padStart(2, "0")}`;
    if (segundos === 0) {
      reserva = null;
      elegirButacas().then(() => avisar("Se terminó el tiempo de la reserva. Elegí las butacas de nuevo."));
    }
  };
  actualizarReloj();
  reloj = setInterval(actualizarReloj, 1000);
}

$("pagar").onclick = async () => {
  $("pagar").disabled = true;
  const r = await api("POST", `/v1/reservas/${reserva.id}/confirmar`);
  $("pagar").disabled = false;
  if (r.estado === 200) {
    avisar("");
    mostrarListo(r.datos);
    return;
  }
  const detalle = r.datos.detail || "No pudimos confirmar la compra.";
  if (r.estado === 409) {
    reserva = null;
    await elegirButacas();
  }
  avisar(detalle);
};

$("cancelar").onclick = async () => {
  await api("DELETE", `/v1/reservas/${reserva.id}`);
  reserva = null;
  avisar("");
  elegirButacas();
};

// ---------------------------------------------------------------- paso 3: compra confirmada
function mostrarListo(orden) {
  mostrar("listo");
  $("listo-codigo").textContent = orden.codigo;
  $("listo-evento").textContent = `${orden.evento} · ${formatearFecha(orden.fecha)}`;
  $("listo-butacas").textContent = orden.butacas.join(", ");
  $("listo-total").textContent = plata(orden.total);
  $("listo-mail").textContent = orden.email ? `Te mandamos las entradas a ${orden.email}.` : "";
}

if (datos.orden) mostrarListo(datos.orden);
else if (reserva) mostrarPago();
else elegirButacas();

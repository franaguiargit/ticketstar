# TicketStar

Proyecto final de **Programación Distribuida y Componentes**.

TicketStar es un servicio de venta de entradas que se le ofrece a teatros, clubes y productoras. Cada cliente sigue teniendo su propia página y sus propios usuarios, y se conecta con nosotros por una API. Nosotros resolvemos la venta: la cartelera, la reserva de butacas, el pago, la entrada con QR y el control en la puerta. Cada cliente entra por su propio subdominio (`teatro-avenida.ticketstar...`).

**Integrantes:** Francisco Aguiar y Rodrigo Rodriguez.

## Entregas

| Entrega | Tag | Documentación |
|---|---|---|
| 0. Plan del proyecto | `v0-plan` | [docs/entrega-0](docs/entrega-0) |
| 1. Propuesta de arquitectura (4+1) | `v1-propuesta` | [docs/entrega-1](docs/entrega-1) |
| 2. Infraestructura | `v2-infraestructura` | [docs/entrega-2](docs/entrega-2) |

## Qué hay andando (Entrega 2)

Son dos sistemas separados, cada uno con su propio `docker compose`:

**TicketStar** (este repo, `docker-compose.yml` de la raíz)

| Contenedor | Qué hace | Se ve desde afuera |
|---|---|---|
| `gateway` | nginx. Mira el subdominio para saber de qué cliente es el pedido y lo manda al servicio que corresponde. | Sí, puerto 80 |
| `eventos` | Python + FastAPI. La cartelera de cada cliente (eventos y funciones). | No |
| `ordenes` | Python + FastAPI. Sesiones de compra y la página de checkout. | No |
| `postgres` | Postgres 17. Cada servicio tiene su propio esquema. | No |

**Sitio del Teatro Avenida** (`clientes-demo/teatro-avenida`)

Es un cliente de prueba hecho en Node, como si fuera el sistema de otra empresa. Muestra la cartelera que le pide a TicketStar y, al tocar "Comprar entradas", abre una sesión de compra y manda a la persona a nuestro checkout. Corre en el puerto 3001.

## Cómo levantarlo

### Requisitos

- Docker Desktop (o Docker Engine con el plugin `compose`).
- git.
- Los puertos 80 y 3001 libres. Si el 80 está ocupado, ver [Problemas comunes](#problemas-comunes).

### Paso a paso

1. Clonar el repo y entrar a la carpeta:

   ```bash
   git clone https://github.com/franaguiargit/ticketstar.git
   cd ticketstar
   ```

2. Levantar TicketStar (la primera vez tarda un poco porque construye las imágenes):

   ```bash
   docker compose up -d --build
   ```

3. Ver que estén los cuatro contenedores corriendo:

   ```bash
   docker compose ps
   ```

4. Probar la API con cada cliente. Cada subdominio devuelve solo sus propios eventos:

   ```bash
   curl http://teatro-avenida.ticketstar.localhost/v1/eventos
   curl http://club-atletico.ticketstar.localhost/v1/eventos
   ```

   También se puede abrir en el navegador. Los subdominios de `localhost` apuntan a la propia máquina, así que no hace falta tocar el archivo `hosts`.

5. Levantar el sitio del teatro, que está en otro compose:

   ```bash
   cd clientes-demo/teatro-avenida
   docker compose up -d --build
   ```

6. Abrir <http://localhost:3001>, ver la cartelera y tocar "Comprar entradas". Te tiene que mandar al checkout de TicketStar, en `teatro-avenida.ticketstar.localhost`.

### Probar que cada nodo es independiente

Desde la raíz del repo:

```bash
docker compose stop eventos
curl http://teatro-avenida.ticketstar.localhost/v1/eventos
# -> 503 {"detail": "El servicio no está disponible en este momento"}
```

Con `eventos` apagado, el resto sigue andando: el sitio del teatro muestra un aviso en lugar de la cartelera, pero se puede seguir abriendo una compra porque eso lo hace `ordenes`. Para volver a prenderlo:

```bash
docker compose start eventos
```

En unos segundos el gateway lo vuelve a encontrar. Para ver el estado de cada servicio:

```bash
curl http://localhost/estado/eventos
curl http://localhost/estado/ordenes
```

### Apagar todo

```bash
docker compose down                                    # TicketStar
docker compose -f clientes-demo/teatro-avenida/docker-compose.yml down   # el sitio del teatro
```

Si además se quieren borrar los datos de la base, agregar `-v` al primer comando.

## API (por ahora)

Todas las rutas van por el subdominio del cliente, por ejemplo `http://teatro-avenida.ticketstar.localhost`.

| Método | Ruta | Servicio | Qué hace |
|---|---|---|---|
| GET | `/v1/eventos` | eventos | Lista los eventos del cliente con sus funciones |
| GET | `/v1/eventos/{id}` | eventos | Un evento con sus funciones |
| POST | `/v1/sesiones` | ordenes | Abre una sesión de compra para un usuario del cliente |
| GET | `/v1/sesiones/{id}` | ordenes | Consulta una sesión |
| GET | `/checkout/{id}` | ordenes | Página de checkout (la persona llega acá desde el sitio del cliente) |

Ejemplo para abrir una sesión:

```bash
curl -X POST http://teatro-avenida.ticketstar.localhost/v1/sesiones \
  -H "Content-Type: application/json" \
  -d '{"usuario_externo": "socio-1024", "evento_id": 1, "url_retorno": "http://localhost:3001/"}'
```

La documentación formal de la API (OpenAPI) es parte de la Entrega 4.

## Estructura del repo

```
ticketstar/
  docker-compose.yml        nuestro sistema completo
  gateway/nginx.conf        el gateway: subdominio -> cliente -> servicio
  servicios/
    eventos/                cartelera (FastAPI)
    ordenes/                sesiones de compra y checkout (FastAPI)
  clientes-demo/
    teatro-avenida/         sitio de prueba de un cliente (Node), con su propio compose
  docs/                     una carpeta por entrega
```

## Problemas comunes

- **El puerto 80 está ocupado.** Copiar `.env.example` como `.env`, cambiar `PUERTO_GATEWAY=8080` y usar ese puerto en las URLs (`http://teatro-avenida.ticketstar.localhost:8080/v1/eventos`). El compose del teatro no hay que tocarlo, porque habla con el gateway por adentro de Docker.
- **En PowerShell `curl` no funciona igual.** En Windows PowerShell `curl` es otro comando. Usar `curl.exe` en su lugar.
- **El sitio del teatro no levanta y dice que no existe la red `ticketstar-publica`.** Hay que levantar primero TicketStar (paso 2), que es el que crea esa red.
- **Algún navegador no abre `*.localhost`.** Probar con Chrome, Edge o Firefox, o usar curl.

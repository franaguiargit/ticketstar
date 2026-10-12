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
| 3. Comunicación síncrona y asíncrona | `v3-comunicacion` | [docs/entrega-3](docs/entrega-3) |

## Qué hay andando (Entrega 3)

Ya se puede comprar de punta a punta: elegir las butacas, reservarlas, pagar (por ahora simulado) y recibir el mail. Son dos sistemas separados, cada uno con su propio `docker compose`:

**TicketStar** (este repo, `docker-compose.yml` de la raíz)

| Contenedor | Qué hace | Se ve desde afuera |
|---|---|---|
| `gateway` | nginx. Mira el subdominio para saber de qué cliente es el pedido y lo manda al servicio que corresponde. | Sí, puerto 80 |
| `eventos` | Python + FastAPI. La cartelera de cada cliente: eventos, funciones y cómo es cada sala. | No |
| `ordenes` | Python + FastAPI. Sesiones de compra, reserva de butacas, órdenes y la página de checkout. | No |
| `notificaciones` | Python. Escucha la cola y manda el mail de cada compra. No tiene API. | No |
| `postgres` | Postgres 17. Cada servicio tiene su propio esquema. | No |
| `rabbitmq` | RabbitMQ 4.3. La cola de avisos entre nuestros servicios. | Solo su consola, en esta máquina (15672) |
| `mail` | Mailpit. Una casilla de prueba que hace de servidor de mail de afuera. | Solo su pantalla, en esta máquina (8025) |

**Sitio del Teatro Avenida** (`clientes-demo/teatro-avenida`)

Es un cliente de prueba hecho en Node, como si fuera el sistema de otra empresa. Muestra la cartelera que le pide a TicketStar, abre la compra y manda a la persona a nuestro checkout. Cuando vuelve, le muestra sus entradas. Corre en el puerto 3001.

### Cómo se comunican

| De | A | Cómo | Por qué |
|---|---|---|---|
| Sitio del teatro y checkout | gateway y servicios | REST (síncrono) | Hay una persona esperando la respuesta en la pantalla. |
| `ordenes` | `eventos` | REST (síncrono), por la red interna | Para armar las butacas de una función, órdenes necesita saber en ese momento cómo es la sala. |
| `ordenes` | `notificaciones` | Mensajes por RabbitMQ (asíncrono) | Nadie espera el mail mirando la pantalla. Si notificaciones está apagado, el aviso queda en la cola. |

La explicación completa está en el [informe de la Entrega 3](docs/entrega-3).

## Cómo levantarlo

### Requisitos

- Docker Desktop (o Docker Engine con el plugin `compose`).
- git.
- Los puertos 80 y 3001 libres, y también el 8025 y el 15672 (se abren solo en la propia máquina). Si el 80 está ocupado, ver [Problemas comunes](#problemas-comunes).
- Para las pruebas, Python 3.10 o más nuevo.

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

3. Ver que estén los siete contenedores corriendo:

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

6. Abrir <http://localhost:3001>, tocar "Comprar entradas" en algún evento y hacer la compra: elegir las butacas en el mapa, "Reservar" y "Pagar". El checkout es de TicketStar y está en `teatro-avenida.ticketstar.localhost`.

7. Ver el mail de la compra en la casilla de prueba, <http://localhost:8025>, y la compra en "Mis entradas" del sitio del teatro.

### Probar el caso de concurrencia

Dos personas que quieren la misma butaca al mismo tiempo. Desde la raíz del repo:

```bash
python pruebas/concurrencia.py
```

Larga 20 pedidos a la vez por la misma butaca, varias veces. En cada ronda tiene que quedar una sola reserva y 19 rechazos. En [pruebas/README.md](pruebas/README.md) está cómo ver el mismo script fallando sin el arreglo, y cómo correr las pruebas de navegador.

### Probar el canal asíncrono

```bash
docker compose stop notificaciones
# hacer una compra: se confirma igual y el aviso queda esperando en la cola
docker compose exec rabbitmq rabbitmqctl list_queues name messages consumers
docker compose start notificaciones
# en unos segundos el mail aparece en http://localhost:8025
```

La cola también se puede mirar en la consola de RabbitMQ, <http://localhost:15672> (usuario y clave `ticketstar`).

### Probar que cada nodo es independiente

Desde la raíz del repo:

```bash
docker compose stop eventos
curl http://teatro-avenida.ticketstar.localhost/v1/eventos
# -> 503 {"detail": "El servicio no está disponible en este momento"}
```

Con `eventos` apagado, el resto sigue andando: el sitio del teatro muestra un aviso en lugar de la cartelera, y las funciones que órdenes ya conoce se siguen vendiendo. Para volver a prenderlo:

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

Si además se quieren borrar los datos de la base y de la cola, agregar `-v` al primer comando.

## API (por ahora)

Todas las rutas van por el subdominio del cliente, por ejemplo `http://teatro-avenida.ticketstar.localhost`.

| Método | Ruta | Servicio | Qué hace |
|---|---|---|---|
| GET | `/v1/eventos` | eventos | Lista los eventos del cliente con sus funciones |
| GET | `/v1/eventos/{id}` | eventos | Un evento con sus funciones |
| POST | `/v1/sesiones` | ordenes | Abre una sesión de compra para un usuario del cliente |
| GET | `/v1/sesiones/{id}` | ordenes | Consulta una sesión |
| GET | `/v1/funciones/{id}/butacas` | ordenes | El mapa de butacas de una función, con el estado de cada una |
| POST | `/v1/reservas` | ordenes | Reserva butacas por 10 minutos. Si alguna ya no está libre responde 409 y no reserva ninguna |
| GET | `/v1/reservas/{id}` | ordenes | Consulta una reserva |
| DELETE | `/v1/reservas/{id}` | ordenes | Cancela una reserva sin pagar y suelta las butacas |
| POST | `/v1/reservas/{id}/confirmar` | ordenes | Confirma la compra (por ahora el pago es simulado) y crea la orden |
| GET | `/v1/ordenes?usuario_externo=` | ordenes | Las compras de un usuario del cliente |
| GET | `/v1/ordenes/{id}` | ordenes | Una orden |
| GET | `/checkout/{id}` | ordenes | Página de checkout (la persona llega acá desde el sitio del cliente) |

Ejemplo para abrir una sesión y reservar una butaca:

```bash
curl -X POST http://teatro-avenida.ticketstar.localhost/v1/sesiones \
  -H "Content-Type: application/json" \
  -d '{"usuario_externo": "socio-1024", "email": "ana@example.com", "evento_id": 1}'

curl -X POST http://teatro-avenida.ticketstar.localhost/v1/reservas \
  -H "Content-Type: application/json" \
  -d '{"sesion_id": "EL-ID-DE-LA-SESION", "funcion_id": 1, "butacas": ["Platea-C-7", "Platea-C-8"]}'
```

Las rutas que empiezan con `/interno` son para que los servicios se llamen entre ellos por la red interna. El gateway no las publica.

La documentación formal de la API (OpenAPI) es parte de la Entrega 4.

## Estructura del repo

```
ticketstar/
  docker-compose.yml        nuestro sistema completo
  gateway/nginx.conf        el gateway: subdominio -> cliente -> servicio
  servicios/
    eventos/                cartelera y salas (FastAPI)
    ordenes/                sesiones, reservas, órdenes y checkout (FastAPI)
    notificaciones/         escucha la cola y manda los mails
  clientes-demo/
    teatro-avenida/         sitio de prueba de un cliente (Node), con su propio compose
  pruebas/                  el script de concurrencia y las pruebas de navegador
  docs/                     una carpeta por entrega
```

## Problemas comunes

- **El puerto 80 está ocupado.** Copiar `.env.example` como `.env`, cambiar `PUERTO_GATEWAY=8080` y usar ese puerto en las URLs (`http://teatro-avenida.ticketstar.localhost:8080/v1/eventos`). El compose del teatro no hay que tocarlo, porque habla con el gateway por adentro de Docker. Al script de concurrencia hay que avisarle: `python pruebas/concurrencia.py --gateway http://127.0.0.1:8080`.
- **En PowerShell `curl` no funciona igual.** En Windows PowerShell `curl` es otro comando. Usar `curl.exe` en su lugar.
- **El sitio del teatro no levanta y dice que no existe la red `ticketstar-publica`.** Hay que levantar primero TicketStar (paso 2), que es el que crea esa red.
- **Algún navegador no abre `*.localhost`.** Probar con Chrome, Edge o Firefox, o usar curl.
- **Un programa que no es el navegador ni curl no encuentra `teatro-avenida.ticketstar.localhost`.** Fuera del navegador ese nombre no siempre se resuelve solo, depende de la red. Se puede llamar al gateway por su dirección y mandar el subdominio aparte, que es lo que hacen nuestras pruebas: `curl -H "Host: teatro-avenida.ticketstar.localhost" http://127.0.0.1/v1/eventos`.
- **Ya tenía levantada la Entrega 2.** No hace falta borrar nada: con `docker compose up -d --build` los servicios agregan solos las tablas nuevas.

# Pruebas

Acá están las pruebas que corremos contra el sistema levantado (ver el [README de la raíz](../README.md)). Todas entran por el gateway, igual que los pedidos de un cliente.

| Archivo | Qué prueba | Qué hace falta |
|---|---|---|
| `concurrencia.py` | El caso de concurrencia: muchos pedidos a la vez por la misma butaca. | Solo Python 3.10 o más nuevo |
| `test_compra.py` | La compra completa en un navegador: sitio del teatro, checkout, reserva, pago, mail y "Mis entradas". | pytest y Playwright |
| `test_misma_butaca.py` | Dos navegadores que eligen la misma butaca y tocan "Reservar" a la vez. | pytest y Playwright |
| `test_reglas.py` | Las reglas del diseño: que un cliente no vea nada de otro, que solo se entre por el gateway y que la reserva quede entera o no quede. | pytest y Playwright |

## El caso de concurrencia

Con TicketStar levantado, desde la raíz del repo:

```bash
python pruebas/concurrencia.py
```

En cada ronda el script elige una butaca libre, abre 20 sesiones de compra y larga los 20 pedidos de reserva al mismo tiempo. Tiene que quedar una sola reserva hecha y 19 rechazos con código 409. La última ronda es con pedidos de dos butacas que se pisan entre sí, para ver que no queda media reserva hecha. Al terminar cancela las reservas, así se puede correr las veces que haga falta.

```
Ronda 1: butaca Pullman-G-16  reservas hechas: 1   rechazos (409): 19  OK   (salieron en 4 ms)
...
RESULTADO: BIEN. En las 6 rondas cada butaca quedó para un solo pedido.
```

Opciones: `--pedidos 50` para largar más pedidos por ronda, `--rondas 10` para probar más butacas y `--gateway http://127.0.0.1:8080` si el gateway no está en el puerto 80.

Si se levanta más de una instancia de órdenes (`docker compose up -d --scale ordenes=2`), al final el script muestra cuántos pedidos atendió cada una.

### Ver el problema sin el arreglo

Para mostrar que el problema existe de verdad, órdenes tiene guardada la versión ingenua de la reserva (primero mira si la butaca está libre y después la marca). Se prende con una variable:

1. En el archivo `.env` de la raíz (si no existe, copiar `.env.example`), poner `RESERVA_SIN_CONTROL=1`.
2. Aplicar el cambio: `docker compose up -d ordenes`
3. Correr el script de nuevo. No falla en todas las rondas, porque depende de cómo se crucen los pedidos, pero en varias aparece más de una reserva para la misma butaca:

   ```
   Ronda 3: butaca Pullman-H-17  reservas hechas: 3   rechazos (409): 17  PROBLEMA
            -> 3 pedidos distintos creen que la butaca Pullman-H-17 es suya
   RESULTADO: MAL. En 2 de 6 rondas una butaca quedó para más de un pedido.
   ```

4. Volver a dejar `RESERVA_SIN_CONTROL=0` y correr otra vez `docker compose up -d ordenes`.

Las dos versiones están una al lado de la otra en [`servicios/ordenes/app/reservas.py`](../servicios/ordenes/app/reservas.py): `tomar_butaca` y `tomar_butaca_sin_control`.

## Las pruebas de navegador

Usan [Playwright](https://playwright.dev/python/), que maneja un navegador de verdad. Hay que tener levantados TicketStar y el sitio del teatro.

```bash
pip install -r pruebas/requirements.txt
playwright install chromium
pytest pruebas
```

Si no se quiere bajar un navegador, se puede usar el Chrome o el Edge que ya esté instalado: `pytest pruebas --browser-channel chrome` (o `msedge`). Con `--headed` se ve el navegador mientras corre.

Si el gateway no está en el puerto 80, avisarle con la misma variable que usa el compose:

```bash
PUERTO_GATEWAY=8080 pytest pruebas          # en PowerShell: $env:PUERTO_GATEWAY=8080; pytest pruebas
```

Las pruebas compran entradas de verdad en la base de prueba. Para volver a tener las salas vacías: `docker compose down -v` y levantar de nuevo.

### El vencimiento de la reserva

Una reserva sin pagar dura 10 minutos, así que esa prueba normalmente se saltea. Para correrla hay que levantar órdenes con una reserva corta y avisarle lo mismo a pytest:

```bash
# en .env: SEGUNDOS_RESERVA=3   y después   docker compose up -d ordenes
SEGUNDOS_RESERVA=3 pytest pruebas -k vence
```

## Probar el canal asíncrono a mano

1. Apagar el servicio de notificaciones: `docker compose stop notificaciones`
2. Hacer una compra desde <http://localhost:3001>. Se confirma igual, porque órdenes no espera a nadie.
3. Ver el aviso esperando en la cola, en <http://localhost:15672> (usuario y clave `ticketstar`), o con:

   ```bash
   docker compose exec rabbitmq rabbitmqctl list_queues name messages consumers
   ```

4. Prender el servicio: `docker compose start notificaciones`. En unos segundos el mail aparece en <http://localhost:8025>.

Lo mismo se puede hacer apagando RabbitMQ (`docker compose stop rabbitmq`): la compra se confirma, el aviso queda guardado en la base de órdenes y sale cuando RabbitMQ vuelve.

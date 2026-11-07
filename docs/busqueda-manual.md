# Búsqueda manual con progreso en tiempo real

Botón **Buscar ahora** en la pestaña Ofertas. Lanza la misma corrida de siempre
(adaptadores, ingesta, deduplicación, clasificación y cola persistentes) y muestra
el avance real mientras ocurre.

## Lo que ve el usuario

```
Buscar ahora → Buscando fuentes → Analizando ofertas → Resultados actualizados → Búsqueda finalizada
```

| Elemento | De dónde sale |
|---|---|
| Fase y fuente en curso | `source_runs.estado = 'running'` de la corrida |
| Barra de progreso | `(completadas + fallidas + canceladas) / total_fuentes` |
| Contadores de la corrida | `SUM(observaciones)`, `SUM(nuevas)`, `SUM(duplicadas)` de `source_runs` |
| Elegibles / dudosas / incompatibles | catálogo vigente en `analyses` (`obsoleto = 0`) |
| IA | `ia_queue`, `settings.ia_habilitada` y la ventana de cuota del modelo |
| Resumen final | `runs.resumen_json`, escrito antes de cerrar la corrida |

El porcentaje no se estima: al planificar se crea una fila `source_runs` en
`pending` por cada fuente, y esa fila avanza de estado cuando la fuente terminó de
verdad. Con 14 fuentes la barra se mueve 14 veces, ni una más.

## Por qué consulta periódica en lugar de SSE

Se evaluaron las dos opciones. Se eligió **consulta periódica** (`/progreso.json`
cada ~1,2 s mientras hay corrida, cada 8 s si no la hay):

1. **El avance es grueso.** Una fuente tarda entre 1 y 5 segundos. Empujar eventos
   con latencia de milisegundos no agrega fidelidad: agrega infraestructura.
2. **El dato ya está persistido.** El panel lee tablas, así que una petición
   normal devuelve exactamente lo mismo que un evento. SSE obligaría a mantener un
   generador asíncrono con su propia conexión a SQLite por pestaña, en un servidor
   que hoy abre y cierra una conexión por request.
3. **Se prueba sin navegador.** Un endpoint JSON se verifica con el cliente de
   pruebas y con `urllib` en la verificación por socket real. Un flujo SSE necesita
   pruebas de streaming y un cliente que sepa leer eventos.
4. **Degrada bien.** Si el servidor se cae, la siguiente consulta simplemente
   falla y se reintenta; un SSE quedaría colgado y habría que reconstruirlo.

El costo es 1 request por segundo contra una base local: despreciable frente a las
descargas HTTP que la corrida está haciendo en paralelo.

## Estados y mensajes

| Fase | Condición | Texto |
|---|---|---|
| `preparando` | corrida activa sin fuentes planificadas | Preparando la búsqueda |
| `fuentes` | alguna fuente en `running` | Buscando fuentes · *nombre* |
| `analizando` | sin fuente en curso y cola con pendientes | Analizando ofertas |
| `finalizada` | `estado = completed` | Búsqueda finalizada |
| `cancelada` | `estado = cancelled` | Búsqueda cancelada |
| `fallida` | `estado = failed` | La búsqueda falló |
| `abandonada` | `running` sin latido (o sin candado) | La búsqueda quedó interrumpida |

## Una sola corrida por vez

Tres guardas, cada una tapa un agujero distinto:

1. **Candado en memoria** (`app.state.candado`): dos hilos en el mismo proceso.
2. **La base** (`progreso.activa`): dos pestañas, o un reinicio del servidor en
   medio.
3. **El mutex de archivo del trabajador**: distingue una corrida viva de una que
   quedó `running` porque el proceso murió. Un latido reciente no prueba que
   alguien esté trabajando; poder tomar el candado sí.

Si ya hay una corrida, la segunda pulsación **no** inicia otra: devuelve la que
existe y la interfaz muestra su progreso.

### Corridas fantasma

Si el proceso muere a mitad (corte de luz, cierre forzado), la fila queda
`running` para siempre y bloquearía el botón. Se resuelve con dos mecanismos:

- `heartbeat_at` se actualiza entre fuentes; con más de 180 s sin latido la
  corrida se informa como abandonada;
- al pulsar el botón, si el latido es reciente pero el candado del trabajador está
  libre, se marca `abandoned` y se permite buscar de nuevo.

Las fuentes que no llegaron a correr quedan `cancelled`, no `success`: el progreso
no cuenta como procesado lo que no se procesó.

## Cancelar

Es **cooperativa**: el trabajador consulta la bandera `runs.cancelada` entre
fuentes. La fuente en curso termina —cortarla dejaría una descarga a medias— y las
siguientes no arrancan. Lo descargado y clasificado se conserva, y la cola mantiene
sus pendientes para la próxima corrida.

## Resultados incrementales

La cola de clasificación se drena **después de cada fuente**, no al final. Así las
ofertas nuevas aparecen en la lista mientras el resto sigue bajando. La interfaz
detecta el cambio por `ofertas.clasificadas`, vuelve a pedir la misma página y
reemplaza sólo el contenido de `#lista-ofertas`: filtros, orden y acciones
(Guardar, Me interesa, Descartar) siguen intactos porque el HTML es el mismo.

## IA

El resumen informa si la IA está habilitada, cuántas ofertas esperan en `ai_queue`
y si la cuota gratuita está disponible. **La corrida no enciende la IA**: si está
apagada en Configuración, no se llama a ningún proveedor. Esta búsqueda nunca
activa proveedores ni consume saldo pago.

## Sin JavaScript

El botón sigue existiendo como formulario `POST /buscar`, que redirige a la página
de origen. El progreso se guarda igual en la base: recargando se ve el avance. No
hay actualización automática, y la página lo dice.

## Verificación

```bat
.venv\Scripts\python.exe -m pytest tests\test_busqueda_manual.py -q
.venv\Scripts\python.exe tools\verificar_interfaz.py            :: 27 comprobaciones
.venv\Scripts\python.exe tools\verificar_interfaz.py --buscar   :: 30, con búsqueda real
```

La verificación por socket real incluye: el botón en la página, el panel, el JS
servido, `/progreso.json`, el arranque, la doble pulsación (que no duplica), la
cancelación en vuelo, el avance con estados distintos y el resumen final.

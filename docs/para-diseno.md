# Para el agente de diseño (UX/UI)

Todo lo que sigue es **funcional y estable**. El objetivo de este documento es que
el cuarto agente sepa qué puede tocar sin romper nada y dónde están las piezas.

Lo que esta sesión **no** hizo, a propósito: modo oscuro, paleta, tipografías,
animaciones, material gráfico, README promocional, redes sociales y cualquier
cambio puramente estético.

## Punto de entrada

| Archivo | Qué es |
|---|---|
| `buscador/web/templates/base.html` | Layout, navegación, **todos los estilos en un `<style>`** |
| `buscador/web/templates/ofertas.html` | Lista con filtros + panel «Buscar ahora» |
| `buscador/web/templates/_lista_ofertas.html` | Tarjeta de oferta (se reutiliza para el refresco incremental) |
| `buscador/web/templates/_busqueda.html` | Panel de búsqueda manual con progreso |
| `buscador/web/templates/detalle.html` | Ficha: análisis, razones, acciones y seguimiento de postulación |
| `buscador/web/templates/postuladas.html` | Seguimiento de postulaciones |
| `buscador/web/templates/diagnostico.html` | Última búsqueda y estado del catálogo |
| `buscador/web/static/progreso.js` | Sondeo de `/progreso.json` y refresco de la lista |

Reglas del sistema visual actual (sin framework, sin build):

- Variables CSS en `:root`: `--fondo`, `--panel`, `--texto`, `--suave`, `--borde`,
  `--acento`, `--ok`, `--duda`, `--no`.
- Clases semánticas reutilizables: `.card`, `.kpi`, `.badge` (+ `.eligible`,
  `.doubtful`, `.incompatible`, `.postulada`, `.remote`, `.excluye`), `.aviso`
  (+ `.bien`, `.alerta`), `.grilla`, `.barra`, `.acciones`, `.chico`, `.sub`.
- El tema es claro y está fijo. Cambiar a oscuro implica tocar las variables y
  revisar contraste de `.badge`, `.aviso` y `.kpi`.

## Contratos que el diseño **no** debe romper

1. **`#lista-ofertas`** debe existir y contener sólo tarjetas: el refresco
   incremental reemplaza su `innerHTML` cuando aparecen ofertas nuevas
   (`progreso.js`).
2. **`#panel-busqueda`** y los `id` que usa el JS (`#btn-buscar`, `#btn-cancelar`,
   `#busqueda-fase`, `#busqueda-barra`, `#busqueda-relleno`, `#busqueda-fuentes`,
   `#busqueda-cola`, `#busqueda-ia`, `#busqueda-nota`, `#busqueda-resumen`,
   `#busqueda-nuevas`, `#c-revisadas`, `#c-nuevas`, `#c-duplicadas`,
   `#c-elegibles`, `#c-dudosas`, `#c-incompatibles`, `#conteo-ofertas`,
   `#progreso-cabecera`). Hay una prueba que verifica que existan
   (`tests/test_busqueda_manual.py`).
3. **Formularios con `csrf`**: cualquier acción POST necesita el campo oculto.
4. **No mostrar «postulada» como si fuera «me interesa»**: son estados distintos y
   el backend los guarda separados.
5. **Cada cifra que se muestre debe venir de los datos**; no se inventan métricas
   ni porcentajes.

## Datos disponibles para diseñar

`GET /progreso.json` (sin caché) devuelve:

```json
{
  "activo": true, "estado": "running", "version": 12345,
  "fuentes": {"total": 14, "pendientes": 3, "ejecutando": 1, "completadas": 10,
              "fallidas": 0, "canceladas": 0, "procesadas": 10, "fraccion": 0.71,
              "actual": "F04", "actual_nombre": "Remote OK", "detalle": [...]},
  "ofertas": {"revisadas": 573, "nuevas": 62, "duplicadas": 58,
              "elegibles": 3, "dudosas": 15, "incompatibles": 1281,
              "clasificadas": 70, "ultima_clasificacion": "..."},
  "ia": {"habilitada": true, "pendientes": 0, "analizando": 0, "en_corrida": 0,
         "cuota": {"disponible": true, "motivo": "...", "modelo": "gemini:..."}},
  "resumen": {"duracion_ms": 24000, "fuentes_ok": 14, "errores": [],
              "nuevas": 60, "candidatas": 18, "candidatas_nuevas": 3}
}
```

En la ficha (`detalle.html`) cada oferta trae:

- `oferta.elegibilidad`, `.compatibilidad`, `.confianza`, `.motivo_elegibilidad`
- `oferta.componentes` (una entrada por componente con `nombre`, `maximo`,
  `obtenido`, `estado` y `detalle`)
- `oferta.razones` (texto + efecto: `suma`, `duda`, `excluye`, `salvedad`)
- `oferta.incertidumbres`, `.decisivas`
- `oferta.requisitos` (alcance territorial, estados de experiencia/formación/
  idioma/viajes, fechas)
- `oferta.postulacion` y `oferta.historial_postulacion`

## Estados de un componente (lo que el diseño debe poder mostrar)

| Estado | Significado | Sugerencia de lectura |
|---|---|---|
| `cumplido` | el aviso lo exige y el perfil lo cumple | verde |
| `parcial` | hay evidencia incompleta | ámbar |
| `sin_datos` | **no se sabe** (no suma puntos) | gris, con texto explícito |
| `no_aplicable` | el requisito no existe para esa oferta | fuera de la lista |
| `incumplido` | lo exige y no se cumple (suele excluir) | rojo |

La distinción `sin_datos` / `cumplido` es el corazón de rules-3.0.0: si el diseño
las muestra igual, se pierde la corrección.

## Pantallas y su función

| Ruta | Función | Qué conviene mejorar |
|---|---|---|
| `/ofertas` | compatibles, con panel de búsqueda | jerarquía del panel, legibilidad de contadores |
| `/dudosas` | falta información para decidir | explicar *qué* falta, no sólo que falta |
| `/todas` | auditoría de descartes | mostrar el motivo del descarte de un vistazo |
| `/guardadas` | decisiones del usuario | estado y fecha de cada decisión |
| `/postuladas` | postulaciones reales | línea de tiempo, agrupación por mes |
| `/duplicados` | mismo puesto en varias fuentes | comparación lado a lado |
| `/fuentes` | salud por fuente | rendimiento real por fuente |
| `/actividad` | corridas y avisos | historial legible; la bandeja distingue puntaje al avisar del vigente y marca recomendaciones desactualizadas |
| `/diagnostico` | última búsqueda vs catálogo | separar visualmente los dos bloques |
| `/config` | perfil, IA, respaldos | formulario largo: agrupar por tema |

## Lo que ya está resuelto y no hace falta rediseñar

- Búsqueda manual con progreso real y resultados incrementales.
- Cancelación cooperativa que conserva el trabajo.
- Reclasificación determinista (sin IA) y autoreparación de la cola.
- Seguimiento de postulaciones con historial.
- Diagnóstico con cifras que coinciden con la base.
- Bandeja de Actividad con registros legibles (no rediseñar su lógica de datos).

**Contrato de plantillas:** la pastilla de no leídos de `base.html` usa
`avisos_no_leidos` (entero). No renombrarla a `avisos`: en `/actividad` ese nombre
es la lista de la bandeja y se volcarían diccionarios en la cabecera.

## Accesibilidad mínima ya presente

- `<label>` con `for` en los campos de seguimiento.
- `role="progressbar"` con `aria-valuenow` en la barra.
- Navegación por teclado: son `<a>`, `<button>` y `<form>` nativos.
- Contraste: pendiente de revisión formal en el rediseño.

## Cómo probar sin romper

```bat
.venv\Scripts\python.exe -m pytest tests\test_busqueda_manual.py tests\test_postulaciones.py -q
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe tools\verificar_interfaz.py
.venv\Scripts\python.exe tools\verificar_interfaz.py --buscar
```

Las dos últimas verifican sobre uvicorn real: si un `id` desaparece o un formulario
pierde el `csrf`, fallan.

# Simulación de sincronización (07/11/2026)

**Estado:** simulado, **no publicado**. No se creó ningún commit de sincronización,
no se actualizó `docs/publicacion/estado.json` y no se hizo push. `origin/main`
sigue donde estaba antes de esta auditoría.

Se eligió la tercera alternativa: corregir la lógica de sincronización y
saneamiento. No se modificó `buscador/rules.py` a mano ni se agregó a
`NO_SINCRONIZAR`; el archivo se sincroniza completo.

## 1. Por qué el saneador bloqueaba la sincronización

`sincronizar()` generaba un parche crudo con `git diff base..head` **del
original** y lo aplicaba con `git apply --check` sobre **la copia publicable**.
Son dos espacios distintos:

| | Original | Copia publicable |
|---|---|---|
| Saltos de línea | LF | CRLF (`core.autocrlf=true`) |
| Texto | con datos personales | anonimizado por `saneado.py` |
| `buscador/rules.py` en la base | versión cruda | versión saneada, con una frase anónima corregida a mano |

El contexto del parche nunca coincide. Concretamente, en `buscador/rules.py` la
copia tenía dos diferencias respecto de la representación saneada de la base:
los saltos CRLF y una frase de documentación reescrita a mano. Como encima el
cambio real era grande (rules-2.0.0 → rules-3.0.0), `git apply --check` fallaba
y la sincronización abortaba todo el lote.

No era un problema de `rules.py`: era un problema de comparar representaciones
distintas. Las otras dos salidas (excluir el archivo o editar el original para
que el parche calce) eran peores: la primera dejaba código viejo en la copia y
la segunda modificaba el motor por una cuestión de empaquetado.

## 2. Corrección: comparar representaciones saneadas equivalentes

- `saneado.sanear_texto(texto, ruta)` — única definición del saneado, en
  memoria. Normaliza saltos y aplica las mismas reglas que `sanear()` usa en
  disco. No hay dos saneadores que puedan divergir.
- `saneado.verificar_texto(texto, ruta)` — la misma puerta de datos sensibles,
  aplicable a un contenido antes de escribirlo.
- `saneado.huella_funcional(texto, ruta)` — para `.py`, huella del AST sin
  docstrings ni comentarios; para el resto, huella del texto normalizado.
  Distingue «cambió una frase» de «cambió una función».
- `saneado.clasificar_cambio(base, head, ruta)` — compara ambas versiones del
  original ya saneadas e informa si el cambio es funcional o equivalente.
- `publicar._resolver_por_saneado()` — cuando un parche crudo no aplica, escribe
  la representación saneada del head **sólo si pasan tres guardas**:

  1. la copia no tiene divergencia funcional propia respecto de la base saneada
     (si la tiene, aborta: no se pisa trabajo local);
  2. la versión saneada del head pasa `verificar_texto` (la puerta de secretos
     sigue activa, también en memoria);
  3. un cambio que desaparece al sanear se acepta únicamente si la huella
     funcional confirma que no tocó código.

Ningún control de seguridad se desactivó: siguen `verificar()` sobre el árbol
completo, las pruebas, la comprobación de historial reescrito y la prohibición
de force push.

- `publicar simular` — corre exactamente el mismo `sincronizar()` sobre un clon
  temporario. Omite commit, registro y push; informa el diff y una huella del
  árbol para verificar reproducibilidad.

## 3. Resultados de la simulación

Comando: `py -3 tools/publicar.py simular` (y la variante `--sin-pruebas`).

Rango: `78a9d7a..a97b9b3`, 6 commits, 39 archivos en el diff.

| Resultado | Cantidad |
|---|---|
| Aplicados por parche | 35 |
| Reemplazados por representación saneada | 3 |
| Equivalentes (sin cambios publicables) | 0 |
| Omitidos (versión saneada propia) | 1 |
| **Conflictos** | **0** |

Reemplazados:

- `buscador/rules.py` — código, vía comparación saneada. Entra completo:
  **530 líneas cambiadas** en el diff del clon (rules-2.0.0 → rules-3.0.0).
- `docs/CONTINUIDAD.md` y `docs/evidencia/pytest.txt` — documentación, por el
  mecanismo de reemplazo ya existente.

Controles:

- Puerta de datos sensibles sobre el árbol completo: **0 hallazgos**.
- Saneado aplicado en 5 archivos nuevos que traían datos personales del
  original; luego de sanear, 0 hallazgos.
- Pruebas dentro del clon (`pytest -q`): **339 superadas** en la primera
  simulación completa; con las 22 pruebas nuevas ya incorporadas, la suite de
  la copia pasa **270/270** antes de sincronizar.
- Huella del árbol: `fa5c5737d75ff991`, **idéntica** al repetir la simulación
  con y sin pruebas. Dos ejecuciones independientes dan el mismo árbol.

La simulación no modificó el repositorio real: el registro y el HEAD quedaron
iguales, y la raíz activa se restauró al salir.

## 4. Pruebas de regresión agregadas

`tests/test_publicacion.py`, 22 pruebas (antes 3). Cubren los cinco puntos
pedidos:

1. **Anonimización**: nombre, correo, usuario, equipo, ruta, dato sensible y
   banda salarial sintéticos desaparecen; el user agent deja el contacto en el
   entorno; `sanear()` es idempotente y conserva CRLF.
2. **No se filtran datos ni secretos**: la puerta detecta cada familia
   (claves de proveedor, tokens, clave privada, correo, equipo, dato sensible,
   banda, URL con credenciales) y sigue activa en el árbol y en las reglas;
   `local.json` está fuera de Git.
3. **No se excluye código necesario**: `buscador/rules.py` no está en
   `NO_SINCRONIZAR`, sigue en la copia y aparece en el diff simulado; un cambio
   de código se propaga completo.
4. **Cambios funcionales reales**: la huella AST detecta un `return 1` →
   `return 2`; un cambio sólo de texto anónimo se clasifica como equivalente;
   una divergencia local real y un head con secreto terminan en conflicto.
5. **Reproducible e idempotente**: dos simulaciones dan la misma huella, el
   simulador no toca registro ni HEAD, y `sincronizar` con la base al día no
   cambia nada.

Nota: los patrones prohibidos se construyen por partes dentro del propio test
para que el archivo de pruebas no dispare la puerta que audita.

## 5. Qué queda pendiente

- Ejecutar `py -3 tools/publicar.py sincronizar` (commit local en la copia) y
  luego el push, **recién cuando la persona responsable lo autorice**. La simulación demuestra
  que el bloqueo desapareció, pero no se publicó nada.
- Los cambios de esta auditoría (`tools/publicar.py`,
  `tools/publicacion/saneado.py`, `tests/test_publicacion.py` y este informe)
  se commitean localmente en la copia publicable; no se empujan.

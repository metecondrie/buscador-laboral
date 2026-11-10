# Fase 1C — riesgos de versión, persistencia y plan de activación

**Estado: documento de planificación. NADA de esto se ejecutó.** No se activaron
reglas, no se reclasificó, no se tocó la base operativa ni el perfil.

## 0. Alcance real de la Fase 1C

| Elemento | Estado |
|---|---|
| `buscador/rules.py` | reparado (estructural) |
| `tests/corpus_fase1c.py`, `tests/test_fase1c_adversarial.py` | nuevos |
| `config.RULES_VERSION` | `rules-3.0.0` **sin cambios** |
| `buscador/schema.sql`, `worker.py`, `perfil.py`, `config.py`, `textutil.py` | hash idéntico al respaldo |
| `%LOCALAPPDATA%\BuscadorLaboral\data\buscador.db` | SHA-256 `ef42a29f…c3a715714` (sin cambios) |
| `%LOCALAPPDATA%\BuscadorLaboral\data\perfil.json` | SHA-256 `8d0aafb1…ed109c565f` (sin cambios; inglés B1) |
| Git | sin commit, push, reset, restore, checkout ni stash |

Los cambios previos del usuario (`notify.py`, `progreso.py`, `web.py`,
plantillas, tests de actividad/ranking/web) quedaron intactos.

---

## 1. Riesgo de mantener `rules-3.0.0` con otra implementación

`analyses.rules_version` es la **única** marca de «con qué criterio se calculó
este veredicto». Dos motores distintos bajo la misma versión son
indistinguibles en la base y en la auditoría.

- `worker.sincronizar_reglas()` (worker.py:261-277) sólo invalida filas con
  `rules_version <> config.RULES_VERSION`. Con la versión congelada **no
  invalida nada**: los veredictos viejos siguen `obsoleto=0` y conviven con los
  nuevos calculados de cero, sin marca que los separe.
- `worker.py:689-705` hace `INSERT ... ON CONFLICT(job_id, job_version_id,
  profile_version_id, rules_version) DO UPDATE SET ...`. La clave única incluye
  `rules_version`; con la misma versión, una reclasificación **sobrescribe en el
  lugar** `elegibilidad`, `score`, `componentes_json`, `razones_json`,
  `incertidumbres_json` y `creado_en=excluded.creado_en`.
- Consecuencia: `componentes_json` y `razones_json` anteriores se pierden y
  `creado_en` deja de ser la fecha real del primer análisis. No se puede
  reconstruir ni auditar el veredicto previo de esa fila.
- Punto a favor: **no hay** `DELETE FROM analyses` en el código. Las filas de
  otra `rules_version` sobreviven como `obsoleto=1`. El historial se preserva
  **sólo si se cambia la versión antes de reclasificar**.

## 2. Interrupciones durante una reclasificación

- `guardar_perfil()` (worker.py:131-157) y `sincronizar_reglas()` ejecutan
  `UPDATE analyses SET obsoleto=1` en una transacción y **después** encolan y
  procesan. Si el proceso se corta en medio: todos los análisis quedan
  obsoletos, la cola queda llena y el catálogo muestra cero clasificaciones
  vigentes. Es exactamente el incidente del 07/11 ya documentado.
- `reclasificar_todo()` (worker.py:233) reencola con `unique_key` que incluye
  `config.RULES_VERSION`. Con versión congelada, una corrida nueva puede no
  reencolar lo que se espera y mezclar criterios sin avisar.
- Mitigación obligatoria en el piloto: respaldo de DB + `BUSCADOR_DATA_DIR`
  temporal + lote acotado + `procesar=False` + drenado explícito + verificación
  de conteos (`COUNT(*) WHERE obsoleto=0`, `tasks`, `runs`) antes de cerrar.

## 3. Veredictos humanos y postulaciones

- `validation_reviews` (schema.sql:386) guarda `veredicto`, `estado_previo`,
  `score_previo`; `applications` (schema.sql:167) guarda `estado`, `fecha`,
  `enlace`, `notas`. **Ninguna** de las dos depende de `analyses` ni se borra
  por una reclasificación.
- Riesgo real, no destructivo: `estado_previo` / `score_previo` son una
  instantánea. Si el puntaje cambia, el veredicto humano queda comparado con
  un valor viejo. Hay que **documentar** el cambio de criterio, no tocar el
  veredicto.
- `notifications` usa `clave` por job y `worker._corresponde_aviso` evita
  reenvíos por recálculo cosmético; un cambio de veredicto sí puede generar
  avisos nuevos. Verificar en el piloto, nunca en la base operativa.

## 4. Rollback entre versiones

- Con la versión congelada **no hay rollback selectivo posible**: reponer el
  código no revierte los análisis ya escritos, porque no hay marca de época.
- Con versión nueva, las filas viejas quedan `obsoleto=1` y conviven gracias a
  la clave única. Rollback = reponer `RULES_VERSION`, marcar obsoletas las
  filas de la versión nueva y reactivar las anteriores, **sin borrar nada**.
- Pero si ya se reclasificó con la versión vieja, su `creado_en` y sus JSON
  fueron sobreescritos (§1). De ahí la regla: **primero cambiar versión,
  después cualquier reclasificación**, aunque sea un piloto.

## 5. Riesgo concreto de `perfil --real` (B1 → B2)

- `buscador/__main__.py:407-418`: `--real` llama
  `worker.guardar_perfil(conn, rutas, perfil_mod.perfil(rutas), origen=ORIGEN)`.
- `perfil_mod.PERFIL_EJEMPLO["idioma"]["ingles"] == "B2"` (constante de
  demostración), mientras el `perfil.json` **operativo** declara inglés B1.
- Efecto combinado: sobreescribe `perfil.json` con B2, crea una versión de
  perfil, marca **todos** los `analyses` obsoletos y reencola todo. Es decir:
  eleva el nivel de inglés **y** dispara una reclasificación masiva no
  autorizada.
- Protección concreta, **sin alterar `perfil.json`** (para una fase separada):
  1. En `cmd_perfil`, antes de `--real`, leer el `perfil.json` vigente y
     comparar `idioma.ingles` contra `perfil_mod.perfil(rutas)`. Si difiere,
     **abortar** con un mensaje que muestre ambos valores. Guardia de sólo
     lectura, no modifica archivos.
  2. Exigir un flag explícito `--confirmar-nivel` para permitir la divergencia.
  3. Regenerar el perfil siempre desde `perfil.json`, nunca desde `PERFIL_EJEMPLO`.
  4. Hasta implementarla: **no ejecutar `perfil --real`**. Las suites usan una
     copia `PERFIL_B1`; `test_perfil_operativo_b1_y_constante_de_demostracion_b2_intactas`
     deja la divergencia documentada y vigilada.

---

## 6. Plan de activación y reclasificación piloto (NO ejecutado)

1. Respaldar `buscador.db` y `perfil.json` con SHA-256; pausar el scheduler.
2. Subir `RULES_VERSION` a `rules-3.1.0` en `config.py` y actualizar el
   encabezado de `rules.py`. **Esquema sin cambios**: no hace falta migración
   SQL, `VERSION_ESQUEMA` queda igual.
3. Implementar la guardia de `perfil --real` del §5 (toca `__main__.py`, fuera
   del alcance de esta fase).
4. Piloto en una **copia** de la DB (`BUSCADOR_DATA_DIR` temporal, sin red):
   muestra de 25 ofertas de `docs/AUDITORIA_25_OFERTAS.md`, con atención a
   #4, #5, #6, #10, #20 (territorio/husos) y #21 (inglés B1/B2). Lote acotado,
   `procesar=False`, drenado explícito.
5. Verificar en la copia: filas `obsoleto=1` conservan `componentes_json`,
   `razones_json` y `creado_en`; `validation_reviews` y `applications` siguen
   con los mismos conteos y valores; `tasks` sin `running` huérfanas;
   `notifications` sin reenvíos duplicados.
6. Revisión humana de los 25 veredictos contra los veredictos ya guardados.
   Registrar las diferencias, no sobrescribirlas.
7. Sólo con autorización expresa: aplicar el cambio de versión a la DB
   operativa y una reclasificación acotada, monitoreando `runs`/`tasks`.
8. Rollback: restaurar el respaldo de DB, reponer `RULES_VERSION`, y —si hace
   falta— reponer `rules.py.1B` desde el respaldo. Nunca `git restore/reset/
   checkout -- .`, nunca `rm` sobre la base.

## 7. Bloqueos fuera del alcance autorizado

- Cambiar `RULES_VERSION`, `schema.sql`, `worker.py` o la persistencia → fase
  separada; aquí sólo se analizó el riesgo.
- La guardia de `perfil --real` requiere editar `__main__.py` (CLI) →
  documentada, **no implementada**.
- Activar/bajar F05, resolver incidentes, tocar scheduler o automatizaciones →
  fuera de alcance.
- **Publicación**: la regla permanente «todo cambio del buscador se cierra
  publicando» queda **pospuesta** por la prohibición explícita de esta fase
  (sin commit, push ni `publicar.py`). No se corrió `tools/publicar.py`.

## 8. Respaldos y rollback selectivo

- `.workbuddy-ai/respaldos/fase1c-20261109-1343/`: `MANIFEST.sha256`
  verificado con `sha256sum -c`, `arbol-trabajo.tar.gz` del árbol de trabajo,
  `rules.py.1B` / `.FASE1` / `.HEAD`, copias de `config.py`, `perfil.py`,
  `worker.py`, `schema.sql`, `textutil.py` y `git-status.txt`.
- Rollback selectivo (no destructivo, conserva los demás cambios del usuario):
  ```
  cp .workbuddy-ai/respaldos/fase1c-20261109-1343/rules.py.1B buscador/rules.py
  rm tests/corpus_fase1c.py tests/test_fase1c_adversarial.py
  .venv/Scripts/python.exe -m pytest -q     # debe volver a 464 passed
  ```
- Entorno aislado de decisión: `.workbuddy-ai/sandbox/fase1c/` con cuatro
  variantes (`head`, `fase1`, `fase1b`, `fase1c`) y `sonda.py`.

# Trazabilidad

Cada fila indica qué parte del requisito está cubierta hoy y qué falta. El
aprobador de etapa es el usuario; la revisión independiente sigue pendiente.

| Requisito | Módulo | Prueba | Estado | Qué falta |
| --- | --- | --- | --- | --- |
| R01 categorías | `rules.py` | P07 | **Cubierto** | Validar la taxonomía con el perfil real |
| R02 experiencia/formación/idioma | `rules.py` | P07 | **Parcial** | Formación sin finalizar y experiencia por proyectos; falta tu validación de la muestra |
| R03 territorio/contrato | `rules.py`, adaptadores | P07 | **Parcial** | Modalidad sí; tipo de contrato se guarda como texto |
| R04 salario/vigencia | `rules.py`, `ingest.py`, `comun.py` | P07 | **Cubierto** | Salario sin conversión de moneda ni período, por diseño |
| R05 fuentes | `adapters/` | P02 | **Cubierto con salvedad** | 14 fuentes; sólo 4 aportan ofertas postulables hoy. 10 aportan 0 |
| R06 contrato de rastreo | `adapters/base.py` | P02, P04 | **Cubierto** | Particiones, errores tipados, metadatos auditables |
| R07 identidad/historial | `ingest.py`, `merge.py` | P06, P09, P14 | **Cubierto** | Fusión sugerida y reversible; alias de empresa pendientes |
| R08 diagnóstico | `incidents.py`, `diagnostics.py` | P04, P18 | **Cubierto** | Bandeja de incidentes, salud por fuente, paquete exportable y bloque de clasificación con ofertas analizadas, pendientes y elegibilidad |
| R09 ranking explicado | `rules.py` | P07, P08 | **Parcial** | Tres dimensiones visibles y 24 falsos positivos corregidos; falta que marques los 25 veredictos |
| R10 salarios | `ingest.py` | P07 | **Parcial** | Solo dato publicado; investigación salarial es H4 |
| R11 IA controlada | `ai/` | P11, P12 | **Cubierto** (una oferta) | Cascada gratuita, credenciales del sistema, cuotas, caché, diagnóstico tipado y consumo discriminado; una generación real a USD 0. Falta el lote masivo |
| R12 onboarding real | `web.py`, `config.html` | P01, P05 | **Cubierto** | Editor de perfil que reclasifica; falta asistente paso a paso |
| R13 automático | `scheduler.py` | P03, P17 | **Parcial** | Hilo interno probado; sigue cada 12 h sin depender de la búsqueda manual; tarea de Windows bloqueada por el entorno |
| R14 dashboard | `web.py`, `progreso.py` | P01, P05, P09, P17 | **Cubierto** | 10 páginas, búsqueda manual con progreso en vivo y resultados incrementales; sin métricas p95 |
| R15 interés | `web.py`, `user_events` | P09 | **Cubierto** | — |
| R16 avisos | `notify.py`, `delivery_attempts` | P10 | **Parcial** | Bandeja local sólida; escritorio opcional sin verificar de punta a punta |
| R17 perfil/CV | `perfil.py`, `config.html` | P12 | **Parcial** | Perfil real desde memoria, con niveles de habilidad; CV por oferta es H3 |
| R18 postulación | — | P16 | **No aplica** | Fuera de alcance: no se postula |
| R19 CRM | — | P09 | **No implementado** | H3 |
| R20 preparación/exportación | `backups.py` | P15 | **Parcial** | CSV de ofertas; exportación para preparación es H4 |
| R21 instalación/respaldo | `__main__.py`, `backups.py` | P01, P14 | **Cubierto** | Instalación, cierre, respaldo y restauración probados |
| R22 retención/salud | `incidents.py`, `diagnostics.py` | P04, P05 | **Parcial** | Salud y retención de respaldos; política de retención de ofertas pendiente |
| R23 presupuesto | `ai/cliente.py`, `ai_budget` | P11 | **Cubierto y sin gasto** | Tope mensual y cuota por corrida; la generación real verificó costo 0 y que un rechazo no cuenta como cuota |
| R24 seguridad | `web.py`, `fetch.py`, `backups.py` | P12, P13 | **Cubierto** | Host, CSRF, token, SSRF, redirecciones, HTML hostil y fórmulas CSV |
| R25 nube | — | P03 | **No aplica** | Ejecución local por decisión del proyecto |

## Evidencias por archivo

| Artefacto | Ruta |
| --- | --- |
| Instalación y entorno | `docs/instalacion.md` |
| Corrida completa con 11 fuentes | `docs/evidencia/corrida-mvp.json` |
| Verificación de fuentes | `docs/evidencia/fuentes-verificacion.json` |
| Pruebas | `docs/evidencia/pytest.txt` |
| Búsqueda manual (diseño y alternativa descartada) | `docs/busqueda-manual.md` |
| Puntaje: fórmula y comparación antes/después | `docs/puntaje.md` |
| Guía para el agente de diseño | `docs/para-diseno.md` |
| Evidencia de postulación tras reiniciar | `docs/evidencia/postulacion-reinicio.txt` |
| Incidente de la cola de clasificación | `docs/incidente-cola-clasificacion.md` |
| Interfaz por socket real | `docs/evidencia/interfaz.txt` |
| Prueba de IA sobre una oferta real | `docs/evidencia/ia-oferta-real.txt` |
| Estado operativo | `docs/estado.md` |
| Traspaso entre sesiones | `docs/CONTINUIDAD.md` |

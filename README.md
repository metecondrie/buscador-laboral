# Buscador laboral · MVP

Aplicación local para Windows: captura ofertas de **catorce fuentes públicas**, las
clasifica con reglas explicables, guarda tu interés, avisa en una bandeja local,
respalda la base y diagnostica los fallos de cada fuente.

No usa IA por defecto, no envía datos a terceros, no postula y no gasta dinero.
El servidor solo escucha en `127.0.0.1`.

## Abrir

```bat
cd "C:\ruta\donde\clonaste\buscador-laboral"
.venv\Scripts\python.exe -m buscador ui
```

O doble clic en `iniciar.cmd`. La consola muestra un enlace con token de un solo
uso:

```
Abrir:   http://127.0.0.1:8765/entrar?token=...
```

Cerrar: **Configuración → Salir de la aplicación**, `detener.cmd` o
`python -m buscador stop`. Cerrar la pestaña no detiene el servidor.

## Comandos

```bat
.venv\Scripts\python.exe -m buscador buscar                  :: corrida manual
.venv\Scripts\python.exe -m buscador doctor                  :: estado y salud
.venv\Scripts\python.exe -m buscador verificar-fuentes       :: mide cada fuente
.venv\Scripts\python.exe -m buscador respaldar               :: respaldo verificado
.venv\Scripts\python.exe -m buscador restaurar <archivo>     :: restaura (cerrar la app)
.venv\Scripts\python.exe -m buscador exportar --guardadas    :: CSV
.venv\Scripts\python.exe -m buscador programar --estado      :: cada 12 h
.venv\Scripts\python.exe -m buscador diagnosticar            :: paquete ZIP
.venv\Scripts\python.exe -m pytest tests -q                  :: 228 pruebas
.venv\Scripts\python.exe -m buscador validacion               :: revisar 25 ofertas
.venv\Scripts\python.exe -m buscador ia --diagnosticar        :: estado de la clave de IA
.venv\Scripts\python.exe tools\prueba_ia_oferta.py           :: 1 oferta, cuota gratuita
.venv\Scripts\python.exe tools\verificar_interfaz.py --buscar :: 30 comprobaciones reales
```

## Pestañas

| Pestaña | Para qué |
| --- | --- |
| Ofertas | Compatibles, ordenadas por compatibilidad, vigencia y modalidad. Arriba está **Buscar ahora** |
| Dudosas | Falta información para decidir; incluye excepciones por competencias |
| Todas | Auditoría: por qué se descartó cada aviso |
| Guardadas | Tu última decisión fue guardar o interesar |
| Duplicados | Mismo puesto en varias fuentes: aceptar, rechazar o revertir |
| Historial | Decisiones, versiones del contenido y corridas |
| Fuentes | Estado, rendimiento real por fuente y pausa |
| Actividad | Corridas, avisos e incidentes |
| Configuración | Perfil, búsqueda automática, respaldos y IA |
| Diagnóstico | Salud del sistema y paquete exportable |

## Fuentes

We Work Remotely, Himalayas, Jobicy, Remote OK, The Muse, Working Nomads, NoDesk,
Jobspresso, Python.org Jobs, Arbeitnow, Remotive y tres familias de tableros de
empresa (Greenhouse, Lever, Ashby). Todas por RSS o API pública, con atribución y
enlace al aviso original.

Rendimiento medido con el perfil real: 4 de las 14 aportan oportunidades
postulables (Remote OK, We Work Remotely, Ashby, Remotive). Las otras responden
bien pero su inventario es senior o restringido a EE. UU./Europa; se pueden
pausar sin perder datos.

## Cómo se decide

Tres dimensiones separadas, que nunca se mezclan:

1. **Elegibilidad** (filtro duro): categoría, territorio, modalidad, formación y
   seniority. El perfil exige remoto; presencial fuera de La Plata no es elegible.
2. **Compatibilidad** (0–100): cercanía profesional, ponderada por nivel de
   habilidad. Sin habilidades declaradas no hay puntaje.
3. **Confianza** (alta/media/baja): cuánta información real trae el aviso.

Más de un año de experiencia no excluye: entre 2 y 7 años, con ≥ 60 % de las
habilidades cubiertas, se registra una **excepción por competencias**.

## Estructura

| Ruta | Contenido |
| --- | --- |
| `buscador/` | aplicación: configuración, base, adaptadores, reglas, trabajador, interfaz |
| `buscador/adapters/` | once adaptadores y utilidades compartidas |
| `buscador/ai/` | proveedores de IA, política, cuota y presupuesto (apagado) |
| `buscador/web/templates/` | plantillas de la interfaz |
| `tests/` | 228 pruebas sin red y sin gasto |
| `docs/` | estado, continuidad, pruebas, trazabilidad, evidencias |
| `%LOCALAPPDATA%\BuscadorLaboral\` | base, perfil, registros, respaldos y exportaciones |

## Requisitos

- Windows 10/11 x64
- Python 3.14 x64 en `%LOCALAPPDATA%\Programs\Python\Python314` (probado con 3.14.10)
- Entorno virtual en `.venv` (no versionado)

## Instalación en Windows

```bat
cd "C:\ruta\donde\clonaste\buscador-laboral"
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest tests -q
```

Después, doble clic en `iniciar.cmd` o `python -m buscador ui`. La base, los
respaldos y los registros se crean en `%LOCALAPPDATA%\BuscadorLaboral\`, nunca
dentro del repositorio.

## IA opcional (Gemini)

La aplicación funciona completa **sin IA** y sin gasto. Si querés habilitarla:

- El repositorio no contiene ninguna clave, ni en los archivos ni en el historial.
- La clave se busca en este orden: variable de entorno `GEMINI_API_KEY`, luego el
  Administrador de credenciales de Windows (objetivo `BuscadorLaboral/gemini`), y
  por último un archivo DPAPI en `%LOCALAPPDATA%\BuscadorLaboral\credenciales\`.
- Para cargarla: **Configuración → IA** en la interfaz, o definir la variable de
  entorno en tu sesión. Nunca la escribas en un archivo versionado.
- Verificación sin exponer el valor:
  `.venv\Scripts\python.exe -m buscador ia --diagnosticar`.
- Detalle de proveedores, cuotas y política de gasto: `docs/ia-proveedores.md`.

## Perfil: qué se versiona y qué no

El repositorio publica **sólo la estructura** del perfil y un perfil de ejemplo
(genérico, sin datos de nadie). El perfil real nunca se versiona:

| Ubicación | Contenido | En Git |
| --- | --- | --- |
| `buscador/perfil.py` | estructura, ponderaciones y perfil de ejemplo | sí |
| `%LOCALAPPDATA%\BuscadorLaboral\data\perfil.json` | perfil activo (lo escribe la interfaz) | no |
| `%LOCALAPPDATA%\BuscadorLaboral\data\perfil.local.json` | semilla opcional del perfil real | no |
| `%LOCALAPPDATA%\BuscadorLaboral\data\buscador.db` | base con ofertas y decisiones | no |

Si `perfil.local.json` existe, se mezcla sobre el ejemplo al arrancar. Sin ese
archivo la aplicación funciona igual, con el perfil de ejemplo, y
`python -m buscador perfil --real` se niega a pisar el perfil activo con datos
de ejemplo.

## Límites

Presupuesto USD 0: sin llamadas de IA ni servicios pagos. El perfil activo es de
demostración hasta que cargues tus datos en Configuración. La aplicación no
postula y no investiga salarios todavía.

Para retomar el trabajo: `docs/CONTINUIDAD.md`.

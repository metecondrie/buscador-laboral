# Instalación y entorno local

Registro de T01 (parcial) del plan v1.1. Fecha: 06/11/2026, 04:44-05:05, zona `America/Argentina/Buenos_Aires`.

Alcance ejecutado: verificación del artefacto de Python, entorno virtual aislado, dependencias, prueba de arranque de FastAPI en loopback y repositorio Git local. **No** incluye lanzador, cierre por menú Salir, perfil mínimo, base de datos de la aplicación ni tarea programada: eso resta de T01 y no se declara hecho.

## 1. Máquina

| Dato | Valor |
| --- | --- |
| Equipo | `<equipo-local>` |
| Sistema | Windows 10 Pro 22H2, build 19045.6466, x64 |
| RAM | 13,94 GB (6,31 GB libres al inicio) |
| Disco C: | 18,2 GB libres |
| Último parche del sistema | KB5126256, 10/09/2026 |
| `LongPathsEnabled` | 1 |
| Terminal usada | Git Bash (MINGW64) y PowerShell 5.1 |

## 2. Artefacto descargado y verificado

| Dato | Valor |
| --- | --- |
| Archivo | `python-3.14.10-amd64.exe` |
| Origen | `https://www.python.org/ftp/python/3.14.10/python-3.14.10-amd64.exe` |
| Tamaño | 33.498.520 bytes (coincide con el índice FTP de python.org) |
| SHA-256 publicado | `92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965` |
| SHA-256 calculado | `92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965` |
| Comparación | coinciden |
| Firma Authenticode | `Valid` — CN=Python Software Foundation |
| Huella del firmante | `6C435B1CAA2CA423A76C14A6693CD55644C8B4D6` |
| Sello de tiempo | Microsoft Public RSA Time Stamping Authority, válido hasta 14/09/2027 |
| Ubicación temporal | `%TEMP%\python-3.14.10-amd64.exe` (no se copió al repositorio) |

El hash publicado se leyó de la ficha oficial de la release `3.14.10` y se recalculó sobre el archivo descargado antes de ejecutar el instalador.

## 3. Instalación del intérprete

Comando ejecutado:

```
python-3.14.10-amd64.exe /quiet InstallAllUsers=0
    TargetDir=%LOCALAPPDATA%\Programs\Python\Python314
    PrependPath=0 Include_launcher=0 Include_test=0 Include_doc=0
    AssociateFiles=0 Shortcuts=0
```

Código de salida: `0`. Pero el log del bundle registra `WixBundleInstalled = 1` y `WixBundleAction = 6` (Modify): **la instalación ya existía** y esta corrida no copió componentes nuevos. Ver sección 7.

| Dato | Valor |
| --- | --- |
| Ruta | `%LOCALAPPDATA%\Programs\Python\Python314\python.exe` |
| Versión | `3.14.10` |
| Arquitectura | 64 bits (AMD64) |
| SQLite del intérprete | 3.50.4 |
| pip del intérprete | 26.2.2 |
| Registro | `Python 3.14.10 (64-bit)`, versión `3.14.10150.0`, instalación por usuario |

## 4. Efectos sobre el sistema

- **PATH sin cambios.** El PATH persistente del usuario no contiene `Python314` ni su `Scripts`; sigue apuntando a Python 3.12.
- **Instalación previa intacta.** `Python312\python.exe` responde `3.12.0`.
- **El lanzador `py` cambia de predeterminado.** No se reemplazó `py.exe`, pero al estar registrada 3.14, `py -0p` ahora la marca con `*` y `py` resuelve a 3.14 en lugar de 3.12. Es consecuencia automática de la selección por versión más alta. Si conviene fijar 3.12, la vía es `PY_PYTHON=3.12` a nivel usuario; no se aplicó.
- **Otras instalaciones ajenas.** Existen `Anaconda3 2025.12-2 (Python 3.13.9)`, `Python313` y `Python314` previos sin `python.exe` (restos de instalaciones incompletas). No se tocaron.

## 5. Entorno virtual

Se reconstruyó desde cero con la ruta explícita del intérprete nuevo:

```
%LOCALAPPDATA%\Programs\Python\Python314\python.exe -m venv .venv
```

| Dato | Valor |
| --- | --- |
| Ruta | `<RUTA_DEL_PROYECTO>\.venv` |
| `sys.prefix` | `<RUTA_DEL_PROYECTO>\.venv` |
| `sys.base_prefix` | `%LOCALAPPDATA%\Programs\Python\Python314` |
| Versión dentro del venv | `3.14.10` |
| SQLite dentro del venv | `3.50.4` |
| pip dentro del venv | `26.3` |
| Tamaño | 30,4 MB |
| Dependencias | `requirements.txt` (14 paquetes, versiones exactas) |

Instalación: `pip install fastapi uvicorn`. No se instalaron extras (`uvicorn[standard]`, `httptools`, `watchfiles`) porque todavía no hacen falta; se agregarán cuando el trabajador los requiera.

Versiones principales: `fastapi 0.162.0`, `uvicorn 0.54.0`, `starlette 1.10.0`, `pydantic 2.14.3`, `pydantic_core 2.50.4` (rueda nativa `cp314`, sin compilar).

## 6. Comprobaciones del motor SQLite

Ejecutadas sobre un archivo temporal, fuera del repositorio, borrado al terminar:

| Comprobación | Resultado |
| --- | --- |
| `pragma journal_mode=wal` | `wal` (WAL efectivo, con archivos `-wal` y `-shm`) |
| `pragma synchronous=full` | `2` (FULL) |
| `pragma foreign_keys` | `0` — **desactivado por omisión** |
| Escritura y lectura | 1 fila insertada y leída |

Consecuencia para T02: cada conexión que escriba debe activar `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=FULL` y `busy_timeout` explícitamente. El valor por omisión de SQLite no alcanza.

## 7. Anomalía detectada: ejecución previa de la misma tarea

Al iniciar este trabajo la carpeta estaba vacía y sin repositorio (verificado a las 04:45). Entre 04:51 y 04:56, otra ejecución en esta misma máquina:

1. Intentó instalar con `TargetDir` escrito con barras `/`, lo que Windows Installer interpretó como ruta de red (`Error 1606`) y terminó con código `66`.
2. Reintentó sin `TargetDir` a las **04:53:48** y completó la instalación de 3.14.10.
3. Creó `.venv`, instaló dependencias y ejecutó su propia prueba de arranque.
4. Hizo dos commits (`70d8f11`, `828b008`) con `.gitignore`, `requirements.txt`, `docs/instalacion.md` y `tools/`.

Después, los cinco archivos de trabajo desaparecieron del disco: quedaron solo `.git` y `.venv`. El árbol figuraba con esos archivos como borrados sin confirmar.

Qué hice con eso:

- No reescribí la historia: los dos commits se conservan.
- Reconstruí el entorno virtual desde cero para tener evidencia propia y verificable, y moví el anterior a `%TEMP%\buscad0r_venv_previo_0454` en lugar de borrarlo.
- Volví a descargar el instalador y verifiqué hash y firma por mi cuenta; la corrida de instalación resultó ser un Modify sin componentes nuevos, y así queda registrado.
- Reescribí los archivos de trabajo con mis propias mediciones, no copiando las del intento anterior.

Ninguna cifra de este documento proviene del intento previo salvo donde se lo cita explícitamente.

## 8. Prueba de arranque

Comando:

```
.venv\Scripts\python.exe tools\smoke_test.py
```

El script arranca Uvicorn en un hilo sobre `127.0.0.1`, espera a que el servidor esté listo, consulta `/salud` por HTTP, pide el cierre ordenado, espera el hilo y comprueba que el puerto dejó de aceptar conexiones.

Salida real:

```json
{
  "host": "127.0.0.1",
  "puerto": 8011,
  "url": "http://127.0.0.1:8011/salud",
  "arranque_ms": 48.7,
  "http_status": 200,
  "cuerpo": {
    "estado": "ok",
    "python": "3.14.10",
    "sqlite": "3.50.4",
    "prefijo": "<RUTA_DEL_PROYECTO>\\.venv"
  },
  "cierre_ordenado": true,
  "cierre_ms": 138.8,
  "puerto_cerrado": true,
  "resultado": "passed"
}
```

Código de salida: `0`. Comprobado después de la prueba: ningún proceso `python.exe` activo y puerto 8011 sin escuchar. El servidor no se expone fuera de loopback.

## 9. Datos de la aplicación

Ubicación acordada: `%LOCALAPPDATA%\BuscadorLaboral\`, fuera del repositorio. Subcarpetas previstas: `data`, `documents`, `logs`, `cache`, `backups`, `exports`. **Todavía no se crearon**: se hará al implementar persistencia en T02, para no dejar estructura vacía sin uso.

## 10. Repositorio

| Dato | Valor |
| --- | --- |
| Ruta | `<RUTA_DEL_PROYECTO>` |
| Rama | `main` |
| Identidad | `metecondrie <correo@ejemplo>` (configurable con `git config user.email`) |
| Remoto | `origin` → repositorio **privado** en GitHub (rama `main`) |
| Excluido | `.venv/`, `__pycache__/`, datos, bases, `.env`, `.workbuddy-ai/` |

## 11. Pendiente para cerrar T01

1. Lanzador y cierre ordenado con la opción Salir (P01), sin depender de la pestaña del navegador.
2. Diagnóstico de arranque visible en la interfaz: versión de Python y SQLite, errores claros.
3. Crear la estructura de `%LOCALAPPDATA%\BuscadorLaboral\` al implementar T02.
4. Confirmar si el equipo tiene ESU activo: el soporte general de Windows 10 venció el 14/10/2025 y el estado sigue sin verificar.
5. Definir remoto GitHub y estrategia de ramas antes de T02.
6. Decidir si se borra `%TEMP%\buscad0r_venv_previo_0454` y el instalador descargado.

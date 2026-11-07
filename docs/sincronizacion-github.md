# Sincronización con GitHub (privado)

Este repositorio se actualiza con `tools/publicar.py`. No hay sincronización
automática, ni GitHub Actions, ni GitHub Pages.

## Origen y destino

| Rol | Ruta |
| --- | --- |
| Proyecto de trabajo (no se publica) | `%USERPROFILE%\WorkBuddy AI\buscad0r` |
| Copia publicable | `%USERPROFILE%\repos\buscador-laboral` |
| Remoto privado | `https://github.com/metecondrie/buscador-laboral` |

Los dos repositorios no comparten historial: la copia tiene historia propia,
saneada. La relación se registra en `docs/publicacion/estado.json`, que guarda
hasta qué commit del original se incorporó en cada publicación.

## Órdenes

```bat
cd "%USERPROFILE%\repos\buscador-laboral"
py -3 tools/publicar.py estado         :: diagnóstico, no modifica nada
py -3 tools/publicar.py sincronizar    :: trae commits nuevos del original
py -3 tools/publicar.py verificar      :: saneado + pruebas, sin commit
py -3 tools/publicar.py publicar -m "fix: ..."   :: cambios hechos en la copia
```

## Qué hace `sincronizar`

1. Exige que la copia no tenga cambios sin commitear en archivos versionados.
2. Toma `base_original` de `docs/publicacion/estado.json` y el `HEAD` del original.
3. Aplica el diff **por archivo**. Nunca copia el árbol de trabajo del original:
   sólo lo commiteado, así no arrastra lo que otra sesión esté editando.
4. Si un archivo de código no aplica limpio, aborta y no publica nada.
5. Pasa el saneado (`tools/publicacion/saneado.py`): rutas del equipo, correo,
   nombre, equipo, motivo de salud, bandas salariales.
6. Corre la puerta de control: claves, correos, rutas, `.db`, `.env`, logs.
7. Corre las pruebas. Si fallan, el trabajo queda local.
8. Commitea con el rango de commits incorporados y hace push sin `--force`.
9. Verifica que `origin/main` quedó en el mismo commit que el local.

## Qué nunca se publica

`.venv/`, `__pycache__/`, `*.db`, `*.db-wal`, `*.db-shm`, `*.sqlite3`, `data/`,
`documents/`, `logs/`, `cache/`, `backups/`, `exports/`, `.env`,
`config.local.*`, `perfil.local.json`, `.pytest_cache/`, `.workbuddy-ai/`.

## Datos personales

Lo que hay que borrar no está escrito en el código: vive en
`tools/publicacion/local.json`, que **no se versiona** (`local.example.json` es la
plantilla). Ahí van el usuario de Windows, el correo, el nombre, el equipo y las
bandas salariales. Sin ese archivo el saneado sólo aplica las reglas genéricas.

## Credenciales

Ninguna clave se guarda en el repositorio. La de Gemini vive en el Administrador
de credenciales de Windows o en `GEMINI_API_KEY` de la sesión. El push usa Git
Credential Manager, ya autenticado en esta máquina.

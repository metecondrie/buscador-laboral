# Sincronización con GitHub (manual)

Este repositorio es **privado** y se actualiza a mano. No hay sincronización
automática, ni GitHub Actions, ni GitHub Pages.

## Regla de aislamiento

El repositorio de trabajo (`buscad0r`) y este no comparten estado. Ninguno de los
dos es un submódulo del otro y no se configuró ningún remoto en el original.
Publicar no altera el repositorio de trabajo.

## Flujo recomendado

1. Terminar y probar los cambios en el repositorio de trabajo:

   ```bat
   .venv\Scripts\python.exe -m pytest tests -q
   ```

2. Revisar qué va a salir, para no filtrar datos locales:

   ```bat
   git status --short
   git diff --stat
   ```

3. Copiar sólo el código, las pruebas y la documentación al clon de publicación
   (sin `.venv`, sin bases, sin `%LOCALAPPDATA%\BuscadorLaboral`), y commitear ahí:

   ```bat
   cd C:\ruta\del\clon\buscador-laboral
   git add -A
   git commit -m "feat: ..."
   git push origin main
   ```

4. Antes de cada push, repetir la auditoría mínima:

   ```bat
   git grep -nE "AIza[0-9A-Za-z_-]{30,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}"
   git ls-files | findstr /I /R "\.env \.db \.sqlite \.log \.wal \.shm"
   ```

   Ambas búsquedas deben salir vacías.

## Qué nunca se versiona

`.venv/`, `__pycache__/`, `*.db`, `*.db-wal`, `*.db-shm`, `*.sqlite3`, `data/`,
`documents/`, `logs/`, `cache/`, `backups/`, `exports/`, `.env`,
`config.local.*`, `.pytest_cache/`, `.workbuddy-ai/`.

Todo eso ya está en `.gitignore`; si aparece algo nuevo, se agrega ahí antes de
commitear.

## Credenciales

Ninguna clave se guarda en el repositorio. La de Gemini vive en el Administrador
de credenciales de Windows o en la variable de entorno `GEMINI_API_KEY` de la
sesión. Ver `docs/ia-proveedores.md`.

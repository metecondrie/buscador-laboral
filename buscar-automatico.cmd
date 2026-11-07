@echo off
rem Lanzador para el Programador de tareas de Windows.
rem Ejecuta una corrida automática sin abrir la interfaz. No postula a nada.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo No se encontro .venv\Scripts\python.exe
  exit /b 1
)
".venv\Scripts\python.exe" -m buscador buscar --causa programada --respaldo >> "%LOCALAPPDATA%\BuscadorLaboral\logs\programado.log" 2>&1
exit /b %ERRORLEVEL%

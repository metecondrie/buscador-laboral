@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Falta el entorno virtual .venv
  echo Crealo con: "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" -m venv .venv
  exit /b 1
)

echo Iniciando Buscador laboral y abriendo el navegador...
start "Buscador laboral" /min ".venv\Scripts\python.exe" -m buscador ui --abrir

endlocal

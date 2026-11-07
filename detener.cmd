@echo off
setlocal
cd /d "%~dp0"

echo Solicitando cierre ordenado del servidor local...
".venv\Scripts\python.exe" -m buscador stop
echo.
pause

endlocal

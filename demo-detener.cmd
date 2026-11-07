@echo off
rem Cierra los servicios de la demo (API, correo, voz, panel, ngrok y Despierta).
rem La base de datos y Ollama quedan corriendo. Ver scripts\demo.ps1.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\demo.ps1 -Detener
pause

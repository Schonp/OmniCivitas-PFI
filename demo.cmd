@echo off
rem Levanta todo para la demo en vivo. Ver scripts\demo.ps1.
rem   demo.cmd               todo, con el tunel de ngrok al panel
rem   demo.cmd -SinTunel     sin ngrok (solo uso local)
rem   demo.cmd -Detener      cierra los servicios
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\demo.ps1 %*

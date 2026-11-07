@echo off
rem Borra todo lo de un vecino de prueba (registros, casos y memoria de las
rem conversaciones) para empezar de cero. Ver scripts\borrar_vecino.py.
cd /d "%~dp0"
echo Borrar los datos de un vecino de prueba
echo (deja vacio lo que no sepas)
echo.
set /p DNI=DNI, sin puntos:
set /p TEL=Celular con codigo de pais (ej. +5491155550123):
set ARGS=
if not "%DNI%"=="" set ARGS=%ARGS% --dni %DNI%
if not "%TEL%"=="" set ARGS=%ARGS% --telefono %TEL%
if "%ARGS%"=="" (
  echo No ingresaste ningun dato.
  pause
  exit /b 1
)
echo.
.venv\Scripts\python.exe -m scripts.borrar_vecino %ARGS%
echo.
set /p OK=Escribi SI para borrar todo eso:
if /i "%OK%"=="SI" (
  .venv\Scripts\python.exe -m scripts.borrar_vecino %ARGS% --borrar
) else (
  echo No se borro nada.
)
echo.
pause

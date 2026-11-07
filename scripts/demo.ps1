<#
Levanta todo lo que necesita la demo en vivo de OmniCivitas.

  Base de datos (Docker) -> Ollama con el modelo precalentado -> API, correo,
  voz, panel compilado y túnel de ngrok, cada uno en su pestaña de Windows
  Terminal, más una pestaña que impide que la PC se suspenda.

  El túnel apunta al panel: con una sola URL se abre el panel desde otra
  computadora (la laptop en la facultad) y Meta manda ahí el webhook de
  WhatsApp, porque el panel le pasa a la API todo lo que empieza con /api.

  El dominio fijo de ngrok se toma de la línea NGROK_DOMINIO= de .env (o de
  -DominioNgrok). Sin dominio fijo, ngrok da una URL distinta en cada arranque.

Uso (desde la raíz del proyecto, o doble clic en demo.cmd):
  demo.cmd                            todo, con el túnel
  demo.cmd -SinTunel                  todo menos ngrok (solo uso local)
  demo.cmd -DominioNgrok x.ngrok-free.app   otro dominio que el de .env
  demo.cmd -Detener                   cierra API, correo, voz, panel, ngrok y
                                      la pestaña Despierta (la base y Ollama
                                      quedan corriendo)
#>
param(
    [Alias("SinWhatsApp")]
    [switch]$SinTunel,
    [string]$DominioNgrok = "",
    [switch]$Detener
)

$ErrorActionPreference = "Stop"
$Raiz = Split-Path -Parent $PSScriptRoot
Set-Location $Raiz

$Modelo = "omnicivitas-qwen"
$Ventana = "omnicivitas"
$Puertos = @{ API = 8000; Voz = 8001; Panel = 5173; ngrok = 4040 }

function Paso($texto) { Write-Host ""; Write-Host "==> $texto" -ForegroundColor Cyan }
function Bien($texto) { Write-Host "    OK  $texto" -ForegroundColor Green }
function Aviso($texto) { Write-Host "    !!  $texto" -ForegroundColor Yellow }
function Pausa($texto) {
    # Read-Host falla si no hay consola interactiva: ahí simplemente no se pausa.
    try { Read-Host $texto | Out-Null } catch { }
}
function Cortar($texto) {
    Write-Host ""
    Write-Host "    ERROR  $texto" -ForegroundColor Red
    Write-Host ""
    Pausa "Enter para cerrar"
    exit 1
}

function Responde($url) {
    try {
        Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Esperar($url, $segundos) {
    $limite = (Get-Date).AddSeconds($segundos)
    while ((Get-Date) -lt $limite) {
        if (Responde $url) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

# ---------------------------------------------------------------- Detener
if ($Detener) {
    # taskkill escribe en stderr si un hijo ya murió: no es un error real.
    $ErrorActionPreference = "Continue"
    Paso "Cerrando los servicios de la demo"
    foreach ($nombre in $Puertos.Keys) {
        $conexiones = Get-NetTCPConnection -LocalPort $Puertos[$nombre] -State Listen -ErrorAction SilentlyContinue
        $pids = @($conexiones | Select-Object -ExpandProperty OwningProcess -Unique)
        if ($pids.Count -eq 0) { Write-Host "    --  $nombre no estaba corriendo"; continue }
        foreach ($id in $pids) { taskkill /T /F /PID $id 2>$null | Out-Null }
        Bien "$nombre cerrado"
    }
    $correo = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -like "*revisar_correo*" }
    foreach ($p in $correo) { taskkill /T /F /PID $p.ProcessId 2>$null | Out-Null }
    if ($correo) { Bien "Correo cerrado" } else { Write-Host "    --  Correo no estaba corriendo" }
    $despierta = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
        Where-Object { $_.CommandLine -like "*mantener_despierta*" }
    foreach ($p in $despierta) { taskkill /T /F /PID $p.ProcessId 2>$null | Out-Null }
    if ($despierta) { Bien "Despierta cerrado (la PC vuelve a poder suspenderse)" }
    Write-Host ""
    Write-Host "La base de datos y Ollama siguen corriendo." -ForegroundColor DarkGray
    exit 0
}

# ---------------------------------------------------------------- Chequeos previos
Paso "Revisando el proyecto"
foreach ($archivo in @(".env", ".venv\Scripts\python.exe", "voz_asr_tts\.venv\Scripts\python.exe", "frontend\node_modules")) {
    if (-not (Test-Path $archivo)) { Cortar "Falta $archivo (ver SETUP_LAPTOP.md)." }
}
$ocupados = @("API", "Voz", "Panel") | Where-Object {
    Get-NetTCPConnection -LocalPort $Puertos[$_] -State Listen -ErrorAction SilentlyContinue
}
if ($ocupados) {
    Cortar ("Ya hay algo escuchando en: " + ($ocupados -join ", ") + ". Corré primero: demo.cmd -Detener")
}
Bien "Archivos en su lugar y puertos libres"

if (-not $SinTunel -and -not $DominioNgrok) {
    # De .env se lee solo esta línea.
    $linea = Select-String -Path ".env" -Pattern "^\s*NGROK_DOMINIO\s*=\s*(\S+)" | Select-Object -First 1
    if ($linea) { $DominioNgrok = $linea.Matches[0].Groups[1].Value }
}
$DominioNgrok = ($DominioNgrok -replace "^https?://", "").TrimEnd("/")
if (-not $SinTunel) {
    if ($DominioNgrok) { Bien "Túnel con dominio fijo: $DominioNgrok" }
    else { Aviso "Sin NGROK_DOMINIO en .env: la URL del túnel va a ser distinta en cada arranque" }
}

# ---------------------------------------------------------------- Panel compilado
# Se sirve el build y no el servidor de desarrollo: hace muchos menos pedidos
# por el túnel y no recarga la página sola si algo cambia en disco.
Paso "Compilando el panel"
Push-Location (Join-Path $Raiz "frontend")
$ErrorActionPreference = "Continue"
$salidaBuild = npm run build 2>&1 | Out-String
$buildOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"
Pop-Location
if (-not $buildOk) {
    Write-Host $salidaBuild
    Cortar "Falló la compilación del panel (npm run build)."
}
Bien "Panel compilado"

# ---------------------------------------------------------------- Docker y base de datos
Paso "Base de datos (Docker)"
$ErrorActionPreference = "Continue"
docker info *> $null
$dockerVivo = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"
if (-not $dockerVivo) {
    $docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
    if (-not $docker) { Cortar "No encuentro docker en el PATH." }
    # ...\DockerDesktop\resources\bin\docker.exe -> ...\DockerDesktop\Docker Desktop.exe
    $escritorio = Join-Path (Split-Path (Split-Path (Split-Path $docker))) "Docker Desktop.exe"
    if (-not (Test-Path $escritorio)) { $escritorio = "C:\Program Files\Docker\Docker\Docker Desktop.exe" }
    Aviso "Docker Desktop no estaba abierto: lo abro (en frío tarda un par de minutos)"
    Start-Process $escritorio
    $limite = (Get-Date).AddSeconds(240)
    do {
        Start-Sleep -Seconds 3
        $ErrorActionPreference = "Continue"
        docker info *> $null
        $dockerVivo = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = "Stop"
    } until ($dockerVivo -or (Get-Date) -gt $limite)
    if (-not $dockerVivo) { Cortar "Docker no arrancó en 4 minutos. Abrilo a mano y volvé a correr el script." }
}
$ErrorActionPreference = "Continue"
docker compose up -d db 2>&1 | Out-Null
$contenedor = (docker compose ps -q db) | Select-Object -First 1
$ErrorActionPreference = "Stop"
if (-not $contenedor) { Cortar "No se pudo levantar el contenedor de la base (docker compose up -d db)." }
$limite = (Get-Date).AddSeconds(60)
$ErrorActionPreference = "Continue"
do {
    $estado = (docker inspect --format "{{.State.Health.Status}}" $contenedor 2>$null)
    if ($estado -eq "healthy") { break }
    Start-Sleep -Seconds 2
} until ((Get-Date) -gt $limite)
$ErrorActionPreference = "Stop"
if ($estado -ne "healthy") { Cortar "La base no quedó healthy (estado: $estado)." }
Bien "PostgreSQL listo en el puerto 5432"

# ---------------------------------------------------------------- Ollama
Paso "Modelo de lenguaje (Ollama)"
if (-not (Responde "http://127.0.0.1:11434/api/tags")) {
    Aviso "Ollama no estaba corriendo: lo arranco"
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    if (-not (Esperar "http://127.0.0.1:11434/api/tags" 30)) { Cortar "Ollama no respondió en 30 s." }
}
$modelos = (Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 10).models | ForEach-Object { $_.name }
if (-not ($modelos | Where-Object { $_ -eq $Modelo -or $_ -like "${Modelo}:*" })) {
    Cortar "Ollama no tiene el modelo $Modelo. Crealo con: ollama create $Modelo -f ollama/Modelfile"
}

# Mismo num_ctx que la app: si cambia, Ollama recarga el modelo en el primer mensaje.
# keep_alive de 24 h: el script puede correr horas antes de la demo, y la app
# usa OLLAMA_KEEP_ALIVE de .env (poner 24h ahí también, si no a los 30 min se descarga).
# De .env se lee solo esta línea.
$numCtx = 8192
$linea = Select-String -Path ".env" -Pattern "^\s*OLLAMA_NUM_CTX\s*=\s*(\d+)" | Select-Object -First 1
if ($linea) { $numCtx = [int]$linea.Matches[0].Groups[1].Value }

Write-Host "    ..  precalentando $Modelo (num_ctx $numCtx), la primera vez tarda"
$cuerpo = @{
    model = $Modelo; prompt = "hola"; stream = $false; keep_alive = "24h"
    options = @{ num_ctx = $numCtx; num_predict = 1 }
} | ConvertTo-Json -Depth 3
try {
    $inicio = Get-Date
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/generate" -Method Post -Body $cuerpo `
        -ContentType "application/json" -TimeoutSec 180 | Out-Null
    Bien ("Modelo cargado en memoria ({0:N0} s)" -f ((Get-Date) - $inicio).TotalSeconds)
} catch {
    Cortar "No se pudo precalentar el modelo: $($_.Exception.Message)"
}

# ---------------------------------------------------------------- Pestañas
Paso "Abriendo los servicios"
$hayWt = [bool](Get-Command wt -ErrorAction SilentlyContinue)

function Abrir($titulo, $carpeta, $comando) {
    if ($hayWt) {
        $argumentos = "-w $Ventana new-tab --title `"$titulo`" -d `"$carpeta`" powershell -NoExit -Command $comando"
        Start-Process wt -ArgumentList $argumentos
    } else {
        $script = "`$host.UI.RawUI.WindowTitle = '$titulo'; Set-Location '$carpeta'; $comando"
        Start-Process powershell -ArgumentList "-NoExit", "-Command", $script
    }
    Start-Sleep -Seconds 1
    Bien $titulo
}

Abrir "API" $Raiz ".venv\Scripts\python.exe run.py"
Abrir "Correo" $Raiz ".venv\Scripts\python.exe -m scripts.revisar_correo"
Abrir "Voz" (Join-Path $Raiz "voz_asr_tts") ".venv\Scripts\python.exe -m uvicorn servidor:app --port 8001"
Abrir "Panel" (Join-Path $Raiz "frontend") "npm run preview -- --host 127.0.0.1 --port 5173 --strictPort"
if (-not $SinTunel) {
    if ($DominioNgrok) { Abrir "ngrok" $Raiz "ngrok http 127.0.0.1:5173 --url https://$DominioNgrok" }
    else { Abrir "ngrok" $Raiz "ngrok http 127.0.0.1:5173" }
}
Abrir "Despierta" $Raiz "powershell -NoProfile -ExecutionPolicy Bypass -File scripts\mantener_despierta.ps1"

# ---------------------------------------------------------------- Esperar a que respondan
Paso "Esperando a que respondan (en frío puede tardar unos minutos)"
$resumen = [ordered]@{}
$resumen["Base de datos"] = $true
$resumen["Ollama ($Modelo)"] = $true
$resumen["API      :8000"] = Esperar "http://127.0.0.1:8000/health" 240
$resumen["Panel    :5173"] = Esperar "http://127.0.0.1:5173" 60
$resumen["Voz      :8001"] = Esperar "http://127.0.0.1:8001/health" 240

$publica = $null
if (-not $SinTunel) {
    $limite = (Get-Date).AddSeconds(30)
    do {
        try {
            $tuneles = (Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 3).tunnels
            $publica = ($tuneles | Where-Object { $_.public_url -like "https://*" } | Select-Object -First 1).public_url
        } catch { }
        if (-not $publica) { Start-Sleep -Seconds 2 }
    } until ($publica -or (Get-Date) -gt $limite)

    # Se prueba el camino completo de afuera hacia adentro: ngrok -> panel -> API.
    # Cualquier respuesta de FastAPI (aunque sea 401 o 404) prueba que se llegó;
    # un 502 o 504 es que el túnel o el panel no pasan.
    $tunelOk = $false
    if ($publica) {
        try {
            Invoke-WebRequest -Uri "$publica/api/no-existe" -UseBasicParsing -TimeoutSec 15 `
                -Headers @{ "ngrok-skip-browser-warning" = "1" } | Out-Null
            $tunelOk = $true
        } catch {
            $codigo = 0
            if ($_.Exception.Response) { $codigo = [int]$_.Exception.Response.StatusCode }
            $tunelOk = ($codigo -in 401, 403, 404, 405, 422)
        }
    }
    $resumen["Túnel ngrok -> panel -> API"] = $tunelOk
}

# ---------------------------------------------------------------- Resumen
Paso "Resumen"
$todoBien = $true
foreach ($servicio in $resumen.Keys) {
    if ($resumen[$servicio]) {
        Write-Host ("    OK     {0}" -f $servicio) -ForegroundColor Green
    } else {
        Write-Host ("    FALLA  {0}  (mirá su pestaña)" -f $servicio) -ForegroundColor Red
        $todoBien = $false
    }
}
Write-Host "    --     Correo: revisá su pestaña (no tiene puerto, revisa la casilla cada 15 s)" -ForegroundColor DarkGray

if ($publica) {
    Write-Host ""
    Write-Host "    Panel desde la laptop:   $publica" -ForegroundColor Cyan
    Write-Host "    Webhook de WhatsApp:     $publica/api/webhooks/whatsapp" -ForegroundColor Cyan
    try { Set-Clipboard -Value $publica; Write-Host "    (la URL del panel quedó en el portapapeles)" -ForegroundColor DarkGray } catch { }
    if (-not $DominioNgrok) {
        Aviso "Sin dominio fijo la URL cambia en cada arranque: pegá el webhook en Meta (WhatsApp > Configuración > Webhook > Callback URL)."
    }
}

if ($resumen["Panel    :5173"]) { Start-Process "http://localhost:5173" }

Write-Host ""
if ($todoBien) {
    Write-Host "Todo listo para la demo." -ForegroundColor Green
} else {
    Write-Host "Algo no levantó: revisá la pestaña que falló antes de empezar." -ForegroundColor Yellow
}
Write-Host "Para cerrar todo: demo.cmd -Detener" -ForegroundColor DarkGray
Write-Host ""
Pausa "Enter para cerrar esta ventana (los servicios siguen corriendo)"

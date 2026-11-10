$ErrorActionPreference = 'Stop'
$projectPath = Split-Path $PSScriptRoot -Parent
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
$frontendPath = Join-Path $projectPath 'frontend'
$logPath = Join-Path $projectPath '.local\logs'
$postgresEnv = Join-Path $projectPath '.local\postgres.env'

Push-Location $projectPath
try {
    if (!(Test-Path -LiteralPath $pythonPath)) { throw 'The project Python environment is missing.' }
    docker info --format '{{.ServerVersion}}'
    if ($LASTEXITCODE -ne 0) { throw 'Open Docker Desktop, wait until it is running, then run this script again.' }
    New-Item -ItemType Directory -Path $logPath -Force | Out-Null
    if (!(Test-Path -LiteralPath $postgresEnv)) {
        $postgresPassword = [guid]::NewGuid().ToString('N')
        Set-Content -LiteralPath $postgresEnv -Value "POSTGRES_PASSWORD=$postgresPassword" -Encoding ASCII
    }
    $passwordLine = Get-Content -LiteralPath $postgresEnv | Where-Object { $_ -match '^POSTGRES_PASSWORD=' } | Select-Object -First 1
    if (!$passwordLine) { throw 'POSTGRES_PASSWORD is missing from .local/postgres.env.' }
    $postgresPassword = $passwordLine.Substring('POSTGRES_PASSWORD='.Length)
    if ($postgresPassword -notmatch '^[a-fA-F0-9]{32}$') { throw 'Expected the generated 32-character local database password.' }
    $env:DATABASE_URL = "postgresql://costbridge:$postgresPassword@127.0.0.1:5432/costbridge"
    Set-Content -LiteralPath (Join-Path $projectPath 'backend\.env.local') -Value "DATABASE_URL=$env:DATABASE_URL" -Encoding ASCII

    & $pythonPath -m pip install 'SQLAlchemy[asyncio]==2.0.35' 'asyncpg==0.30.0' 'PyJWT[crypto]>=2.10.1' 'httpx>=0.27.0' --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
    & $pythonPath -c 'import backend.server'
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependencies are missing. Install backend/requirements.txt in .venv first.' }

    docker compose --env-file $postgresEnv up --detach --wait postgres
    if ($LASTEXITCODE -ne 0) { throw 'Could not start PostgreSQL.' }

    Push-Location $frontendPath
    try {
        npx.cmd --yes yarn@1.22.22 install --frozen-lockfile --non-interactive
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    } finally { Pop-Location }

    $env:CORS_ORIGINS = 'http://localhost:3000,http://127.0.0.1:3000'
    $env:REACT_APP_BACKEND_URL = 'http://127.0.0.1:8001'
    $env:WDS_SOCKET_PORT = '0'
    $env:HOST = '127.0.0.1'
    $env:PORT = '3000'
    $env:BROWSER = 'none'
    $env:DISABLE_EMERGENT_OVERLAY = 'true'

    foreach ($port in 8001, 3000) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            throw "Port $port is already in use. Stop the previous server before starting again."
        }
    }

    $backend = Start-Process -FilePath $pythonPath -ArgumentList '-m', 'uvicorn', 'backend.server:app', '--host', '127.0.0.1', '--port', '8001' -WorkingDirectory $projectPath -WindowStyle Hidden -RedirectStandardOutput "$logPath\backend.out.log" -RedirectStandardError "$logPath\backend.err.log" -PassThru
    $frontend = $null
    try {
        $frontend = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npm.cmd start' -WorkingDirectory $frontendPath -WindowStyle Hidden -RedirectStandardOutput "$logPath\frontend.out.log" -RedirectStandardError "$logPath\frontend.err.log" -PassThru
        foreach ($url in 'http://127.0.0.1:8001/api/clerk/config', 'http://127.0.0.1:3000') {
            $ready = $false
            for ($attempt = 0; $attempt -lt 120; $attempt++) {
                if ($backend.HasExited -or $frontend.HasExited) { throw "A server exited. Check logs in $logPath." }
                try {
                    $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
                    $ready = $response.StatusCode -eq 200
                } catch { $ready = $false }
                if ($ready) { break }
                Start-Sleep -Seconds 1
            }
            if (!$ready) { throw "Server did not become ready: $url. Check logs in $logPath." }
        }
    } catch {
        taskkill.exe /PID $backend.Id /T /F | Out-Null
        if ($frontend) { taskkill.exe /PID $frontend.Id /T /F | Out-Null }
        throw
    }
    Write-Host 'CostBridge is running at http://localhost:3000'
    Write-Host "Backend PID: $($backend.Id); frontend PID: $($frontend.Id). Logs: $logPath"
} finally { Pop-Location }

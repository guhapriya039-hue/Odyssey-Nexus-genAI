# ODYSSEY TRANSFORM CORE - free public demo, no account and no card.
#
# Runs the platform on this machine and exposes it over a public HTTPS URL via a
# Cloudflare quick tunnel. Costs nothing and needs no signup. The trade-off is
# that the URL only exists while this script is running, and it changes every
# time you start it.
#
#   powershell -ExecutionPolicy Bypass -File scripts\free-demo.ps1
#
# For a permanent URL on someone else's always-on infrastructure, see the
# Deploy section of the README instead.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$port = if ($env:ODYSSEY_PORT) { $env:ODYSSEY_PORT } else { "8000" }
$exe = Join-Path $PSScriptRoot "cloudflared.exe"

# The API serves the built dashboard, so the bundle has to exist first.
$dist = Join-Path $root "frontend\dist\index.html"
if (-not (Test-Path $dist)) {
    Write-Host "Building the dashboard..."
    Push-Location (Join-Path $root "frontend")
    try {
        if (-not (Test-Path "node_modules")) { npm install | Out-Null }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
    } finally { Pop-Location }
}

if (-not (Test-Path $exe)) {
    Write-Host "Downloading cloudflared..."
    Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" `
        -OutFile $exe -TimeoutSec 300
}

# Is something already serving the API? Reuse it rather than fighting for the port.
$up = $false
try {
    $probe = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 5
    $up = $probe.status -eq "ok"
} catch { }

if (-not $up) {
    Write-Host "Starting the API on port $port..."
    Start-Process -FilePath "python" `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", $port `
        -WorkingDirectory (Join-Path $root "backend") `
        -WindowStyle Hidden | Out-Null
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        try {
            if ((Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 3).status -eq "ok") { $up = $true; break }
        } catch { }
    }
    if (-not $up) { throw "the API did not come up on port $port" }
}

Write-Host "Opening the tunnel..."
$errLog = Join-Path $env:TEMP "odyssey-tunnel.err"
Remove-Item $errLog -ErrorAction SilentlyContinue

Start-Process -FilePath $exe `
    -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$port" `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden | Out-Null

for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Path $errLog) {
        $hit = Select-String -Path $errLog -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -AllMatches
        if ($hit) {
            $url = $hit.Matches[0].Value
            Write-Host ""
            Write-Host "  Demo live at:  $url" -ForegroundColor Green
            Write-Host "  API docs:      $url/docs"
            Write-Host "  Local:         http://127.0.0.1:$port"
            Write-Host ""
            Write-Host "  Anyone with this link can read and write to this instance."
            Write-Host "  Stop the demo with Ctrl+C, or close the cloudflared and uvicorn processes."
            exit 0
        }
    }
}

Write-Error "the tunnel did not report a URL; see $errLog"
exit 1

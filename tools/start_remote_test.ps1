$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$cloudflared = Join-Path $PSScriptRoot 'cloudflared\cloudflared.exe'
$localUrl = 'http://127.0.0.1:8000/api/status'

try {
    Invoke-RestMethod -Uri $localUrl -TimeoutSec 4 | Out-Null
} catch {
    Write-Host 'The A01 website is not running.' -ForegroundColor Yellow
    Write-Host 'First double-click: one-click startup BAT, then run this launcher again.'
    exit 1
}

Write-Host ''
Write-Host 'Starting temporary HTTPS tunnel for remote teammates...' -ForegroundColor Cyan
Write-Host 'Keep BOTH the website window and this tunnel window open.' -ForegroundColor Yellow
Write-Host 'Share only the https://*.trycloudflare.com address shown below.'
Write-Host 'Press Ctrl+C to stop remote access.'
Write-Host ''

& $cloudflared tunnel --no-autoupdate --protocol http2 --url http://127.0.0.1:8000

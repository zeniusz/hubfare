# Starts the TravelEdge API (dashboard) and the background worker as two hidden processes.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\start-windows.ps1 [-Python C:\path\to\python.exe]
# To run at every logon, create a Task Scheduler task "At log on" that runs this script.
param([string]$Python = "python")
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$data = Join-Path $root "data"
New-Item -ItemType Directory -Force $data | Out-Null
Start-Process -WindowStyle Hidden -WorkingDirectory $backend -FilePath $Python `
  -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000" `
  -RedirectStandardOutput (Join-Path $data "api.log") -RedirectStandardError (Join-Path $data "api.err.log")
Start-Process -WindowStyle Hidden -WorkingDirectory $backend -FilePath $Python `
  -ArgumentList "-m","app.worker" `
  -RedirectStandardOutput (Join-Path $data "worker.log") -RedirectStandardError (Join-Path $data "worker.err.log")
Write-Host "TravelEdge running: http://localhost:8000  (logs in $data)"

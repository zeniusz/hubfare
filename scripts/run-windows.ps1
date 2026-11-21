# HubFare always-on runner for Windows: starts the dashboard API and the background scanner,
# then checks every 30 s and restarts whichever one has stopped (after sleep, a crash, a network error).
#
#   powershell -ExecutionPolicy Bypass -File scripts\run-windows.ps1
#
# install-windows.ps1 registers this script to start hidden at every Windows log-on.
param(
  [string]$Python = "",
  [int]$Port = 8000
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$data = Join-Path $root "data"
New-Item -ItemType Directory -Force $data | Out-Null
if (-not $Python) { $Python = Join-Path $root ".venv\Scripts\python.exe" }
if (-not (Test-Path $Python)) { throw "Python not found at $Python - run scripts\install-windows.ps1 first" }

$env:PYTHONIOENCODING = "utf-8"
$log = Join-Path $data "runner.log"
function Say($msg) { Add-Content -Path $log -Value ("{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $msg) -Encoding utf8 }

# only one runner at a time
$lock = Join-Path $data "runner.pid"
if (Test-Path $lock) {
  $old = Get-Content $lock -ErrorAction SilentlyContinue
  if ($old -and (Get-Process -Id $old -ErrorAction SilentlyContinue)) { Say "runner already active (pid $old) - exiting"; exit 0 }
}
Set-Content -Path $lock -Value $PID

$jobs = @{
  api    = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port")
  worker = @("-m", "app.worker")
}
$procs = @{}

function Start-Part($name) {
  $p = Start-Process -PassThru -WindowStyle Hidden -WorkingDirectory $backend -FilePath $Python -ArgumentList $jobs[$name] `
    -RedirectStandardOutput (Join-Path $data "$name.log") -RedirectStandardError (Join-Path $data "$name.err.log")
  $procs[$name] = $p
  Say "started $name (pid $($p.Id))"
}

Say "runner started (pid $PID) - dashboard http://localhost:$Port"
try {
  while ($true) {
    foreach ($name in $jobs.Keys) {
      $p = $procs[$name]
      if (-not $p -or $p.HasExited) {
        if ($p) { Say "$name stopped (exit $($p.ExitCode)) - restarting" }
        Start-Part $name
      }
    }
    Start-Sleep -Seconds 30
  }
} finally {
  foreach ($p in $procs.Values) { if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } }
  Remove-Item $lock -ErrorAction SilentlyContinue
  Say "runner stopped"
}

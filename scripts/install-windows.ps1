# One-time setup: creates .venv, installs dependencies and registers HubFare to start (hidden) at every log-on.
# No administrator rights needed - the task runs as your own user.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1            # install + start now
#   powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1 -Uninstall # remove the start-up task
#   ... install-windows.ps1 -Python C:\path\to\venv\Scripts\python.exe   # reuse an existing environment
#   (useful when Windows Smart App Control blocks DLLs in a freshly downloaded environment)
param([switch]$Uninstall, [string]$BasePython = "python", [string]$Python = "")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$task = "HubFare"

if ($Uninstall) {
  Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "Start-up task removed. Files in $root were left untouched."
  exit 0
}

$venvPy = if ($Python) { $Python } else { Join-Path $root ".venv\Scripts\python.exe" }
if (-not (Test-Path $venvPy)) {
  Write-Host "Creating virtual environment..."
  & $BasePython -m venv (Join-Path $root ".venv")
}
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -r (Join-Path $root "backend\requirements.txt")
if (-not (Test-Path (Join-Path $root ".env"))) {
  Copy-Item (Join-Path $root ".env.example") (Join-Path $root ".env")
  Write-Host "Created .env from .env.example - add your API tokens there."
}

$runner = Join-Path $root "scripts\run-windows.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument ("-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`"" + $(if ($Python) { " -Python `"$Python`"" } else { "" })) `
  -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings `
  -Description "HubFare travel deal monitor (dashboard on http://localhost:8000 + background scanner)" -Force | Out-Null
Start-ScheduledTask -TaskName $task
Write-Host "HubFare installed. It starts at every log-on; dashboard: http://localhost:8000 (logs in $root\data)"

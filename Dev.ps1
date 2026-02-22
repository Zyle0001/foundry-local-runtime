Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$backendVenv = Join-Path $repoRoot "ONNX host service\env"
$backendPython = Join-Path $backendVenv "Scripts\python.exe"

if (-not (Test-Path $backendPython)) {
    Write-Host "Creating backend virtual environment at '$backendVenv'..."
    py -3 -m venv $backendVenv
}

Write-Host "Installing backend Python dependencies from requirements.txt..."
& $backendPython -m pip install -r (Join-Path $repoRoot "requirements.txt")

Start-Process powershell -WorkingDirectory (Join-Path $repoRoot "runtime-ui") -ArgumentList `
    "-NoExit", `
    "-Command", "npm run dev"

$backendCommand = "& '$backendPython' -m uvicorn onnx_host.main:app --reload"
Start-Process powershell -WorkingDirectory $repoRoot -ArgumentList `
    "-NoExit", `
    "-Command", $backendCommand

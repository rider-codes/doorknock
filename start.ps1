# Starts the Doorknock backend (port 8000) and the frontend (port 5173).
# Run from the doorknock folder:  powershell -ExecutionPolicy Bypass -File .\start.ps1
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Test-Path "$root\backend\.venv")) {
  Write-Host "Setting up the backend (first run only)..."
  python -m venv "$root\backend\.venv"
  & "$root\backend\.venv\Scripts\python.exe" -m pip install -q -r "$root\backend\requirements.txt"
}
if (-not (Test-Path "$root\frontend\node_modules")) {
  Write-Host "Installing the frontend (first run only)..."
  Push-Location "$root\frontend"; npm install --no-audit --no-fund; Pop-Location
}
if (-not (Test-Path "$root\backend\.env") -and -not (Test-Path "$root\.env")) {
  Copy-Item "$root\.env.example" "$root\backend\.env"
  Write-Host "Created backend\.env. Add your ANTHROPIC_API_KEY there, then run this again."
}

# Node tools are called directly because npx breaks on folder names containing '&'.
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; & .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; node node_modules/vite/bin/vite.js --port 5173"
Write-Host "Open http://localhost:5173  (on your phone: http://<this-pc-ip>:5173 on the same Wi-Fi)"

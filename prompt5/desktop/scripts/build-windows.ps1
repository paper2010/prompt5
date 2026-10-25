$ErrorActionPreference = "Stop"

$root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $root

Write-Host "== 1/4 Build web dist =="
Push-Location "$root\web"
if (-not (Test-Path "node_modules")) {
    npm.cmd ci
}
npm.cmd run build
Pop-Location

Write-Host "== 2/4 Install PyInstaller =="
& "$root\.venv\Scripts\python.exe" -m pip install pyinstaller

Write-Host "== 3/4 Build backend executable =="
& "$root\.venv\Scripts\pyinstaller.exe" `
    --noconfirm `
    --clean `
    --onefile `
    --name prompt5-backend `
    --add-data "web/dist;web/dist" `
    --add-data "config.example.yaml;." `
    --add-data "src/prompt5/store/schema.sql;prompt5/store" `
    --add-data "src/prompt5/store/schema_v2.sql;prompt5/store" `
    --collect-submodules prompt5 `
    --paths src `
    desktop/launcher.py

Write-Host "== 4/4 Build Windows installer =="
Push-Location "$root\desktop"
if (-not (Test-Path "node_modules")) {
    npm.cmd ci
}
npm.cmd run dist:win
Pop-Location

Write-Host "Done. Installer: desktop\release-windows\"

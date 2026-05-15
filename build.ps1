# build.ps1 — Génère dist\PCB-Mosaic-Maker.exe sur Windows.
#
# Utilisation :
#   .\build.ps1            # build standard
#   .\build.ps1 -Clean     # supprime build/ et dist/ avant
#
# Pré-requis : Python 3.10+ et `pip install -r requirements.txt`
#              `pip install pyinstaller`

param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

if ($Clean) {
    if (Test-Path build) { Remove-Item build -Recurse -Force }
    if (Test-Path dist)  { Remove-Item dist  -Recurse -Force }
    Get-ChildItem -Path . -Filter __pycache__ -Recurse -Directory |
        Remove-Item -Recurse -Force
}

Write-Host "==> Vérification de PyInstaller…" -ForegroundColor Cyan
python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller non installé. Installation…" -ForegroundColor Yellow
    pip install pyinstaller
}

Write-Host "==> Lancement du build…" -ForegroundColor Cyan
pyinstaller pcbmosaic.spec --clean --noconfirm

if (Test-Path "dist\PCB-Mosaic-Maker.exe") {
    $size = (Get-Item "dist\PCB-Mosaic-Maker.exe").Length / 1MB
    Write-Host ("==> OK : dist\PCB-Mosaic-Maker.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
} else {
    Write-Host "==> Build échoué." -ForegroundColor Red
    exit 1
}

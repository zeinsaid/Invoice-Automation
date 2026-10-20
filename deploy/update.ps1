<#
Update the code on the shop PC from GitHub, or undo the last update (D-023).

-Root is the "Admin only" folder (D-024). Only its app\ is replaced: data\, output\, processed\,
logs\, .env and the staff folders are never touched, so nothing the tool has learned can be lost by
an update. The previous code is kept as
app.old: if the new code doesn't install or start, it is put back automatically, and "Undo" puts
it back by hand.

Run from Admin.bat (option 2 or 3), or for the first install from setup.ps1.
#>
param(
    [Parameter(Mandatory = $true)][string]$Root,
    [switch]$Undo
)
$ErrorActionPreference = "Stop"
$Repo = "zeinsaid/Invoice-Automation"
$App = Join-Path $Root "app"
$Old = Join-Path $Root "app.old"
$Tools = Join-Path $Root "tools"
$Uv = Join-Path $Tools "uv\uv.exe"
$env:UV_CACHE_DIR = Join-Path $Tools "cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools "python"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $Tools "venv"
$env:UV_PYTHON_PREFERENCE = "only-managed"
Set-Location $Root

function Swap-Back {
    if (Test-Path $Old) {
        if (Test-Path $App) { Remove-Item $App -Recurse -Force }
        Rename-Item $Old "app"
        & $Uv sync --frozen --no-dev --project $App | Out-Host
    }
}

function Copy-StaffFiles {
    # The launcher and the staff guide sit in the staff folder (D-024); the admin guide is tucked into data\.
    $staff = Split-Path $Root -Parent
    Copy-Item (Join-Path $App "deploy\Process Invoices.bat") $staff -Force
    $guides = Join-Path $App "deploy\guides"
    if (Test-Path $guides) {
        Copy-Item (Join-Path $guides "Staff guide.html") $staff -Force
        New-Item -ItemType Directory -Force (Join-Path $Root "data") | Out-Null
        Copy-Item (Join-Path $guides "Admin guide.html") (Join-Path $Root "data") -Force
    }
}

function Test-App {
    # Starts the tool far enough to load the code and read data\ (the export, the pack links).
    & $Uv sync --frozen --no-dev --project $App | Out-Host
    if ($LASTEXITCODE -ne 0) { return $false }
    if (-not (Test-Path (Join-Path $Root "data\powersoft\items_export_*.csv"))) { return $true }  # first install
    & $Uv run --frozen --no-dev --project $App invoice-automation --packs | Out-Null
    return $LASTEXITCODE -eq 0
}

if ($Undo) {
    if (-not (Test-Path $Old)) { Write-Host "There is no previous version to go back to."; exit 1 }
    $broken = Join-Path $Root "app.undone"
    if (Test-Path $broken) { Remove-Item $broken -Recurse -Force }
    Rename-Item $App "app.undone"
    Rename-Item $Old "app"
    & $Uv sync --frozen --no-dev --project $App | Out-Host
    Copy-Item (Join-Path $Tools "version.old.txt") (Join-Path $Tools "version.txt") -ErrorAction SilentlyContinue
    Copy-StaffFiles
    Write-Host "Back to the previous version."
    exit 0
}

# The newest commit on main, so the version that is running can always be named.
$sha = (Invoke-RestMethod "https://api.github.com/repos/$Repo/commits/main").sha
$current = Get-Content (Join-Path $Tools "version.txt") -ErrorAction SilentlyContinue | Select-Object -First 1
if ($current -eq $sha) { Write-Host "Already up to date ($($sha.Substring(0, 7)))."; exit 0 }

$download = Join-Path $Tools "download"
if (Test-Path $download) { Remove-Item $download -Recurse -Force }
New-Item -ItemType Directory $download | Out-Null
$zip = Join-Path $download "app.zip"
Write-Host "Downloading $($sha.Substring(0, 7))..."
Invoke-WebRequest "https://github.com/$Repo/archive/$sha.zip" -OutFile $zip -UseBasicParsing
Expand-Archive $zip $download
$new = Get-ChildItem $download -Directory | Select-Object -First 1

if (Test-Path $Old) { Remove-Item $Old -Recurse -Force }
if (Test-Path $App) {
    Rename-Item $App "app.old"
    Copy-Item (Join-Path $Tools "version.txt") (Join-Path $Tools "version.old.txt") -ErrorAction SilentlyContinue
}
Move-Item $new.FullName $App
Remove-Item $download -Recurse -Force

if (-not (Test-App)) {
    Write-Host "The new version did not start. Going back to the previous one." -ForegroundColor Red
    Swap-Back
    exit 1
}
Set-Content (Join-Path $Tools "version.txt") $sha
Copy-StaffFiles
Write-Host "Updated to $($sha.Substring(0, 7)). Nothing in data\ was changed." -ForegroundColor Green

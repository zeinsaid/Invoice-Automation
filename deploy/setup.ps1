<#
First install on the shop PC (D-023, D-024). Run once, over AnyDesk:

  1. Unzip the install package onto the ThawSpace drive (any drive but C:). It holds a staff folder,
     e.g. D:\Invoices, and in it "Admin only" with this file, .env and data\.
  2. Run it from PowerShell (double-clicking is blocked by Windows):
       powershell -ExecutionPolicy Bypass -File "D:\Invoices\Admin only\setup.ps1"

It installs uv (and through it Python and the libraries) into tools\, downloads the code into app\,
and sets up the staff folder: the two folders staff use, Process Invoices and the Staff guide.
Everything else stays in "Admin only". It makes no desktop shortcut: Zein makes one to the staff
folder by hand, in Deep Freeze's thawed mode. Running it again is safe: it skips what is there.
#>
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot  # "Admin only"
$Staff = Split-Path $Root -Parent
$UvVersion = "0.12.19"  # the version the tool was built and tested with
if ($Root.StartsWith("C:", "OrdinalIgnoreCase")) {
    Write-Host "This folder is on C:, which Deep Freeze resets at every restart. Use the ThawSpace drive." -ForegroundColor Red
    exit 1
}
# Process Invoices.bat finds the tool by this name, and the staff folder must be a folder of its own.
if ((Split-Path $Root -Leaf) -ne "Admin only" -or $Staff -eq [IO.Path]::GetPathRoot($Root)) {
    Write-Host "This file must be in a folder called 'Admin only', inside the staff folder (e.g. D:\Invoices\Admin only)." -ForegroundColor Red
    exit 1
}
Set-Location $Root
foreach ($dir in "tools", "data", "output", "processed", "logs") {
    New-Item -ItemType Directory -Force (Join-Path $Root $dir) | Out-Null
}
# The folders staff see. The same names are in env.bat: change them in both places.
foreach ($dir in "1. Put invoice scans here", "2. Excel files ready to upload") {
    New-Item -ItemType Directory -Force (Join-Path $Staff $dir) | Out-Null
}

$uvDir = Join-Path $Root "tools\uv"
if (-not (Test-Path (Join-Path $uvDir "uv.exe"))) {
    Write-Host "Installing uv $UvVersion into tools\uv..."
    $env:UV_INSTALL_DIR = $uvDir
    $env:UV_NO_MODIFY_PATH = "1"  # don't touch the system PATH (it lives on C:)
    Invoke-RestMethod "https://astral.sh/uv/$UvVersion/install.ps1" | Invoke-Expression
}

# The code (and through uv sync, Python 3.12 and the libraries, all into tools\). The update also puts
# Process Invoices and the Staff guide in the staff folder.
$update = Join-Path $Root "tools\update.ps1"
Invoke-WebRequest "https://raw.githubusercontent.com/zeinsaid/Invoice-Automation/main/deploy/update.ps1" -OutFile $update -UseBasicParsing
& powershell -NoProfile -ExecutionPolicy Bypass -File $update -Root $Root
if ($LASTEXITCODE -ne 0) { exit 1 }
Remove-Item $update
Copy-Item (Join-Path $Root "app\deploy\Admin.bat") (Join-Path $Root "Admin.bat") -Force

$missing = @()
if (-not (Test-Path (Join-Path $Root ".env"))) { $missing += ".env  (the Azure endpoint and key)" }
if (-not (Test-Path (Join-Path $Root "data\powersoft\items_export_*.csv")) -and
    -not (Test-Path (Join-Path $Root "data\powersoft\itemsList.csv"))) { $missing += "data\powersoft\itemsList.csv" }
foreach ($need in "data\powersoft\categories.xlsx", "data\powersoft\suppliers.xlsx",
                  "data\reference\legacy_supplier_lists.xlsx", "data\flag_items.csv") {
    if (-not (Test-Path (Join-Path $Root $need))) { $missing += $need }
}
if ($missing) {
    Write-Host "`nInstalled. Now copy these into 'Admin only' from Zein's PC:" -ForegroundColor Yellow
    $missing | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host "`nInstalled and ready." -ForegroundColor Green
}

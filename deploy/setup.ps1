<#
First install on the shop PC (D-023). Run once, over AnyDesk:

  1. Make the tool folder on the ThawSpace drive (any drive but C:), e.g. D:\Invoice Tool
  2. Put this file in it, right-click > Run with PowerShell
     (or: powershell -ExecutionPolicy Bypass -File "D:\Invoice Tool\setup.ps1")
  3. Copy in data\ and .env from Zein's PC, as the script lists at the end

It installs uv (and through it Python and the libraries) into tools\, downloads the code into app\,
and puts the two launchers in the tool folder. Running it again is safe: it skips what is there.
#>
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$UvVersion = "0.12.19"  # the version the tool was built and tested with
if ($Root.StartsWith("C:", "OrdinalIgnoreCase")) {
    Write-Host "This folder is on C:, which Deep Freeze resets at every restart. Use the ThawSpace drive." -ForegroundColor Red
    exit 1
}
Set-Location $Root
foreach ($dir in "tools", "data", "input", "output", "processed", "logs") {
    New-Item -ItemType Directory -Force (Join-Path $Root $dir) | Out-Null
}

$uvDir = Join-Path $Root "tools\uv"
if (-not (Test-Path (Join-Path $uvDir "uv.exe"))) {
    Write-Host "Installing uv $UvVersion into tools\uv..."
    $env:UV_INSTALL_DIR = $uvDir
    $env:UV_NO_MODIFY_PATH = "1"  # don't touch the system PATH (it lives on C:)
    Invoke-RestMethod "https://astral.sh/uv/$UvVersion/install.ps1" | Invoke-Expression
}

# The code (and through uv sync, Python 3.12 and the libraries, all into tools\).
$update = Join-Path $Root "tools\update.ps1"
Invoke-WebRequest "https://raw.githubusercontent.com/zeinsaid/Invoice-Automation/main/deploy/update.ps1" -OutFile $update -UseBasicParsing
& powershell -NoProfile -ExecutionPolicy Bypass -File $update -Root $Root
if ($LASTEXITCODE -ne 0) { exit 1 }
Remove-Item $update

foreach ($launcher in "Process Invoices.bat", "Admin.bat") {
    Copy-Item (Join-Path $Root "app\deploy\$launcher") (Join-Path $Root $launcher) -Force
}

# A desktop shortcut for staff. The desktop is on C:, so it only survives a restart if this runs
# while Deep Freeze is "Boot Thawed"; otherwise make the shortcut again in thawed mode.
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "Process Invoices.lnk"))
$link.TargetPath = Join-Path $Root "Process Invoices.bat"
$link.WorkingDirectory = $Root
$link.WindowStyle = 7  # minimised: the black window only flashes
$link.Save()

$missing = @()
if (-not (Test-Path (Join-Path $Root ".env"))) { $missing += ".env  (the Azure endpoint and key)" }
foreach ($need in "data\powersoft\items_export_*.csv", "data\powersoft\categories.xlsx", "data\powersoft\suppliers.xlsx",
                  "data\reference\legacy_supplier_lists.xlsx", "data\flag_items.csv") {
    if (-not (Test-Path (Join-Path $Root $need))) { $missing += $need }
}
if ($missing) {
    Write-Host "`nInstalled. Now copy these in from Zein's PC:" -ForegroundColor Yellow
    $missing | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host "`nInstalled and ready." -ForegroundColor Green
}

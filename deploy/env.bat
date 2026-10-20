@echo off
rem Shared settings for the launchers (D-023, D-024). The tool folder looks like this:
rem
rem   <staff folder>\                on the ThawSpace drive (anything but C:, which Deep Freeze resets)
rem     1. Put invoice scans here\   2. Excel files ready to upload\   Process Invoices.bat   Staff guide.html
rem     Admin only\                  ROOT: everything staff don't need to see
rem       app\                       the code: replaced by Update, nothing else
rem       data\  output\Uploaded\  processed\  logs\  .env     what the tool keeps: never touched by Update
rem       tools\uv\  tools\python\  tools\venv\  tools\cache\  uv, Python and the libraries
rem       Admin.bat
rem
rem Everything uv and Python need lives in tools\, because anything installed on C: is wiped at restart.
rem The two staff folder names are also in setup.ps1: change them in both places.

for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
for %%I in ("%ROOT%\..") do set "STAFF=%%~fI"
set "INVOICE_INPUT=%STAFF%\1. Put invoice scans here"
set "INVOICE_READY=%STAFF%\2. Excel files ready to upload"
set "APP=%ROOT%\app"
set "UV=%ROOT%\tools\uv"
set "UV_CACHE_DIR=%ROOT%\tools\cache"
set "UV_PYTHON_INSTALL_DIR=%ROOT%\tools\python"
set "UV_PROJECT_ENVIRONMENT=%ROOT%\tools\venv"
set "UV_PYTHON_PREFERENCE=only-managed"
set "UV_NO_PROGRESS=1"
cd /d "%ROOT%"

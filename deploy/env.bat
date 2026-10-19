@echo off
rem Shared settings for the launchers (D-023). The tool folder looks like this:
rem
rem   <tool folder>\                 on the ThawSpace drive (anything but C:, which Deep Freeze resets)
rem     app\                         the code: replaced by Update, nothing else
rem     data\  input\  output\  processed\  logs\  .env     what the tool keeps: never touched by Update
rem     tools\uv\  tools\python\  tools\venv\  tools\cache\  uv, Python and the libraries
rem
rem Everything uv and Python need lives in tools\, because anything installed on C: is wiped at restart.

for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
set "APP=%ROOT%\app"
set "UV=%ROOT%\tools\uv"
set "UV_CACHE_DIR=%ROOT%\tools\cache"
set "UV_PYTHON_INSTALL_DIR=%ROOT%\tools\python"
set "UV_PROJECT_ENVIRONMENT=%ROOT%\tools\venv"
set "UV_PYTHON_PREFERENCE=only-managed"
set "UV_NO_PROGRESS=1"
cd /d "%ROOT%"

@echo off
rem Zein only (over AnyDesk): the review window in Zein's mode, plus the update and check commands.
call "%~dp0app\deploy\env.bat"
echo.
echo   1  Review window, Zein's mode (invoices staff sent to Zein)
echo   2  Update the code from GitHub (keeps everything in data\)
echo   3  Undo the last update
echo   4  Pack check (which single item each pack counts as)
echo.
set /p CHOICE="Choose 1-4: "
if "%CHOICE%"=="1" start "" "%UV%\uvw.exe" run --frozen --no-dev --project "%APP%" invoice-automation --zein
if "%CHOICE%"=="2" powershell -NoProfile -ExecutionPolicy Bypass -File "%APP%\deploy\update.ps1" -Root "%ROOT%"
if "%CHOICE%"=="3" powershell -NoProfile -ExecutionPolicy Bypass -File "%APP%\deploy\update.ps1" -Root "%ROOT%" -Undo
if "%CHOICE%"=="4" "%UV%\uv.exe" run --frozen --no-dev --project "%APP%" invoice-automation --packs
pause

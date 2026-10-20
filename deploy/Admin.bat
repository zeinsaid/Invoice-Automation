@echo off
rem Admin only (Zein, over AnyDesk): the review window in admin mode, plus the update and check commands.
call "%~dp0app\deploy\env.bat"
echo.
echo   1  Review window, admin mode (also the invoices staff sent to Zein)
echo   2  Update the code from GitHub (keeps everything in data\)
echo   3  Undo the last update
echo   4  Pack check (which single item each pack counts as)
echo   5  Open what the tool has learned, to delete a wrong answer (close it before processing)
echo.
set /p CHOICE="Choose 1-5: "
if "%CHOICE%"=="1" start "" "%UV%\uvw.exe" run --frozen --no-dev --project "%APP%" invoice-automation --zein
if "%CHOICE%"=="2" powershell -NoProfile -ExecutionPolicy Bypass -File "%APP%\deploy\update.ps1" -Root "%ROOT%"
if "%CHOICE%"=="3" powershell -NoProfile -ExecutionPolicy Bypass -File "%APP%\deploy\update.ps1" -Root "%ROOT%" -Undo
if "%CHOICE%"=="4" "%UV%\uv.exe" run --frozen --no-dev --project "%APP%" invoice-automation --packs
rem D-026: delete the row of a wrong answer and save; that line is asked again next time.
if "%CHOICE%"=="5" start "" "%ROOT%\data\supplier_items.xlsx"
pause

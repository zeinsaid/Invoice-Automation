@echo off
rem Staff: double-click to process the scans in "1. Put invoice scans here" (D-002).
rem It sits in the staff folder; the tool itself is in "Admin only" beside it (D-024).
call "%~dp0Admin only\app\deploy\env.bat"
rem uvw is uv without a black console window; the tool shows its own window and errors.
start "" "%UV%\uvw.exe" run --frozen --no-dev --project "%APP%" invoice-automation %*

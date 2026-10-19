@echo off
rem Staff: double-click to process the scans in the "input" folder (D-002).
call "%~dp0app\deploy\env.bat"
rem uvw is uv without a black console window; the tool shows its own window and errors.
start "" "%UV%\uvw.exe" run --frozen --no-dev --project "%APP%" invoice-automation %*

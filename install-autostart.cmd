@echo off
rem Register the xinyuehu (Hsin Moon Fox) pet watchdog to start at logon.
rem It only launches the pet while the DSH desktop app is running, and stops
rem the pet again when DSH exits. ASCII-only on purpose: cmd.exe parses .cmd
rem files with the OEM codepage, so non-ASCII comments can turn into commands.
setlocal
set "HERE=%~dp0"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET=%STARTUP%\xinyuehu-pet.vbs"
set "TEMPLATE=%HERE%autostart\start-pet-at-logon.vbs"

if not exist "%TEMPLATE%" (
  echo [!] autostart\start-pet-at-logon.vbs is missing.
  pause
  exit /b 1
)

rem The launcher lives in the Startup folder, so it cannot find the project by
rem its own location: bake absolute paths in while copying. The Python path is
rem baked in too, because %DSH_HOME% is NOT set in a fresh logon environment.
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" (
  echo [!] DSH bundled Python not found at:
  echo     %PY%
  echo     Set PY in this file to a Python that has Pillow and numpy, then rerun.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$t = Get-Content -LiteralPath '%TEMPLATE%' -Raw -Encoding UTF8; $t = $t.Replace('__PACKAGE_ROOT__', '%ROOT%'); $t = $t.Replace('__PYTHON_EXE__', '%PY%'); Set-Content -LiteralPath '%TARGET%' -Value $t -Encoding ASCII -NoNewline"
if errorlevel 1 (
  echo [!] Failed to write "%TARGET%"
  pause
  exit /b 1
)

echo [ok] Autostart installed:
echo      %TARGET%
echo      project : %ROOT%
echo      python  : %PY%
echo.
echo The pet now appears whenever DSH is running, and closes with DSH.
echo Start it now without logging off:
echo      wscript "%TARGET%"
echo.
echo To undo: run uninstall-autostart.cmd
pause

@echo off
rem Uninstall the logon autostart entry, then stop the watchdog and the pet.
rem ASCII-only on purpose (cmd.exe parses .cmd with the OEM codepage). The
rem actual process killing lives in stop-pet.ps1, which can parse the lock
rem files reliably.
setlocal
set "HERE=%~dp0"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET=%STARTUP%\xinyuehu-pet.vbs"

if exist "%TARGET%" (
  del /q "%TARGET%"
  echo [ok] Autostart entry removed.
) else (
  echo [i] No autostart entry was installed.
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%stop-pet.ps1"

echo.
echo Uninstalled. The pet will no longer start with DSH.
pause

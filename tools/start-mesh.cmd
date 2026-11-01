@echo off
rem Start the Mesh app, detached, at logon - the same pattern tools\start-relay.cmd uses.
rem
rem Mesh is hosted on the tailnet so the URL works from this PC or from a phone:
rem     https://emitchell.tail8c4a75.ts.net:8446
rem published by `tailscale serve --bg --https=8446 http://127.0.0.1:4317`.
rem The serve mapping persists on its own; this script only has to keep the app running.
rem
rem Two constraints come from the app itself, not from this script:
rem   * startApp refuses a dataDir that is not test/app03-* - an owned synthetic store,
rem     so Mesh cannot be pointed at an arbitrary folder.
rem   * startApp refuses a fixed port and requires an OS-assigned one. So the backend port
rem     changes every boot; only the preview port (4317) is stable, which is what we publish.
setlocal EnableExtensions
set "DIR=D:\Mesh"
set "LOG=%DIR%\test\app03-mesh\start-mesh.log"

if not exist "%DIR%\test\m1-serve.mjs" (
  echo [%DATE% %TIME%] FAIL m1-serve.mjs missing under %DIR%>>"%LOG%"
  exit /b 1
)

rem Do not start a second copy.
netstat -ano | findstr /c:"127.0.0.1:4317" | findstr /i "LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo [%DATE% %TIME%] already listening on 4317 - nothing to do>>"%LOG%"
  exit /b 0
)

echo [%DATE% %TIME%] launching Mesh>>"%LOG%"

rem The app reads these two from its environment. They are set HERE, in the shell that
rem spawns it, so the child inherits them. Do NOT pass Start-Process -Environment: that
rem parameter only exists in PowerShell 7, and this script may run under Windows
rem PowerShell 5.1, where it fails with "parameter cannot be found". That bug was latent
rem for exactly as long as the app was already running, because the check above returned
rem first every time.
rem Refresh the Relay agent snapshot. Best effort: never blocks the boot.
node "%DIR%\tools\sync-relay-agents.mjs" 2>nul
set "MESH_DATA_DIR=test/app03-mesh"
set "MESH_PREVIEW_PORT=4317"

rem Start-Process rather than `start /B` with a redirect: the latter keeps a stdout handle
rem open and the caller waits on a server that never exits.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'node' -ArgumentList 'test/m1-serve.mjs' -WorkingDirectory '%DIR%' -WindowStyle Hidden -RedirectStandardOutput '%DIR%\test\app03-mesh\serve.out.log' -RedirectStandardError '%DIR%\test\app03-mesh\serve.err.log'"

rem Confirm it actually arrives rather than trusting the launch call.
set /a TRIES=0
:wait
ping -n 3 127.0.0.1 >nul 2>&1
set /a TRIES+=1
netstat -ano | findstr /c:"127.0.0.1:4317" | findstr /i "LISTENING" >nul 2>&1
if not errorlevel 1 goto up
if %TRIES% lss 20 goto wait
echo [%DATE% %TIME%] FAIL launched, but 4317 was still not listening after %TRIES% checks>>"%LOG%"
exit /b 1

:up
echo [%DATE% %TIME%] OK 4317 is listening (after %TRIES% checks)>>"%LOG%"
rem The serve mapping points at 4317, which does not change. Re-assert it in case the
rem tailnet config was reset - harmless and idempotent.
tailscale serve --bg --https=8446 http://127.0.0.1:4317 >nul 2>&1
endlocal

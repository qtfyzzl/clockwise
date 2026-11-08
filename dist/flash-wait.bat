@echo off
setlocal enabledelayedexpansion
REM 优先用脚本同目录自带的 esptool.exe（换电脑无需装 PlatformIO）
if exist "%~dp0esptool.exe" (
  set ESPTOOL=%~dp0esptool.exe
) else (
  set ESPTOOL=%USERPROFILE%\.platformio\packages\tool-esptool\esptool.exe
)
set IMG=%~dp0clockwise-ota-merged.bin
set PORT=%1
if "%PORT%"=="" set PORT=COM6
set /a N=0

if not exist "%ESPTOOL%" (
  echo esptool not found: %ESPTOOL%
  echo Install PlatformIO first, or edit ESPTOOL in this file.
  exit /b 1
)
if not exist "%IMG%" (
  echo Image not found: %IMG%
  exit /b 1
)

echo.
echo ============================================================
echo   Put the board into DOWNLOAD MODE:
echo.
echo     1. HOLD  BOOT (IO0)
echo     2. PRESS and RELEASE  EN / RST
echo     3. RELEASE  BOOT
echo.
echo   Screen goes black = success (chip is halted).
echo   No buttons? Short IO0 to GND, then plug USB.
echo ============================================================
echo.
echo Waiting on %PORT% (Ctrl+C to abort)

:wait
"%ESPTOOL%" --chip esp32 --port %PORT% --connect-attempts 1 chip-id >nul 2>&1
if not errorlevel 1 goto connected
set /a N+=1
if !N! geq 90 (
  echo.
  echo.
  echo Timed out after about 3 minutes.
  echo Check: data-capable USB cable / CH340 driver / correct COM port.
  exit /b 1
)
timeout /t 2 /nobreak >nul
<nul set /p =.
goto wait

:connected
echo.
echo.
echo Download mode detected. Flashing %IMG%
echo.
"%ESPTOOL%" --chip esp32 --port %PORT% --baud 460800 write-flash -z 0x0 "%IMG%"
if not errorlevel 1 goto done

echo.
echo Flash failed at 460800, retrying at 115200 ...
"%ESPTOOL%" --chip esp32 --port %PORT% --baud 115200 write-flash -z 0x0 "%IMG%"
if not errorlevel 1 goto done

echo.
echo Flash FAILED. Close serial monitors and try again.
exit /b 1

:done
echo.
echo ============================================================
echo   Done. Board reboots automatically.
echo   Watch boot log:  pio device monitor --port %PORT% --baud 115200
echo ============================================================
exit /b 0

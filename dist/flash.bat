@echo off
setlocal
set ESPTOOL=%USERPROFILE%\.platformio\packages\tool-esptool\esptool.exe
set IMG=%~dp0clockwise-v1.4.4-mario-merged.bin

if "%1"=="" (
  echo Usage: flash.bat COM5
  echo.
  echo Available ports:
  echo   See Device Manager ^> Ports, or run: pio device list
  exit /b 1
)

if not exist "%ESPTOOL%" (
  echo esptool not found at %ESPTOOL%
  echo Install PlatformIO first, or edit ESPTOOL path in this file.
  exit /b 1
)

echo Flashing %IMG% to %1 ...
"%ESPTOOL%" --chip esp32 --port %1 --baud 921600 write-flash -z 0x0 "%IMG%"

if errorlevel 1 (
  echo.
  echo Flash FAILED. Try:
  echo   1. Close any serial monitor holding the port
  echo   2. Hold BOOT button while plugging in USB
  echo   3. Lower baud rate to 460800
  exit /b 1
)

echo.
echo Done. Open serial monitor at 115200 to watch boot log.

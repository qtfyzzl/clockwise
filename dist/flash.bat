@echo off
setlocal

REM 薄包装：直接调用同目录的 flash.ps1（已含自动枚举串口、本地 esptool 回退、
REM 分段烧录 firmware.bin 等完整逻辑）。参数透传给 ps1。
REM
REM 用法：
REM   flash.bat             双击，自动找串口烧最新固件
REM   flash.bat -Port COM8  指定串口
REM   flash.bat -Erase      整片擦除（清空设置，需重配 WiFi）
REM   flash.bat -Merged     烧合并镜像（救砖）

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0flash.ps1" %*

if errorlevel 1 (
  echo.
  echo 烧录失败，见上方输出。
  pause
  exit /b 1
)

echo.
echo 完成。
pause
exit /b 0

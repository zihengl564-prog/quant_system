@echo off
chcp 65001 > nul
cd /d D:\quant_system

call D:\quant_system\.venv\Scripts\activate.bat
if errorlevel 1 goto :error

echo 运行环境自检...
python D:\quant_system\scripts\preflight_check.py
if errorlevel 1 goto :error

pause
exit /b 0

:error
echo 自检失败，请查看上方报错
pause
exit /b 1
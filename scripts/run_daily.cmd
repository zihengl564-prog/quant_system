@echo off
cd /d D:\quant_system
call D:\quant_system\.venv\Scripts\activate
python D:\quant_system\scripts\collect_daily.py 20250101 20250314
pause
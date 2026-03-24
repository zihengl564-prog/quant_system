@echo off
chcp 65001 > nul
cd /d D:\quant_system

call D:\quant_system\.venv\Scripts\activate.bat
if errorlevel 1 goto :error

echo [0/8] 运行环境自检...
python D:\quant_system\scripts\preflight_check.py
if errorlevel 1 goto :error

echo [1/8] 升级数据库三期结构...
python D:\quant_system\scripts\init_db_v3.py
if errorlevel 1 goto :error

echo [2/8] 升级数据库四期结构...
python D:\quant_system\scripts\init_db_v4.py
if errorlevel 1 goto :error

echo [3/8] 从 Tushare 刷新股票池...
python D:\quant_system\scripts\refresh_symbol_universe.py
if errorlevel 1 goto :error

echo [4/8] 从 Tushare 刷新交易日历...
python D:\quant_system\scripts\refresh_trade_calendar.py 20240101 20261231
if errorlevel 1 goto :error

echo [5/8] 用 Tushare 采集日线(20只冒烟验证)...
python D:\quant_system\scripts\collect_daily_tushare.py 20250101 20250314 20
if errorlevel 1 goto :error

echo [6/8] 用 AKShare 采集日线(20只补源验证)...
python D:\quant_system\scripts\collect_daily_from_db.py 20250101 20250314 20
if errorlevel 1 goto :error

echo [7/8] 采集指数日线...
python D:\quant_system\scripts\collect_index_daily.py 20250101 20250314
if errorlevel 1 goto :error

echo [8/8] 完成
pause
exit /b 0

:error
echo 某一步执行失败，请查看上方报错
pause
exit /b 1
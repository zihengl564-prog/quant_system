@echo off
cd /d D:\quant_system

call .venv310\Scripts\activate

python -m src.scheduler.scheduler_runner ^
  --hour 18 ^
  --minute 10 ^
  --calendar-lookback-days 60 ^
  --calendar-forward-days 30 ^
  --repair-lookback-days 20 ^
  --max-daily-dates 3 ^
  --max-daily-basic-dates 3 ^
  --max-std-dates 5

pause
@echo off
REM Food Price Tracker - One-click data update
REM Fetches the latest Malaysian (KPDN) and international (World Bank)
REM prices, then checks for price spikes.
cd /d "%~dp0"

set PYTHON=C:\Users\cheek\AppData\Local\Programs\Python\Python313\python.exe
if not exist "%PYTHON%" set PYTHON=python

echo === Updating Malaysian prices (KPDN PriceCatcher) ===
"%PYTHON%" main.py scrape-malaysia --months 2

echo.
echo === Updating international prices (World Bank) ===
"%PYTHON%" main.py scrape --months 3

echo.
echo === Checking for price spikes ===
"%PYTHON%" main.py alerts

echo.
echo Done! Launch start_dashboard.bat to view the data.
pause

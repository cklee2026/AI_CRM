@echo off
REM Food Price Tracker - Dashboard Launcher with Auto-Update
REM Double-click this file to open the dashboard in your browser.
cd /d "%~dp0"

set PYTHON=C:\Users\ACER\AppData\Local\Programs\Python\Python311\python.exe
if not exist "%PYTHON%" set PYTHON=python

echo.
echo ============================================
echo   Food Price Tracker Dashboard
echo ============================================
echo.
echo Checking and updating price data...
echo.

REM Run data update before starting dashboard
"%PYTHON%" -c "from src.scrapers.pricecatcher import run; result = run(months_back=1); print(result['message'])"

if %ERRORLEVEL% neq 0 (
    echo Warning: Data update failed, but dashboard will still start with existing data.
)

echo.
echo Starting dashboard...
echo.
"%PYTHON%" -m streamlit run src/visualization/dashboards.py
pause

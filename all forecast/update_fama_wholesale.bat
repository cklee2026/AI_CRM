@echo off
REM Food Price Tracker - FAMA wholesale price update (Sabah)
REM Drives the official FAMA Power BI dashboard in a headless browser to
REM collect Sabah wholesale (Borong) prices. Slower than the other scrapers
REM because it launches a browser - run it on its own when you want fresh
REM wholesale numbers.
cd /d "%~dp0"

set PYTHON=C:\Users\cheek\AppData\Local\Programs\Python\Python313\python.exe
if not exist "%PYTHON%" set PYTHON=python

echo === First-time setup check: Playwright browser ===
"%PYTHON%" -c "import playwright" 2>nul || "%PYTHON%" -m pip install playwright
"%PYTHON%" -m playwright install chromium

echo.
echo === Scraping FAMA Sabah wholesale (Borong) prices ===
"%PYTHON%" main.py scrape-fama --level Borong --state SABAH

echo.
echo Done! Launch start_dashboard.bat and use the Price Type filter
echo on the Data page to see wholesale vs retail.
pause

@echo off
setlocal
cd /d "%~dp0"
echo ARR Data Hub to Storm Generator ^(ICM and XPSWMM^)
echo.
py -3 hub_to_storm_generator.py
if errorlevel 1 (
  echo.
  echo Build failed. See messages above.
  pause
  exit /b 1
)
echo.
pause

@echo off
setlocal
cd /d "%~dp0"
set "JATO_ISCC="
for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do if not defined JATO_ISCC set "JATO_ISCC=%%I"
if not defined JATO_ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "JATO_ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined JATO_ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "JATO_ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined JATO_ISCC (
  echo Install Inno Setup 6 from https://jrsoftware.org/isdl.php
  echo Then run this script again. If installed elsewhere, add its folder to PATH.
  pause
  exit /b 1
)
call build.bat --no-pause
if errorlevel 1 goto :err
"%JATO_ISCC%" installer.iss
if errorlevel 1 goto :err
python source_release.py
if errorlevel 1 goto :err
echo.
echo Ready: installer-output\jatotrainer-Setup.exe
pause
exit /b 0
:err
echo Installer build failed. Read the error above.
pause
exit /b 1

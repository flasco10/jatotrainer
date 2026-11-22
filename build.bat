@echo off
setlocal
cd /d "%~dp0"
where dotnet >nul 2>&1
if errorlevel 1 (
  echo Install the .NET 8 SDK to build the bundled osu! reader.
  goto :err
)
if not defined JATO_MSYS2 set "JATO_MSYS2=C:\msys64"
if not exist "%JATO_MSYS2%\usr\bin\bash.exe" (
  echo Install MSYS2, or set JATO_MSYS2 to its installation folder. See README.md.
  goto :err
)
set "MSYSTEM=UCRT64"
set "CHERE_INVOKING=1"
"%JATO_MSYS2%\usr\bin\bash.exe" -lc "bash ./build_ffmpeg.sh"
if errorlevel 1 goto :err
dotnet publish native\OsuReader.csproj -c Release -r win-x64 --self-contained true -p:GeneratePackageOnBuild=false -o build-tools\reader --source https://api.nuget.org/v3/index.json
if errorlevel 1 goto :err
build-tools\reader\Jatotrainer.OsuReader.exe --self-test
if errorlevel 1 goto :err
python -m pip install -r requirements.txt
if errorlevel 1 goto :err
python -m PyInstaller --noconfirm --clean --onedir --windowed --name jatotrainer --icon assets\jatotrainer.ico --add-data "assets;assets" --collect-all customtkinter --collect-all simfile --collect-all fs --collect-all msdparser --collect-all pkg_resources --exclude-module PIL._avif --add-data "LICENSE;." --add-data "THIRD_PARTY.md;." jatotrainer.py
if errorlevel 1 goto :err
copy /y build-tools\audio\ffmpeg.exe dist\jatotrainer\ffmpeg.exe >nul
if errorlevel 1 goto :err
copy /y build-tools\reader\Jatotrainer.OsuReader.exe dist\jatotrainer\Jatotrainer.OsuReader.exe >nul
if errorlevel 1 goto :err
mkdir dist\jatotrainer\licenses 2>nul
copy /y vendor\piotrekol\LICENSE dist\jatotrainer\licenses\PIOTREKOL-GPL.txt >nul
if errorlevel 1 goto :err
copy /y JATOTRAINER-MIT-NOTICE.txt dist\jatotrainer\licenses\JATOTRAINER-MIT-NOTICE.txt >nul
if errorlevel 1 goto :err
copy /y build-tools\audio\licenses\* dist\jatotrainer\licenses\ >nul
if errorlevel 1 goto :err
copy /y build-tools\audio\FFMPEG-BUILD.txt dist\jatotrainer\licenses\FFMPEG-BUILD.txt >nul
if errorlevel 1 goto :err
powershell -NoProfile -Command "$root = Split-Path (Get-Command dotnet.exe).Source; $ErrorActionPreference = 'Stop'; Copy-Item (Join-Path $root 'LICENSE.txt') 'dist/jatotrainer/licenses/DOTNET-LICENSE.txt'; Copy-Item (Join-Path $root 'ThirdPartyNotices.txt') 'dist/jatotrainer/licenses/DOTNET-NOTICES.txt'"
if errorlevel 1 goto :err
dotnet --info > dist\jatotrainer\licenses\DOTNET-BUILD.txt
echo.
echo Ready: dist\jatotrainer\jatotrainer.exe
if /I not "%~1"=="--no-pause" pause
exit /b 0
:err
echo Build failed. Read the error above.
if /I not "%~1"=="--no-pause" pause
exit /b 1

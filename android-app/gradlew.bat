@echo off
setlocal
set "BEFIKR_GRADLE_VERSION=9.6.0"
set "BEFIKR_GRADLE_HOME=%USERPROFILE%\.gradle\befikr-bootstrap\gradle-%BEFIKR_GRADLE_VERSION%"

if not exist "%BEFIKR_GRADLE_HOME%\bin\gradle.bat" (
    echo Downloading Gradle %BEFIKR_GRADLE_VERSION% for this Android project...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; $root=Join-Path $env:USERPROFILE '.gradle\befikr-bootstrap'; $zip=Join-Path $env:TEMP 'befikr-gradle-9.6.0-bin.zip'; New-Item -ItemType Directory -Force -Path $root | Out-Null; Invoke-WebRequest -Uri 'https://services.gradle.org/distributions/gradle-9.6.0-bin.zip' -OutFile $zip; Expand-Archive -LiteralPath $zip -DestinationPath $root -Force; Remove-Item -LiteralPath $zip"
    if errorlevel 1 exit /b 1
)

call "%BEFIKR_GRADLE_HOME%\bin\gradle.bat" %*
exit /b %ERRORLEVEL%

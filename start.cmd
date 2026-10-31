@echo off
for /f "tokens=2 delims=:" %%C in ('chcp') do set "OLDCP=%%C"
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

rem Start AegisBank from Windows CMD by delegating to WSL.
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"

where wsl.exe >nul 2>nul
if errorlevel 1 (
  echo [AegisBank] WSL is required. Install WSL first, or run bash start.sh inside WSL.
  exit /b 1
)

set "DISTRO="
set "LINUX_REPO="
if "%REPO:~0,2%"=="\\" goto :from_unc
goto :from_drive

:from_unc
set "TRIMMED=%REPO:~2%"
for /f "tokens=1,2,* delims=\" %%A in ("%TRIMMED%") do (
  set "HOST=%%A"
  set "DISTRO=%%B"
  set "TAIL=%%C"
)
if /i not "!HOST!"=="wsl.localhost" if /i not "!HOST!"=="wsl$" (
  echo [AegisBank] Unsupported UNC path. Put the repository on a local drive or in WSL.
  exit /b 1
)
if not defined TAIL (
  set "LINUX_REPO=/"
) else (
  set "TAIL=!TAIL:\=/!"
  set "LINUX_REPO=/!TAIL!"
)
goto :run

:from_drive
if not "%REPO:~1,1%"==":" (
  echo [AegisBank] Use a local drive path or a WSL path for this repository.
  exit /b 1
)
set "DRIVE=%REPO:~0,1%"
for %%D in (a b c d e f g h i j k l m n o p q r s t u v w x y z) do if /i "%DRIVE%"=="%%D" set "DRIVE=%%D"
set "TAIL=%REPO:~2%"
set "TAIL=!TAIL:\=/!"
set "LINUX_REPO=/mnt/!DRIVE!!TAIL!"
goto :run

:run
echo [AegisBank] WSL path: !LINUX_REPO!
if defined DISTRO (
  wsl.exe -d !DISTRO! --cd "!LINUX_REPO!" -- bash start.sh %*
) else (
  wsl.exe --cd "!LINUX_REPO!" -- bash start.sh %*
)
set "CODE=%ERRORLEVEL%"
if defined OLDCP chcp !OLDCP! >nul
endlocal & exit /b %CODE%
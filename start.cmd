@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem One Windows implementation for CMD and PowerShell, including UNC paths.
rem Use -Repo and -Distro to select a Linux checkout from any working directory.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
exit /b %ERRORLEVEL%

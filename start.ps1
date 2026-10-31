#Requires -Version 5.1
<#
.SYNOPSIS
  Start AegisBank from Windows PowerShell by delegating to WSL.

.DESCRIPTION
  The backend must run in Linux-compatible Python. This wrapper translates the
  current repository location (Windows drive or \\wsl.localhost path) to a WSL
  path, then runs the same `bash start.sh` entry used on Linux/WSL.
#>
[CmdletBinding()]
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

try {
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    [Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
    $OutputEncoding = [Console]::OutputEncoding
}
catch {
    # Keep the original console encoding if the host does not allow changes.
}
$repo = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($repo)) {
    $repo = (Get-Location).Path
}

$wslDistro = $null
if ($repo -match '^\\\\wsl(?:\$|\.localhost)\\([^\\]+)\\(.*)$') {
    $wslDistro = $Matches[1]
    $linuxRepo = '/' + ($Matches[2] -replace '\\', '/')
}
else {
    if ($repo.StartsWith('\\\\')) {
        throw 'PowerShell 入口无法映射这个网络路径。请把仓库放到 Windows 盘符或 WSL 文件系统中再运行 start.ps1。'
    }
    $escapedRepo = $repo.Replace('\', '\\')
    $converted = & wsl.exe wslpath -a $escapedRepo 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($converted)) {
        throw '未找到可用的 WSL。请先安装 WSL，或从 WSL 终端直接运行 bash start.sh。'
    }
    $linuxRepo = ([string]$converted).Trim()
}

$wslArgs = @()
if ($wslDistro) {
    $wslArgs += @('-d', $wslDistro)
}
$wslArgs += @('--cd', $linuxRepo, '--', 'bash', 'start.sh')
if ($NoBrowser) {
    $wslArgs += '--no-browser'
}

Write-Host "[AegisBank] WSL path: $linuxRepo"
& wsl.exe @wslArgs
exit $LASTEXITCODE
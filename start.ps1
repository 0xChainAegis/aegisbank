#Requires -Version 5.1
<#
.SYNOPSIS
  Start AegisBank in WSL, with an explicit repository and distribution if needed.
#>
[CmdletBinding()]
param(
    [string]$Repo,
    [string]$Distro,
    [switch]$NoBrowser,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$LauncherArgs
)

$ErrorActionPreference = 'Stop'
try {
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $OutputEncoding = [Console]::OutputEncoding
}
catch {
    # A non-console host may not expose an encoding setter.
}

# Use a process API rather than file association/PATHEXT resolution. Native
# arguments are quoted as Windows argv, never evaluated as a command string.
function Invoke-Wsl {
    param([string[]]$Arguments, [switch]$Capture)
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = (Get-Command wsl.exe -ErrorAction Stop).Source
    $info.UseShellExecute = $false
    $quoted = foreach ($argument in $Arguments) {
        if ($argument -and $argument -notmatch '[\s"]') { $argument; continue }
        $value = [regex]::Replace($argument, '(\\*)"', '$1$1\"')
        $value = [regex]::Replace($value, '(\\+)$', '$1$1')
        '"' + $value + '"'
    }
    $info.Arguments = $quoted -join ' '
    $info.RedirectStandardOutput = [bool]$Capture
    if ($Capture) { $info.StandardOutputEncoding = [Text.UTF8Encoding]::new($false) }
    $process = [Diagnostics.Process]::Start($info)
    try {
        $output = if ($Capture) { $process.StandardOutput.ReadToEnd() } else { '' }
        $process.WaitForExit()
        return @{ Code = $process.ExitCode; Output = $output }
    }
    finally { $process.Dispose() }
}

try {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        throw '未找到 wsl.exe；请使用已有 WSL 环境运行此产品。'
    }
    if ([string]::IsNullOrWhiteSpace($Repo)) { $Repo = $PSScriptRoot }
    if ([string]::IsNullOrWhiteSpace($Repo)) {
        throw '无法确定仓库位置；请用 -Repo 指定 Linux 主线仓库绝对路径。'
    }

    $wslArgs = @()
    if ($Repo -match '^\\\\wsl(?:\$|\.localhost)\\([^\\]+)\\(.*)$') {
        $pathDistro = $Matches[1]
        $linuxRepo = '/' + ($Matches[2] -replace '\\', '/')
        if ($Distro -and $Distro -ne $pathDistro) {
            throw "-Distro $Distro 与仓库 UNC 路径中的 $pathDistro 不一致。"
        }
        $Distro = $pathDistro
    }
    elseif ($Repo.StartsWith('/')) {
        $linuxRepo = $Repo
    }
    elseif ($Repo -match '^[A-Za-z]:\\') {
        if ($Distro) { $wslArgs = @('-d', $Distro) }
        # Pass the original path as one argument, without shell interpolation.
        $conversion = Invoke-Wsl -Arguments ($wslArgs + @('--exec', 'wslpath', '-a', '-u', $Repo)) -Capture
        $converted = $conversion.Output
        if ($conversion.Code -ne 0 -or [string]::IsNullOrWhiteSpace($converted)) {
            throw '仓库路径转换失败；请核对 -Distro 和 -Repo，使用 wsl.exe -l -v 查看发行版。'
        }
        $linuxRepo = ([string]$converted).Trim()
    }
    else {
        throw '不支持此仓库路径；-Repo 需要 Linux 绝对路径、Windows 盘符路径或 WSL UNC 路径。'
    }

    if ($Distro) { $wslArgs = @('-d', $Distro) }
    Write-Host "[AegisBank] WSL distro: $(if ($Distro) { $Distro } else { '(default)' })"
    Write-Host "[AegisBank] Repository: $linuxRepo"
    $check = Invoke-Wsl -Arguments ($wslArgs + @('--exec', 'test', '-f', "$linuxRepo/start.sh"))
    if ($check.Code -ne 0) {
        throw "所选发行版无法读取 $linuxRepo/start.sh；请核对发行版与 Linux 主线路径，不要使用冻结的 Windows 历史副本。"
    }

    $startArgs = @()
    if ($NoBrowser) { $startArgs += '--no-browser' }
    if ($null -ne $LauncherArgs) { $startArgs += $LauncherArgs }
    # This is a foreground process: keep this terminal open and stop with Ctrl+C.
    $result = Invoke-Wsl -Arguments ($wslArgs + @('--cd', $linuxRepo, '--exec', 'bash', './start.sh') + $startArgs)
    $code = $result.Code
    if ($code -ne 0) {
        [Console]::Error.WriteLine("[AegisBank] 启动失败（退出码 $code），请查看上方错误及日志；服务未宣称就绪。")
    }
    exit $code
}
catch {
    [Console]::Error.WriteLine("[AegisBank] $($_.Exception.Message)")
    exit 1
}

# 安装"每日8点自动推送"Windows 计划任务
# 用法（普通权限，电脑开机且用户登录时才会执行）：
#   powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1
# 用法（管理员权限，即使未登录也会执行，每天8点）：
#   powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -RunAsSystem
# 可选参数：
#   -At "09:30"       修改推送时间
#   -TaskName "xxx"   修改任务名称
#   -PythonPath "C:\..."  指定 Python 解释器路径

param(
    [string]$At = "08:00",
    [string]$TaskName = "DailyJobDigest",
    [switch]$RunAsSystem,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root "daily_job_digest.py"

if (-not (Test-Path $script)) {
    throw "找不到主脚本：$script"
}

# 定位 Python 解释器
if ($PythonPath) {
    $python = $PythonPath
} else {
    $cmd = Get-Command python -ErrorAction Stop
    $python = $cmd.Source
}
if (-not (Test-Path $python)) {
    throw "Python 解释器不存在：$python"
}
Write-Host "Python: $python"
Write-Host "脚本:   $script"
Write-Host "时间:   每天 $At"

# 任务动作：运行 python daily_job_digest.py（工作目录=项目根目录）
$action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew

if ($RunAsSystem) {
    # 以 SYSTEM 身份运行：无需密码，未登录也会执行，但需要管理员权限
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -User "SYSTEM" -RunLevel Highest -Force | Out-Null
    Write-Host "已创建计划任务：$TaskName（每天 $At，SYSTEM 身份，未登录也会运行）"
} else {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Force | Out-Null
    Write-Host "已创建计划任务：$TaskName（每天 $At，当前用户登录时运行）"
    Write-Host '提示：如需「即使未登录也执行」，请以管理员身份运行并加 -RunAsSystem 参数。'
}

Write-Host ""
Write-Host "验证：Get-ScheduledTask -TaskName $TaskName"
Write-Host "手动立即运行一次：Start-ScheduledTask -TaskName $TaskName"
Write-Host "查看日志：$root\logs\digest.log"

# 卸载"每日8点自动推送"计划任务
param(
    [string]$TaskName = "DailyJobDigest"
)

$ErrorActionPreference = "Stop"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "已卸载计划任务：$TaskName"
} else {
    Write-Host "计划任务不存在：$TaskName"
}

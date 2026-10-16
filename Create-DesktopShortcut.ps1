$ErrorActionPreference = 'Stop'
$appDirectory = $PSScriptRoot
$pythonWindowless = Join-Path $env:USERPROFILE 'miniconda3\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonWindowless)) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $pythonWindowless = Join-Path (Split-Path -Parent $pythonCommand.Source) 'pythonw.exe'
    }
}
if (-not (Test-Path -LiteralPath $pythonWindowless)) {
    throw 'Python with Tkinter is required. Cannot locate pythonw.exe.'
}
$desktopDirectory = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopDirectory 'PaperShot.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonWindowless
$shortcut.Arguments = '"' + (Join-Path $appDirectory 'app.py') + '"'
$shortcut.WorkingDirectory = $appDirectory
$shortcut.IconLocation = (Join-Path $appDirectory 'PaperShot.ico') + ',0'
$shortcut.Description = 'PaperShot - Personal research paper digest'
$shortcut.Save()
$check = $shell.CreateShortcut($shortcutPath)
if ($check.TargetPath -ne $pythonWindowless -or -not (Test-Path -LiteralPath $shortcutPath)) {
    throw 'Shortcut verification failed.'
}
Write-Output ('Created: ' + $shortcutPath)
Write-Output ('Target: ' + $check.TargetPath)
Write-Output ('Icon: ' + $check.IconLocation)

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("$env:USERPROFILE\Desktop\Whisper Typing.lnk")
$sc.TargetPath = "$env:USERPROFILE\whisper-typing\start.bat"
$sc.WorkingDirectory = "$env:USERPROFILE\whisper-typing"
$sc.Description = "Whisper Typing - Voice to Text"
$sc.WindowStyle = 7
$sc.Save()
Write-Host "Shortcut created on Desktop"

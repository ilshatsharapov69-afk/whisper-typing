' Hidden runner for keepalive.ps1 — Task Scheduler must not flash a console.
CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""D:\whisper-typing\keepalive.ps1""", 0, False

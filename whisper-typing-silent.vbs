Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\GigaByte\whisper-typing"
WshShell.Run "cmd /c .venv\Scripts\python.exe -m whisper_typing", 0, False

Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "d:\whisper-typing"
WshShell.Run "cmd /c .venv\Scripts\python.exe -m whisper_typing", 0, False

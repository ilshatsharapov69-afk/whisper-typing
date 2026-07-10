# Self-heal: relaunch whisper-typing if it is not running.
# Liveness check via the app's single-instance mutex — deliberately NO WMI:
# Get-CimInstance/Get-Process-by-cmdline hang when the Winmgmt service is
# stuck (known failure mode on this machine).
$m = $null
$alive = [System.Threading.Mutex]::TryOpenExisting("WhisperTyping_SingleInstance", [ref]$m)
if ($m) { $m.Dispose() }
if (-not $alive) {
    Start-Process -FilePath "wscript.exe" -ArgumentList '"D:\whisper-typing\whisper-typing-silent.vbs"' -WorkingDirectory "D:\whisper-typing"
}

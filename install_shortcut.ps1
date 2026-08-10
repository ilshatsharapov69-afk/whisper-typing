# Puts a "Whisper Typing" shortcut on the Desktop (and in the Start menu).
# The shortcut launches the silent VBS starter, so no console window appears.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $root "whisper-typing-silent.vbs"
$icon = Join-Path $root "src\whisper_typing\assets\app.ico"

if (-not (Test-Path $target)) { throw "not found: $target" }
if (-not (Test-Path $icon)) { throw "icon not found: $icon - run tools\make_icon.py first" }

$shell = New-Object -ComObject WScript.Shell
$places = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs")
)

foreach ($place in $places) {
    if (-not (Test-Path $place)) { continue }
    $link = $shell.CreateShortcut((Join-Path $place "Whisper Typing.lnk"))
    $link.TargetPath = "wscript.exe"
    $link.Arguments = '"' + $target + '"'
    $link.WorkingDirectory = $root
    $link.IconLocation = $icon
    $link.Description = "Voice typing: numpad Enter to start and stop"
    $link.Save()
    Write-Host "shortcut created: $place"
}

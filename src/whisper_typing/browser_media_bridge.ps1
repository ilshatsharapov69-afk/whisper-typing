$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

public static class BackgroundMediaClick {
    private delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential)]
    private struct RECT { public int Left, Top, Right, Bottom; }

    [StructLayout(LayoutKind.Sequential)]
    private struct POINT { public int X, Y; }

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
    [DllImport("user32.dll")]
    private static extern bool EnumChildWindows(IntPtr parent, EnumWindowsProc callback, IntPtr lParam);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetClassName(IntPtr hwnd, StringBuilder text, int count);
    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")]
    private static extern bool IsWindowEnabled(IntPtr hwnd);
    [DllImport("user32.dll")]
    private static extern bool IsWindow(IntPtr hwnd);
    [DllImport("user32.dll")]
    private static extern bool GetWindowRect(IntPtr hwnd, out RECT rect);
    [DllImport("user32.dll")]
    private static extern bool GetClientRect(IntPtr hwnd, out RECT rect);
    [DllImport("user32.dll")]
    private static extern bool ScreenToClient(IntPtr hwnd, ref POINT point);
    [DllImport("user32.dll")]
    private static extern bool PostMessage(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam);

    private const uint WM_MOUSEMOVE = 0x0200;
    private const uint WM_LBUTTONDOWN = 0x0201;
    private const uint WM_LBUTTONUP = 0x0202;
    private const int MK_LBUTTON = 0x0001;

    private static string ClassName(IntPtr hwnd) {
        var text = new StringBuilder(256);
        GetClassName(hwnd, text, text.Capacity);
        return text.ToString();
    }

    public static bool WindowAlive(long hwnd) {
        IntPtr handle = new IntPtr(hwnd);
        return IsWindow(handle) && IsWindowVisible(handle);
    }

    public static long[] ChromeTopWindows() {
        var result = new List<long>();
        EnumWindows(delegate(IntPtr hwnd, IntPtr unused) {
            if (IsWindowVisible(hwnd) && ClassName(hwnd) == "Chrome_WidgetWin_1") {
                result.Add(hwnd.ToInt64());
            }
            return true;
        }, IntPtr.Zero);
        return result.ToArray();
    }

    private static IntPtr RendererAt(IntPtr parent, int screenX, int screenY) {
        IntPtr best = IntPtr.Zero;
        long bestArea = long.MaxValue;
        EnumChildWindows(parent, delegate(IntPtr hwnd, IntPtr unused) {
            if (!IsWindowVisible(hwnd) || !IsWindowEnabled(hwnd) ||
                ClassName(hwnd) != "Chrome_RenderWidgetHostHWND") {
                return true;
            }
            RECT rect;
            if (!GetWindowRect(hwnd, out rect) || screenX < rect.Left || screenX >= rect.Right ||
                screenY < rect.Top || screenY >= rect.Bottom) {
                return true;
            }
            long area = (long)(rect.Right - rect.Left) * (rect.Bottom - rect.Top);
            if (area < bestArea) {
                best = hwnd;
                bestArea = area;
            }
            return true;
        }, IntPtr.Zero);
        return best;
    }

    private static IntPtr MouseParam(int x, int y) {
        int packed = (x & 0xffff) | ((y & 0xffff) << 16);
        return new IntPtr(packed);
    }

    public static bool Click(long topWindow, int screenX, int screenY) {
        IntPtr top = new IntPtr(topWindow);
        IntPtr target = RendererAt(top, screenX, screenY);
        if (target == IntPtr.Zero) target = top;

        POINT point = new POINT { X = screenX, Y = screenY };
        RECT client;
        if (!ScreenToClient(target, ref point) || !GetClientRect(target, out client)) return false;
        if (point.X < client.Left || point.X >= client.Right ||
            point.Y < client.Top || point.Y >= client.Bottom) return false;

        int neutralX = Math.Max(client.Left + 1, Math.Min(client.Right - 2, 500));
        int neutralY = Math.Max(client.Top + 1, Math.Min(client.Bottom - 2, 500));
        PostMessage(target, WM_MOUSEMOVE, IntPtr.Zero, MouseParam(neutralX, neutralY));
        Thread.Sleep(100);
        PostMessage(target, WM_MOUSEMOVE, IntPtr.Zero, MouseParam(point.X, point.Y));
        Thread.Sleep(100);
        bool down = PostMessage(target, WM_LBUTTONDOWN, new IntPtr(MK_LBUTTON), MouseParam(point.X, point.Y));
        Thread.Sleep(30);
        bool up = PostMessage(target, WM_LBUTTONUP, IntPtr.Zero, MouseParam(point.X, point.Y));
        return down && up;
    }
}
"@

# ── State ────────────────────────────────────────────────────────────────────
# A lease = a player control this helper moved from playing to paused, and is
# therefore allowed to move back. Leases survive command timeouts on the Python
# side, so this list is the only record of what the app owes the user.
$script:leases = @()
$script:logs = New-Object System.Collections.ArrayList

$script:ButtonCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Button
)

# YouTube names the player button "Pause (k)" / "Play (k)" -- the keyboard hint
# is part of the accessible name, so an optional "(shortcut)" suffix is allowed.
# The pattern is anchored at both ends on purpose: thumbnails on listing pages
# are named "Play video: <title>", and clicking one starts a random video.
$script:PAUSE_NAME = "(?i)^(pause|pause video|приостановить|пауза|остановить)(\s*\([^)]{1,16}\))?$"
$script:PLAY_NAME = "(?i)^(play|play video|воспроизвести|продолжить|возобновить)(\s*\([^)]{1,16}\))?$"

$script:STATE_ATTEMPTS = 14
$script:STATE_DELAY_MS = 60
$script:MIN_BUTTON_PX = 8
$script:MAX_BUTTON_PX = 180

function Add-Log([string]$Message) {
    [void]$script:logs.Add($Message)
}

function Write-Response([hashtable]$Value) {
    $Value["logs"] = @($script:logs)
    $script:logs.Clear()
    [Console]::Out.WriteLine(($Value | ConvertTo-Json -Compress -Depth 4))
    [Console]::Out.Flush()
}

function Get-ControlName($Control) {
    try { return [string]$Control.Current.Name } catch { return $null }
}

function Get-RuntimeId($Control) {
    try { return ($Control.GetRuntimeId() -join ".") } catch { return "" }
}

function Get-ControlState($Control) {
    # "playing" = the button offers Pause; "paused" = it offers Play.
    $name = Get-ControlName $Control
    if ($null -eq $name) { return "gone" }
    if ($name -match $script:PAUSE_NAME) { return "playing" }
    if ($name -match $script:PLAY_NAME) { return "paused" }
    return "unknown"
}

function Test-UsableControl($Control) {
    try {
        if ($Control.Current.IsOffscreen) { return $false }
        $rect = $Control.Current.BoundingRectangle
        return ($rect.Width -ge $script:MIN_BUTTON_PX -and $rect.Height -ge $script:MIN_BUTTON_PX -and
                $rect.Width -le $script:MAX_BUTTON_PX -and $rect.Height -le $script:MAX_BUTTON_PX)
    } catch { return $false }
}

function Invoke-BackgroundClick($Lease) {
    try {
        if (-not (Test-UsableControl $Lease.Control)) { return $false }
        $rect = $Lease.Control.Current.BoundingRectangle
        $x = [int][Math]::Round($rect.Left + ($rect.Width / 2.0))
        $y = [int][Math]::Round($rect.Top + ($rect.Height / 2.0))
        return [BackgroundMediaClick]::Click([long]$Lease.Hwnd, $x, $y)
    } catch { return $false }
}

function Wait-MediaState($Control, [string]$Target, [int]$Attempts = 0) {
    if ($Attempts -le 0) { $Attempts = $script:STATE_ATTEMPTS }
    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        Start-Sleep -Milliseconds $script:STATE_DELAY_MS
        if ((Get-ControlState $Control) -eq $Target) { return $true }
    }
    return $false
}

function Set-MediaState($Lease, [string]$Target) {
    # Idempotent transition with undo. A Chromium accessibility name can lag
    # behind the real player state (SMTC just paused the same video), so a
    # "toggle" click can do the exact opposite of what was intended. When the
    # verification fails, click once more to put the media back where it was.
    # Returns "changed" (we moved it), "already" (nothing to do) or "failed".
    $state = Get-ControlState $Lease.Control
    if ($state -eq $Target) { return "already" }
    if ($state -ne "playing" -and $state -ne "paused") { return "failed" }

    if (-not (Invoke-BackgroundClick $Lease)) { return "failed" }
    if (Wait-MediaState $Lease.Control $Target) { return "changed" }

    $actual = Get-ControlState $Lease.Control
    Add-Log "stale name on '$($Lease.Name)': wanted $Target, got $actual -- undoing"
    if ($actual -ne $Target -and (Invoke-BackgroundClick $Lease)) {
        [void](Wait-MediaState $Lease.Control $state 8)
    }
    return "failed"
}

function Get-ControlByRuntimeId([long]$Hwnd, [string]$RuntimeId) {
    if ([string]::IsNullOrEmpty($RuntimeId)) { return $null }
    try {
        if (-not [BackgroundMediaClick]::WindowAlive($Hwnd)) { return $null }
        $root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]::new($Hwnd))
        if ($null -eq $root) { return $null }
        foreach ($button in $root.FindAll(
            [System.Windows.Automation.TreeScope]::Descendants, $script:ButtonCondition)) {
            if ((Get-RuntimeId $button) -eq $RuntimeId) { return $button }
        }
    } catch {}
    return $null
}

function Resolve-LeaseControl($Lease) {
    # Cached AutomationElements go stale when Chrome rebuilds its tree (tab
    # switch, PiP open/close). Re-find the same control by RuntimeId instead of
    # losing the lease and leaving the user's video paused forever.
    if ((Get-ControlState $Lease.Control) -ne "gone") { return $Lease.Control }
    $found = Get-ControlByRuntimeId $Lease.Hwnd $Lease.RuntimeId
    if ($null -ne $found) { Add-Log "re-resolved a stale lease control" }
    return $found
}

function Get-PlayingBrowserControls {
    $result = New-Object System.Collections.ArrayList
    foreach ($rawHwnd in [BackgroundMediaClick]::ChromeTopWindows()) {
        try {
            $root = [System.Windows.Automation.AutomationElement]::FromHandle(
                [IntPtr]::new([long]$rawHwnd))
            if ($null -eq $root) { continue }
            foreach ($button in $root.FindAll(
                [System.Windows.Automation.TreeScope]::Descendants, $script:ButtonCondition)) {
                $name = Get-ControlName $button
                if ($null -eq $name -or -not ($name -match $script:PAUSE_NAME)) { continue }
                if (-not (Test-UsableControl $button)) { continue }
                [void]$result.Add([pscustomobject]@{
                    Hwnd = [long]$rawHwnd
                    Control = $button
                    RuntimeId = (Get-RuntimeId $button)
                    Name = $name
                })
            }
        } catch {}
    }
    return @($result)
}

function Invoke-PauseCommand {
    # Carried leases are NOT resumed first: a new recording wants everything
    # quiet, and playing the previous take's media just to pause it again was
    # the audible "video starts for a second" glitch.
    $carried = @($script:leases)
    $script:leases = @()
    $seen = @{}
    $paused = 0

    foreach ($lease in $carried) {
        $control = Resolve-LeaseControl $lease
        if ($null -eq $control) { Add-Log "carried lease vanished"; continue }
        $lease.Control = $control
        if (-not [string]::IsNullOrEmpty($lease.RuntimeId)) { $seen[$lease.RuntimeId] = $true }
        $state = Get-ControlState $control
        if ($state -eq "paused") {
            $script:leases += $lease
            continue
        }
        # The user restarted it by hand while we still owed a resume.
        if ((Set-MediaState $lease "paused") -eq "changed") {
            $script:leases += $lease
            $paused++
        }
    }

    foreach ($candidate in Get-PlayingBrowserControls) {
        if (-not [string]::IsNullOrEmpty($candidate.RuntimeId) -and
            $seen.ContainsKey($candidate.RuntimeId)) { continue }
        if (-not [string]::IsNullOrEmpty($candidate.RuntimeId)) {
            $seen[$candidate.RuntimeId] = $true
        }
        if ($paused -gt 0) {
            # A tab and its Picture-in-Picture window are two controls over one
            # video. Give the one we just paused time to publish its new name,
            # or the next candidate reads a stale "Pause" and restarts it.
            Start-Sleep -Milliseconds 150
        }
        $outcome = Set-MediaState $candidate "paused"
        if ($outcome -eq "changed") {
            $script:leases += $candidate
            $paused++
        } elseif ($outcome -eq "already") {
            Add-Log "'$($candidate.Name)' was already paused -- not leased"
        }
    }

    return @{ paused = $paused; leased = @($script:leases).Count }
}

function Invoke-ResumeCommand {
    $owed = @($script:leases)
    $script:leases = @()
    $resumed = 0
    foreach ($lease in $owed) {
        $control = Resolve-LeaseControl $lease
        if ($null -eq $control) { Add-Log "leased control vanished before resume"; continue }
        $lease.Control = $control
        # Only media still sitting where we left it may be restarted.
        if ((Get-ControlState $control) -ne "paused") {
            Add-Log "'$($lease.Name)' is no longer paused -- leaving it alone"
            continue
        }
        if ((Set-MediaState $lease "playing") -eq "changed") { $resumed++ }
    }
    return @{ resumed = $resumed; leased = $owed.Count }
}

Write-Response @{ ok = $true; ready = $true; id = 0 }

while ($null -ne ($line = [Console]::In.ReadLine())) {
    $id = 0
    $command = ""
    try {
        # Wire format: "<id> <command>". The id lets the client discard a
        # response that arrived after its own timeout instead of killing the
        # helper -- killing it would destroy every outstanding lease.
        $parts = $line.Trim() -split "\s+", 2
        if ($parts.Count -eq 2) {
            $id = [int]$parts[0]
            $command = $parts[1].ToLowerInvariant()
        } else {
            $command = $parts[0].ToLowerInvariant()
        }
    } catch {
        $command = ""
    }
    if ([string]::IsNullOrEmpty($command)) { continue }

    try {
        switch ($command) {
            "pause" {
                $result = Invoke-PauseCommand
                Write-Response @{ ok = $true; id = $id; paused = $result.paused; leased = $result.leased }
            }
            "resume" {
                $result = Invoke-ResumeCommand
                Write-Response @{ ok = $true; id = $id; resumed = $result.resumed; leased = $result.leased }
            }
            "ping" {
                Write-Response @{ ok = $true; id = $id; alive = $true; leased = @($script:leases).Count }
            }
            "stop" {
                $result = Invoke-ResumeCommand
                Write-Response @{ ok = $true; id = $id; resumed = $result.resumed; leased = $result.leased }
            }
            default { Write-Response @{ ok = $false; id = $id; error = "unknown command '$command'" } }
        }
    } catch {
        Write-Response @{ ok = $false; id = $id; error = $_.Exception.Message }
    }
    if ($command -eq "stop") { break }
}

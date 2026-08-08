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

$script:leases = @()

function Write-Response([hashtable]$Value) {
    [Console]::Out.WriteLine(($Value | ConvertTo-Json -Compress -Depth 4))
    [Console]::Out.Flush()
}

function Get-ControlName($Control) {
    try { return [string]$Control.Current.Name } catch { return "" }
}

function Test-PauseName([string]$Name) {
    return $Name -match "(?i)^(pause|pause video|приостановить|пауза|остановить)(\b|\s|$)"
}

function Test-PlayName([string]$Name) {
    return $Name -match "(?i)^(play|play video|воспроизвести|продолжить)(\b|\s|$)"
}

function Invoke-VerifiedClick($Lease, [string]$ExpectedState) {
    $control = $Lease.Control
    try {
        $rect = $control.Current.BoundingRectangle
        if ($rect.Width -lt 8 -or $rect.Height -lt 8 -or $control.Current.IsOffscreen) {
            return $false
        }
        $x = [int][Math]::Round($rect.Left + ($rect.Width / 2.0))
        $y = [int][Math]::Round($rect.Top + ($rect.Height / 2.0))
        if (-not [BackgroundMediaClick]::Click([long]$Lease.Hwnd, $x, $y)) {
            return $false
        }
        for ($attempt = 0; $attempt -lt 12; $attempt++) {
            Start-Sleep -Milliseconds 75
            $name = Get-ControlName $control
            if ($ExpectedState -eq "play" -and (Test-PlayName $name)) { return $true }
            if ($ExpectedState -eq "pause" -and (Test-PauseName $name)) { return $true }
        }
    } catch {}
    return $false
}

function Get-PlayingBrowserControls {
    $result = New-Object System.Collections.ArrayList
    $buttonCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Button
    )
    foreach ($rawHwnd in [BackgroundMediaClick]::ChromeTopWindows()) {
        try {
            $hwnd = [IntPtr]::new([long]$rawHwnd)
            $root = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
            if ($null -eq $root) { continue }
            $buttons = $root.FindAll(
                [System.Windows.Automation.TreeScope]::Descendants,
                $buttonCondition
            )
            foreach ($button in $buttons) {
                $name = Get-ControlName $button
                if (-not (Test-PauseName $name)) { continue }
                $rect = $button.Current.BoundingRectangle
                if ($button.Current.IsOffscreen -or $rect.Width -lt 8 -or $rect.Height -lt 8 -or
                    $rect.Width -gt 180 -or $rect.Height -gt 180) { continue }
                [void]$result.Add([pscustomobject]@{
                    Hwnd = [long]$rawHwnd
                    Control = $button
                    Name = $name
                })
            }
        } catch {}
    }
    return @($result)
}

function Resume-Leases {
    $oldLeases = @($script:leases)
    $script:leases = @()
    $resumed = 0
    foreach ($lease in $oldLeases) {
        $name = Get-ControlName $lease.Control
        if ((Test-PlayName $name) -and (Invoke-VerifiedClick $lease "pause")) {
            $resumed++
        }
    }
    return @{ resumed = $resumed; leased = $oldLeases.Count }
}

function Pause-Playing {
    # Heal an abandoned lease before creating a new one.
    [void](Resume-Leases)
    $paused = 0
    foreach ($lease in Get-PlayingBrowserControls) {
        # Re-read immediately before acting; SMTC may have paused it meanwhile.
        if (-not (Test-PauseName (Get-ControlName $lease.Control))) { continue }
        if (Invoke-VerifiedClick $lease "play") {
            $script:leases += $lease
            $paused++
        }
    }
    return $paused
}

Write-Response @{ ok = $true; ready = $true }
while ($null -ne ($line = [Console]::In.ReadLine())) {
    try {
        switch ($line.Trim().ToLowerInvariant()) {
            "pause" {
                $count = Pause-Playing
                Write-Response @{ ok = $true; paused = $count }
            }
            "resume" {
                $result = Resume-Leases
                Write-Response @{ ok = $true; resumed = $result.resumed; leased = $result.leased }
            }
            "stop" {
                $result = Resume-Leases
                Write-Response @{ ok = $true; resumed = $result.resumed; leased = $result.leased }
                break
            }
            default { Write-Response @{ ok = $false; error = "unknown command" } }
        }
        if ($line.Trim().ToLowerInvariant() -eq "stop") { break }
    } catch {
        Write-Response @{ ok = $false; error = $_.Exception.Message }
    }
}

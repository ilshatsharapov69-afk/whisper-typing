"""Top-level package for whisper-typing."""

# --- WMI-hang guard (Windows / Python 3.13+) ---
# Python 3.13's platform.win32_ver() queries WMI (Win32_OperatingSystem) as the
# "canonical" source for the OS version. sounddevice calls platform.system() at
# import time, so when the machine's WMI service is hung the WMI query blocks
# forever -> `import sounddevice` hangs -> the whole app never starts.
#
# platform already ships a complete non-WMI fallback (sys.getwindowsversion +
# `ver` + registry), but it only kicks in when the WMI call raises OSError —
# never when it merely hangs. Setting platform._wmi = None makes _wmi_query()
# raise OSError immediately, forcing that fallback. This is exactly the state
# platform puts itself in once a WMI query fails, so platform.system()/release()/
# version() keep returning correct values.
import sys as _sys

if _sys.platform == "win32":
    import platform as _platform

    _platform._wmi = None

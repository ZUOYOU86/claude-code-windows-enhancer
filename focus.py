"""focus.py - Bring a window to the foreground.

Runs as the claude-notify:// protocol handler.  Launched via pythonw.exe
(GUI subsystem) so Windows treats it as a proper interactive process,
not a background console app.  This makes SetForegroundWindow /
SwitchToThisWindow actually succeed.

URL format:  claude-notify://focus?hwnd=591878&hwnd=723106
"""
import sys
import time
import os
import ctypes
from ctypes import wintypes
import re

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ── Win32 definitions ───────────────────────────────────────────────────

HWND_TOPMOST = wintypes.HWND(-1)
HWND_NOTOPMOST = wintypes.HWND(-2)
SW_RESTORE = 9
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040
SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
SPIF_SENDCHANGE = 0x0002
SPIF_UPDATEINIFILE = 0x0001
LSFW_LOCK = 1
LSFW_UNLOCK = 2

# Set up function signatures
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND

user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, wintypes.LPVOID]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL

user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL

user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
user32.AllowSetForegroundWindow.restype = wintypes.BOOL

user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL

user32.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
user32.SwitchToThisWindow.restype = None

user32.LockSetForegroundWindow.argtypes = [wintypes.UINT]
user32.LockSetForegroundWindow.restype = wintypes.BOOL

user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL

user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT,
    wintypes.LPVOID, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL

# SendInput (modern replacement for keybd_event)
wintypes.ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", wintypes.ULONG_PTR)]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", wintypes.ULONG_PTR)]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]

class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]

user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


# ── helpers ─────────────────────────────────────────────────────────────

def _send_alt_key():
    """Simulate Alt press+release via SendInput – grants foreground rights."""
    inputs = (INPUT * 2)()
    # Press Alt
    inputs[0].type = 1  # INPUT_KEYBOARD
    inputs[0].union.ki.wVk = VK_MENU
    # Release Alt
    inputs[1].type = 1
    inputs[1].union.ki.wVk = VK_MENU
    inputs[1].union.ki.dwFlags = KEYEVENTF_KEYUP
    user32.SendInput(2, inputs, ctypes.sizeof(INPUT))


def _restore_if_minimized(hwnd):
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)


def _focus_window(hwnd):
    """Try to bring *hwnd* to the foreground. Returns True on success."""
    if not hwnd or not user32.IsWindow(hwnd):
        return False

    _restore_if_minimized(hwnd)

    # ── Method 1: SwitchToThisWindow (Windows' own Alt+Tab path) ────────
    user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    _send_alt_key()
    # Force Z-order change BEFORE focus – so the window is on top visually
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.05)
    user32.SwitchToThisWindow(hwnd, True)
    time.sleep(0.12)
    if user32.GetForegroundWindow() == hwnd:
        return True

    # ── Method 2: AttachThreadInput + SetForegroundWindow ───────────────
    current_tid = kernel32.GetCurrentThreadId()
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)

    aF, aT = False, False
    if fg_tid and fg_tid != current_tid:
        aF = user32.AttachThreadInput(current_tid, fg_tid, True)
    if target_tid and target_tid != current_tid and target_tid != fg_tid:
        aT = user32.AttachThreadInput(current_tid, target_tid, True)

    _send_alt_key()
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)

    if aF:
        user32.AttachThreadInput(current_tid, fg_tid, False)
    if aT:
        user32.AttachThreadInput(current_tid, target_tid, False)

    time.sleep(0.12)
    if user32.GetForegroundWindow() == hwnd:
        return True

    # ── Method 3: LockSetForegroundWindow + TopMost brute-force ─────────
    user32.LockSetForegroundWindow(LSFW_UNLOCK)
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    time.sleep(0.06)
    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    _send_alt_key()
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.LockSetForegroundWindow(LSFW_LOCK)

    time.sleep(0.12)
    return user32.GetForegroundWindow() == hwnd


# ── diagnostic log ──────────────────────────────────────────────────────

_LOG_PATH = os.path.join(os.environ.get("TEMP", ""), "claude_focus_log.txt")

def _log(msg):
    ts = time.strftime("%H:%M:%S")
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as lf:
            lf.write(f"{ts}  {msg}\n")
    except Exception:
        pass


# ── main ────────────────────────────────────────────────────────────────

def main():
    _log("=" * 50)
    _log(f"focus.py started  args={sys.argv[1:] if len(sys.argv) > 1 else 'none'}")

    # Disable foreground lock timeout
    user32.SystemParametersInfoW(SPI_SETFOREGROUNDLOCKTIMEOUT, 0, None,
                                 SPIF_SENDCHANGE | SPIF_UPDATEINIFILE)

    url = sys.argv[1] if len(sys.argv) > 1 else ""
    hwnds = []
    session_id = ""

    # Parse sid=NNN and hwnd=NNN from URL
    if url:
        for part in url.split("?")[-1].split("&"):
            if part.startswith("sid="):
                session_id = part[4:]
            m = re.match(r"hwnd=(\d+)", part)
            if m:
                try:
                    hwnds.append(int(m.group(1)))
                except (ValueError, OverflowError):
                    pass
    _log(f"Parsed sid={session_id}  hwnds from URL: {hwnds}")

    # If URL has a session id, read the per-session file
    if session_id:
        sid_file = os.path.join(os.environ.get("TEMP", ""),
                                f"claude_code_hwnd_{session_id}.txt")
        try:
            with open(sid_file) as fh:
                sid_hwnds = []
                for line in fh:
                    line = line.strip()
                    if line.isdigit():
                        try:
                            sid_hwnds.append(int(line))
                        except (ValueError, OverflowError):
                            pass
                if sid_hwnds:
                    hwnds = sid_hwnds
            _log(f"Loaded {len(hwnds)} HWND(s) from session file sid={session_id}")
        except Exception as e:
            _log(f"Session file read failed: {e}")

    if not hwnds:
        # Legacy: try reading from file
        f = os.path.join(os.environ.get("TEMP", ""), "claude_code_hwnd.txt")
        try:
            with open(f) as fh:
                for line in fh:
                    line = line.strip()
                    if line.isdigit():
                        try:
                            hwnds.append(int(line))
                        except (ValueError, OverflowError):
                            pass
            _log(f"Loaded {len(hwnds)} HWND(s) from legacy file")
        except Exception as e:
            _log(f"Legacy file read failed: {e}")

    if not hwnds:
        _log("FATAL: no HWNDs found – exiting")
        return

    for i, hwnd in enumerate(hwnds):
        _log(f"--- HWND [{i}] {hwnd} ---")
        is_valid = user32.IsWindow(hwnd)
        is_minimized = user32.IsIconic(hwnd) if is_valid else False
        fg_before = user32.GetForegroundWindow()
        _log(f"  IsWindow={is_valid}  IsIconic={is_minimized}  ForegroundBefore={fg_before}")

        if not is_valid:
            _log("  SKIP: HWND invalid")
            continue

        result = _focus_window(hwnd)
        fg_after = user32.GetForegroundWindow()
        _log(f"  Result={result}  ForegroundAfter={fg_after}  Match={fg_after == hwnd}")

        if result:
            _log(f"  SUCCESS – window {hwnd} is now foreground")
            break
        else:
            _log(f"  FAILED – foreground is {fg_after}, wanted {hwnd}")

    # Restore foreground lock timeout
    user32.SystemParametersInfoW(SPI_SETFOREGROUNDLOCKTIMEOUT, 0,
                                 ctypes.c_void_p(200000),
                                 SPIF_SENDCHANGE)
    _log("focus.py exiting")


import os as _os_module  # noqa – used below
if __name__ == "__main__":
    main()

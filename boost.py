"""boost.py - Persistent background booster for Claude Code.

Keeps Claude at FULL SPEED even when minimized / background:
  HIGH process priority | power throttling OFF | efficiency mode OFF
  memory priority = 5  | all threads ABOVE_NORMAL

Usage:
    python boost.py --daemon     Run as background watchdog (auto-exits
                                 when Claude process is gone)
    python boost.py              One-shot boost
    python boost.py --all        Boost ALL running Claude instances
"""
import sys
import os
import ctypes
from ctypes import wintypes
import time
import signal

kernel32 = ctypes.windll.kernel32
ntdll = ctypes.windll.ntdll

# ── constants ──────────────────────────────────────────────────────────
HIGH_PRIORITY_CLASS = 0x00000080
THREAD_PRIORITY_ABOVE_NORMAL = 1
MEMORY_PRIORITY_NORMAL = 5
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_INFORMATION = 0x0200
PROCESS_SET_QUOTA = 0x0100
THREAD_SET_INFORMATION = 0x0020
THREAD_QUERY_INFORMATION = 0x0040
TH32CS_SNAPPROCESS = 0x02
TH32CS_SNAPTHREAD = 0x04

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260),
    ]

class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]

class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG),
                ("StateMask", wintypes.ULONG)]

class PROCESS_EFFICIENCY_STATE(ctypes.Structure):
    _fields_ = [("Value", wintypes.ULONG)]


def _get_parent_pid(pid):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return None
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    try:
        if kernel32.Process32First(snap, ctypes.byref(entry)):
            while True:
                if entry.th32ProcessID == pid:
                    return entry.th32ParentProcessID
                if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snap)
    return None


def _find_our_tree_pids():
    """Walk UP from this Python process to find all ancestor PIDs."""
    pids = set()
    pids.add(os.getpid())
    pid = os.getpid()
    for _ in range(8):
        parent = _get_parent_pid(pid)
        if not parent:
            break
        pids.add(parent)
        pid = parent
    return pids


def _find_all_claude_pids():
    """Return PIDs of Claude-related processes in OUR process tree only.

    Walks up from Python to find ancestors, then walks down to include
    all descendants.  Never touches unrelated system node.exe processes.
    """
    pids = set()
    # Walk up to find all ancestors
    pid = os.getpid()
    pids.add(pid)
    for _ in range(8):
        parent = _get_parent_pid(pid)
        if not parent:
            break
        pids.add(parent)
        pid = parent

    # Walk down: find children of every PID in our tree
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap != -1:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        try:
            if kernel32.Process32First(snap, ctypes.byref(entry)):
                while True:
                    if entry.th32ParentProcessID in pids:
                        pids.add(entry.th32ProcessID)
                    if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                        break
        finally:
            kernel32.CloseHandle(snap)
    return pids


def _is_process_alive(pid):
    """Check if a process with given PID still exists."""
    h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if h:
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        kernel32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    return False


def boost_pid(pid):
    """Apply all performance tweaks. Returns list of applied actions."""
    results = []

    # ── Process priority: HIGH ──────────────────────────────────────────
    # OpenProcess(access, inherit, pid) – access flags FIRST
    h = kernel32.OpenProcess(PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION,
                             False, pid)
    if h:
        kernel32.SetPriorityClass(h, HIGH_PRIORITY_CLASS)
        results.append("PRI=HIGH")
        kernel32.CloseHandle(h)

    # ── Disable power throttling ────────────────────────────────────────
    h = kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
    if h:
        try:
            state = PROCESS_POWER_THROTTLING_STATE()
            state.Version = 1
            state.ControlMask = PROCESS_POWER_THROTTLING_EXECUTION_SPEED
            state.StateMask = 0
            kernel32.SetProcessInformation(
                h, 4, ctypes.byref(state), ctypes.sizeof(state))
            results.append("NO_THROTTLE")
        except Exception:
            pass
        kernel32.CloseHandle(h)

    # ── Disable efficiency mode (Win 11 EcoQoS) ────────────────────────
    h = kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
    if h:
        try:
            eff = PROCESS_EFFICIENCY_STATE()
            eff.Value = 2
            kernel32.SetProcessInformation(
                h, 1, ctypes.byref(eff), ctypes.sizeof(eff))
        except Exception:
            pass
        kernel32.CloseHandle(h)

    # ── Memory priority ─────────────────────────────────────────────────
    h = kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
    if h:
        try:
            mem_pri = wintypes.ULONG(MEMORY_PRIORITY_NORMAL)
            ntdll.NtSetInformationProcess(
                h, 0x27, ctypes.byref(mem_pri), ctypes.sizeof(mem_pri))
        except Exception:
            pass
        kernel32.CloseHandle(h)

    # ── Boost all threads ───────────────────────────────────────────────
    boosted = 0
    tsnap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if tsnap != -1:
        tentry = THREADENTRY32()
        tentry.dwSize = ctypes.sizeof(THREADENTRY32)
        if kernel32.Thread32First(tsnap, ctypes.byref(tentry)):
            while True:
                if tentry.th32OwnerProcessID == pid:
                    th = kernel32.OpenThread(
                        THREAD_SET_INFORMATION | THREAD_QUERY_INFORMATION,
                        False, tentry.th32ThreadID)
                    if th:
                        kernel32.SetThreadPriority(th, THREAD_PRIORITY_ABOVE_NORMAL)
                        kernel32.CloseHandle(th)
                        boosted += 1
                if not kernel32.Thread32Next(tsnap, ctypes.byref(tentry)):
                    break
        kernel32.CloseHandle(tsnap)
    if boosted:
        results.append(f"THR={boosted}")

    return results


def _claude_is_running():
    """Return True if any Claude-related process is still alive."""
    for pid in _find_all_claude_pids():
        if _is_process_alive(pid):
            return True
    return False


# ── daemon mode ─────────────────────────────────────────────────────────

_PID_FILE = os.path.join(os.environ.get("TEMP", ""), "claude_boost_daemon.pid")


def _daemon_running():
    """Check if another daemon is already running."""
    if os.path.isfile(_PID_FILE):
        try:
            with open(_PID_FILE) as f:
                old_pid = int(f.read().strip())
            if _is_process_alive(old_pid):
                return True
        except Exception:
            pass
    return False


def run_daemon():
    """Run continuously, re-boosting every 30 s. Exits when Claude stops."""
    if _daemon_running():
        return  # Already running

    # Write PID file
    with open(_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    try:
        while _claude_is_running():
            pids = _find_all_claude_pids()
            for pid in sorted(pids):
                if _is_process_alive(pid):
                    boost_pid(pid)
            time.sleep(30)
    finally:
        try:
            os.remove(_PID_FILE)
        except Exception:
            pass


# ── main ────────────────────────────────────────────────────────────────

def main():
    if "--daemon" in sys.argv:
        run_daemon()
        return

    # One-shot boost
    if "--all" in sys.argv:
        pids = _find_all_claude_pids()
    else:
        pids = _find_our_tree_pids()

    for pid in sorted(pids):
        if _is_process_alive(pid):
            r = boost_pid(pid)
            if r:
                print(f"  PID {pid}: {' '.join(r)}")


if __name__ == "__main__":
    main()

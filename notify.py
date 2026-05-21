"""Claude Code notification helper - Windows toast (clickable) + sound.

Usage: python notify.py <event_type>

Clicking the toast notification switches to the Claude Code terminal.

On Windows 10/11, toast notifications require a Start Menu shortcut with a
matching AppUserModelID. Without it, Windows silently suppresses the toast.
This script auto-creates that shortcut on first run via COM (IPropertyStore).
"""
import sys
import subprocess
import os
import ctypes
import tempfile
from ctypes import wintypes

MESSAGES = {
    "PermissionRequest": (
        "\U0001f514 Claude Code - 权限申请",
        "Claude 需要你的批准才能继续，点击此处切换到终端。"
    ),
    "Elicitation": (
        "\U0001f4ac Claude Code - 需要交互",
        "Claude 正在等待你的输入或选择，点击此处切换到终端。"
    ),
    "Stop": (
        "Claude Code - 响应完成",
        "Claude 已完成当前回答，点击此处查看终端。"
    ),
    "TaskCompleted": (
        "Claude Code - 任务完成",
        "一个子任务已标记为完成，点击此处查看终端。"
    ),
}

SOUNDS = {
    "PermissionRequest": "SystemHand",
    "Elicitation": "SystemAsterisk",
    "Stop": "SystemNotification",
    "TaskCompleted": "SystemNotification",
}


# ── config ──────────────────────────────────────────────────────────────
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
HWND_FILE = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()), "claude_code_hwnd.txt")
FOCUS_SCRIPT = os.path.join(_PROJECT_DIR, "focus.py")
# Use pythonw.exe (GUI subsystem) for the protocol handler so Windows
# treats it as an interactive process capable of setting the foreground
# window.  PowerShell / conhost-based handlers are silently denied.
_PYTHONW = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
if not os.path.isfile(_PYTHONW):
    _PYTHONW = sys.executable  # fallback to python.exe
PROTOCOL = "claude-notify"
AUMID = "ClaudeCode"

_START_MENU_DIR = os.path.join(
    os.environ.get("APPDATA", ""),
    "Microsoft", "Windows", "Start Menu", "Programs",
)
_SHORTCUT_PATH = os.path.join(_START_MENU_DIR, "Claude Code.lnk")

# The HWNDs discovered by save_console_hwnd() are also embedded directly
# into the toast launch URL so the focus script doesn't need to read any
# file – each toast carries its own target.  This naturally handles
# multiple Claude instances: toast from instance A → focuses A's terminal,
# toast from instance B → focuses B's terminal.
_HWND_LIST = []  # populated by save_console_hwnd(), used by send_toast()
_SESSION_ID = ""  # stable per-tab identifier for multi-instance support


# ── low-level helpers ───────────────────────────────────────────────────

def _ps_script(commands, timeout=15):
    """Run a PowerShell script, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", commands],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


# ── process-tree window discovery ───────────────────────────────────────
# When notify.py runs inside a modern terminal (Windows Terminal, mintty,
# etc.), GetConsoleWindow() returns 0.  GetForegroundWindow() is useless
# because the user is looking at a browser, not the terminal.  Instead we
# walk UP the process ancestry to find a visible top-level window – which
# will be the terminal frame that hosts Claude Code.

# Toolhelp snapshot constants
_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize",              wintypes.DWORD),
        ("cntUsage",            wintypes.DWORD),
        ("th32ProcessID",       wintypes.DWORD),
        ("th32DefaultHeapID",   ctypes.POINTER(wintypes.ULONG)),
        ("th32ModuleID",        wintypes.DWORD),
        ("cntThreads",          wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase",      wintypes.LONG),
        ("dwFlags",             wintypes.DWORD),
        ("szExeFile",           ctypes.c_char * 260),
    ]


def _get_parent_pid(pid):
    """Return the parent process ID of *pid*, or None on failure."""
    kernel32 = ctypes.windll.kernel32
    snap = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snap == _INVALID_HANDLE_VALUE:
        return None
    entry = _PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
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


def _find_visible_windows_for_pid(pid):
    """Return ALL visible top-level windows (with titles) for *pid*.

    Returns a list of (hwnd, title) tuples.  When there are multiple
    windows (e.g. several Windows Terminal instances), the focus script
    will try each one so at least one of them works.
    """
    result = []
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _enum_callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            wnd_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wnd_pid))
            if wnd_pid.value == pid:
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, buf, 512)
                if len(buf.value) > 0:
                    result.append((hwnd, buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(_enum_callback), 0)
    return result


def save_console_hwnd(session_name=None):
    """Discover terminal window HWNDs + session id.

    If *session_name* is given AND a previously-captured HWND file
    exists for that session (via --capture), use THAT specific HWND.
    This provides accurate multi-instance window targeting.
    Otherwise fall back to process-tree auto-discovery.
    """
    global _HWND_LIST, _SESSION_ID
    try:
        _SESSION_ID = session_name
        hwnds = []

        # If session was captured (via UserPromptSubmit hook), use the
        # exact HWND saved at that moment – 100% accurate targeting.
        if session_name:
            sid_file = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()),
                                    f"claude_code_hwnd_{session_name}.txt")
            if os.path.isfile(sid_file):
                with open(sid_file) as f:
                    captured = [int(line.strip()) for line in f
                                if line.strip().isdigit()]
                if captured and all(ctypes.windll.user32.IsWindow(h) for h in captured):
                    hwnds = captured
                    _HWND_LIST = hwnds
                    return  # Captured HWND is authoritative – done.

        # Auto-discovery fallback
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()

        if hwnd:
            hwnds = [hwnd]
            if not _SESSION_ID:
                _SESSION_ID = str(os.getpid())
        else:
            pid = os.getpid()
            prev_pid = None
            for _ in range(8):
                parent = _get_parent_pid(pid)
                if not parent:
                    break
                candidates = _find_visible_windows_for_pid(parent)
                if candidates:
                    hwnds = [h for h, _ in candidates]
                    if not _SESSION_ID:
                        _SESSION_ID = str(prev_pid if prev_pid else pid)
                    break
                prev_pid = parent
                pid = parent

        # Ensure _SESSION_ID is never None (fallback: Python PID)
        if not _SESSION_ID:
            _SESSION_ID = str(os.getpid())

        _HWND_LIST = hwnds

        if hwnds and _SESSION_ID:
            sid_file = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()),
                                    f"claude_code_hwnd_{_SESSION_ID}.txt")
            lines = [f"{h}" for h in hwnds]
            with open(sid_file, "w") as f:
                f.write("\n".join(lines))
            with open(HWND_FILE, "w") as f:
                f.write("\n".join(lines))
    except Exception:
        pass
def _create_shortcut_lazy():
    """Create the .lnk file via WScript.Shell (fast, no AUMID yet)."""
    os.makedirs(_START_MENU_DIR, exist_ok=True)
    rc, _, err = _ps_script(f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{_SHORTCUT_PATH}')
$sc.TargetPath = 'explorer.exe'
$sc.WorkingDirectory = '%USERPROFILE%'
$sc.IconLocation = 'shell32.dll,13'
$sc.Save()
""")
    return rc == 0, err


def _set_shortcut_aumid():
    """Set the AppUserModelID on the shortcut via IPropertyStore COM.

    This is the critical step.  Without it, Windows silently suppresses
    every toast from CreateToastNotifier(AUMID) because the caller has no
    registered identity in the Start Menu.
    """
    rc, out, err = _ps_script(f"""
$shortcutPath = '{_SHORTCUT_PATH}'
$appId = '{AUMID}'

$code = @'
using System;
using System.Runtime.InteropServices;

[ComImport, Guid("00021401-0000-0000-C000-000000000046")]
public class ShellLink {{ }}

public enum STGM : uint {{ READ = 0, WRITE = 1, READWRITE = 2 }}

[ComImport, Guid("0000010b-0000-0000-C000-000000000046"),
 InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPersistFile {{
    void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string pszFile);
    int IsDirty();
    void Load([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, uint dwMode);
    void Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, bool fRemember);
    void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string pszFileName);
}}

[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"),
 InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPropertyStore {{
    uint GetCount(out uint cProps);
    IntPtr GetAt(uint iProp, out PropertyKey pkey);
    uint GetValue(ref PropertyKey key, out PROPVARIANT pv);
    uint SetValue(ref PropertyKey key, ref PROPVARIANT pv);
    uint Commit();
}}

[StructLayout(LayoutKind.Sequential)]
public struct PropertyKey {{
    public Guid fmtid;
    public uint pid;
    public PropertyKey(Guid fmtid, uint pid) {{ this.fmtid = fmtid; this.pid = pid; }}
}}

// PROPVARIANT – we only need VT_LPWSTR (31)
[StructLayout(LayoutKind.Explicit, Size = 24)]
public struct PROPVARIANT {{
    [FieldOffset(0)] public ushort vt;
    [FieldOffset(8)] public IntPtr pwszVal;
}}

public static class AumidSetter {{
    private static readonly PropertyKey PKEY_AppUserModel_ID =
        new PropertyKey(new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5);

    public static void Set(string shortcutPath, string appId) {{
        var shellLink = new ShellLink();
        var pf = (IPersistFile)shellLink;
        pf.Load(shortcutPath, (uint)STGM.READWRITE);
        var ps = (IPropertyStore)shellLink;
        var prop = new PROPVARIANT();
        prop.vt = 31; // VT_LPWSTR
        prop.pwszVal = Marshal.StringToCoTaskMemUni(appId);
        var key = PKEY_AppUserModel_ID;
        ps.SetValue(ref key, ref prop);
        ps.Commit();
        Marshal.FreeCoTaskMem(prop.pwszVal);
        pf.Save(null, true);
        pf.SaveCompleted(null);
    }}
}}
'@

Add-Type -TypeDefinition $code
[AumidSetter]::Set($shortcutPath, $appId)
Write-Output 'ok'
""")
    return rc == 0 and out == "ok"


def create_shortcut():
    """Ensure a Start Menu shortcut with our AUMID exists.

    Returns True if setup succeeded or was already done.
    """
    # Quick check: does the shortcut already exist with the right AUMID?
    rc, out, _ = _ps_script(f"""
$shell = New-Object -ComObject Shell.Application
$folder = $shell.NameSpace('{_START_MENU_DIR}')
if ($folder) {{
    $file = $folder.ParseName('Claude Code.lnk')
    if ($file) {{
        $id = $file.ExtendedProperty('System.AppUserModel.ID')
        if ($id -eq '{AUMID}') {{ Write-Output 'ok' }}
    }}
}}
""")
    if rc == 0 and out == "ok":
        return True  # Already set up

    # Create the shortcut file …
    ok, _ = _create_shortcut_lazy()
    if not ok:
        return False

    # … then stamp the AppUserModelID onto it via IPropertyStore.
    return _set_shortcut_aumid()


# ── URL protocol registration ──────────────────────────────────────────

def register_protocol():
    """Register claude-notify:// URL protocol (one-time)."""
    try:
        import winreg
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                               rf"Software\Classes\{PROTOCOL}")
        winreg.SetValue(key, "", winreg.REG_SZ,
                        "URL:Claude Code Notification Protocol")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        winreg.CloseKey(key)

        cmd_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                   rf"Software\Classes\{PROTOCOL}\shell\open\command")
        # Use pythonw.exe (GUI subsystem, no console) so the process has
        # foreground-window rights that a hidden console process lacks.
        exe = _PYTHONW
        cmd = f'"{exe}" "{FOCUS_SCRIPT}" "%1"'
        winreg.SetValue(cmd_key, "", winreg.REG_SZ, cmd)
        winreg.CloseKey(cmd_key)
    except Exception:
        pass


# ── notification completeness check ─────────────────────────────────────

def check_notification_setup():
    """Return (toast_ok, sound_ok, focus_ok, details) after verifying all pieces."""
    details = []

    # 1. Check Start Menu shortcut with AppUserModelID
    shortcut_ok = os.path.isfile(_SHORTCUT_PATH)
    aumid_ok = False
    if shortcut_ok:
        rc, out, _ = _ps_script(f"""
$shell = New-Object -ComObject Shell.Application
$folder = $shell.NameSpace('{_START_MENU_DIR}')
if ($folder) {{
    $file = $folder.ParseName('Claude Code.lnk')
    if ($file) {{
        $id = $file.ExtendedProperty('System.AppUserModel.ID')
        if ($id -eq '{AUMID}') {{ Write-Output 'ok' }}
    }}
}}
""")
        aumid_ok = (rc == 0 and out == "ok")
    details.append(("Start Menu shortcut", shortcut_ok and aumid_ok,
                    f"Path={_SHORTCUT_PATH}" if shortcut_ok else "Missing"))

    # 2. Check URL protocol registration
    rc, out, _ = _ps_script("""
$cmd = (Get-ItemProperty -Path 'HKCU:\\Software\\Classes\\claude-notify\\shell\\open\\command' -ErrorAction SilentlyContinue).'(default)'
if ($cmd) { Write-Output $cmd }
""")
    protocol_ok = (rc == 0 and bool(out))
    details.append(("URL protocol", protocol_ok, out[:120] if out else "Not registered"))

    # 3. Check sound
    sound_ok = False
    try:
        import winsound
        sound_ok = True
    except ImportError:
        sound_ok = False
    details.append(("Sound (winsound)", sound_ok, "Module loaded" if sound_ok else "winsound unavailable"))

    # 4. Check WinRT toast capability
    toast_ok = False
    if aumid_ok:
        rc, out, err = _ps_script(f"""
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime]
$x = [Windows.Data.Xml.Dom.XmlDocument]::new()
$x.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text id=\"1\">test</text></binding></visual></toast>')
$nf = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{AUMID}')
$n = [Windows.UI.Notifications.ToastNotification]::new($x)
$nf.Show($n)
Write-Output 'ok'
""")
        toast_ok = (rc == 0 and out == "ok")
    details.append(("WinRT toast", toast_ok, "Test toast sent" if toast_ok else "Shortcut AUMID required"))

    # 5. Check HWND discovery
    hwnd_ok = bool(_HWND_LIST)
    details.append(("Window discovery", hwnd_ok,
                    f"Found {len(_HWND_LIST)} HWND(s)" if hwnd_ok else "No windows found"))

    return toast_ok, sound_ok, hwnd_ok, details


# ── toast notification ──────────────────────────────────────────────────

def send_toast(title, message):
    """Send a clickable Windows toast notification.

    Tries the WinRT toast API if the Start Menu shortcut is properly set up.
    Falls back to a balloon tip otherwise.
    """
    title_esc = title.replace("'", "''")
    msg_esc = message.replace("'", "''")

    hwnd_params = "&amp;".join(f"hwnd={int(h)}" for h in (_HWND_LIST or []))
    sid = _SESSION_ID or ""
    if hwnd_params:
        launch_url = f"claude-notify://focus?sid={sid}&{hwnd_params}"
    elif sid:
        launch_url = f"claude-notify://focus?sid={sid}"
    else:
        launch_url = "claude-notify://focus"
    # The URL goes into an XML attribute – & must be escaped for LoadXml.
    launch_url_xml = launch_url.replace("&", "&amp;")

    # Only try WinRT toast if the shortcut with AUMID is in place.
    # Otherwise Windows will silently suppress it and the user sees nothing.
    shortcut_ready = os.path.isfile(_SHORTCUT_PATH)
    if shortcut_ready:
        rc, _, _ = _ps_script(f"""
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime]
$x = [Windows.Data.Xml.Dom.XmlDocument]::new()
$x.LoadXml(@'
<toast launch="{launch_url_xml}" activationType="protocol" scenario="reminder">
  <visual>
    <binding template="ToastGeneric">
      <text id="1">{title_esc}</text>
      <text id="2">{msg_esc}</text>
    </binding>
  </visual>
</toast>
'@)
$nf = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{AUMID}')
$nf.Show([Windows.UI.Notifications.ToastNotification]::new($x))
""")
        if rc == 0:
            return

    # WinRT toast failed – log to diagnostic file instead of showing a
    # plain-text balloon that has no button and can't jump to the window.
    _DIAG_FILE = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()),
                               "claude_notify_error.txt")
    try:
        with open(_DIAG_FILE, "a", encoding="utf-8") as df:
            import time as _time
            df.write(f"{_time.strftime('%Y-%m-%d %H:%M:%S')}  "
                     f"Toast FAILED for event – "
                     f"shortcut_ready={shortcut_ready}  title={title_esc}\n")
    except Exception:
        pass


# ── sound ───────────────────────────────────────────────────────────────

# Custom sound file overrides – place .wav files in the project directory
# and map them to event types.  Falls back to system sounds if the file
# doesn't exist or isn't configured.
_CUSTOM_SOUNDS = {
    # "Stop": os.path.join(_PROJECT_DIR, "task_done.wav"),
}


def play_sound(sound_name):
    """Play a notification sound.

    1. If a custom .wav file is configured for this event in _CUSTOM_SOUNDS
       and the file exists, play it via winsound.PlaySound.
    2. Otherwise fall back to a system MessageBeep with an appropriate icon.
    """
    # Custom WAV file (if configured and present)
    custom = _CUSTOM_SOUNDS.get(sound_name, "")
    if custom and os.path.isfile(custom):
        try:
            import winsound
            winsound.PlaySound(custom, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        except Exception:
            pass  # Fall through to system beep

    # System beep fallback
    try:
        import winsound
        flags = {
            "SystemHand": winsound.MB_ICONHAND,
            "SystemAsterisk": winsound.MB_ICONASTERISK,
            "SystemExclamation": winsound.MB_ICONEXCLAMATION,
            "SystemNotification": winsound.MB_OK,
        }
        winsound.MessageBeep(flags.get(sound_name, winsound.MB_OK))
    except Exception:
        pass


# ── process booster ─────────────────────────────────────────────────────

def _run_boost():
    """Launch boost.py --daemon as a detached background process.

    The daemon runs continuously while Claude is alive, re-boosting
    process priority / disabling throttling every 30 s.  Only one
    daemon runs at a time (checked via PID file).
    """
    boost_script = os.path.join(_PROJECT_DIR, "boost.py")
    if not os.path.isfile(boost_script):
        return
    try:
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        subprocess.Popen(
            [sys.executable, boost_script, "--daemon"],
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        _DIAG_FILE = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()),
                                   "claude_notify_error.txt")
        try:
            with open(_DIAG_FILE, "a") as df:
                df.write(f"[boost] launch failed: {e}\n")
        except Exception:
            pass


# ── main ────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    session_name = None
    event = ""

    # Parse --session <name> and event type
    i = 0
    while i < len(args):
        if args[i] == "--session" and i + 1 < len(args):
            session_name = args[i + 1]
            i += 2
        elif args[i] in ("--check", "--setup"):
            event = args[i]
            i += 1
        else:
            event = args[i]
            i += 1

    # --capture : save foreground window as THIS session's HWND
    if event == "--capture":
        if not session_name:
            cwd_part = os.getcwd().replace(':', '').replace('\\', '_').replace('/', '_')
            shell_pid = ""
            pid = os.getpid()
            prev = None
            for _ in range(8):
                parent = _get_parent_pid(pid)
                if not parent:
                    break
                if _find_visible_windows_for_pid(parent):
                    shell_pid = str(prev if prev else pid)
                    break
                prev = parent
                pid = parent
            session_name = f"{cwd_part}_{shell_pid}" if shell_pid else cwd_part
        fg = ctypes.windll.user32.GetForegroundWindow()
        if fg:
            sid_file = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()),
                                    f"claude_code_hwnd_{session_name}.txt")
            with open(sid_file, "w") as f:
                f.write(str(fg))
        return

    # --check : run diagnostics only, no notification
    if event == "--check":
        save_console_hwnd(session_name)
        register_protocol()
        create_shortcut()
        toast_ok, sound_ok, focus_ok, details = check_notification_setup()
        print("=" * 60)
        print("  Claude Code Notification - Diagnostics")
        print("=" * 60)
        all_ok = True
        for name, ok, detail in details:
            flag = "PASS" if ok else "FAIL"
            all_ok = all_ok and ok
            print(f"  [{flag}] {name:<24s}  {detail}")
        print("=" * 60)
        if all_ok:
            print("  All checks passed.")
        else:
            print("  Some checks failed – review the items above.")
            print("  Run: python notify.py --setup   to re-initialise.")
        return

    # --setup : force re-initialise the shortcut and protocol
    if event == "--setup":
        if os.path.isfile(_SHORTCUT_PATH):
            try:
                os.remove(_SHORTCUT_PATH)
            except Exception:
                pass

    # Auto-detect session: CWD + stable shell PID (the process directly
    # below WindowsTerminal in the ancestry chain).  This guarantees
    # uniqueness even when two Claude instances share the same directory.
    # Sanitize session_name: keep only safe chars for filenames
    def _sanitize_session(name):
        return "".join(c for c in name if c.isalnum() or c in "_-.")

    if not session_name:
        cwd_part = _sanitize_session(
            os.getcwd().replace(':', '_').replace('\\', '_').replace('/', '_'))
        shell_pid = ""
        pid = os.getpid()
        prev = None
        for _ in range(8):
            parent = _get_parent_pid(pid)
            if not parent:
                break
            if _find_visible_windows_for_pid(parent):
                shell_pid = str(prev if prev else pid)
                break
            prev = parent
            pid = parent
        session_name = f"{cwd_part}_{shell_pid}" if shell_pid else cwd_part
    else:
        session_name = _sanitize_session(session_name)

    save_console_hwnd(session_name)
    register_protocol()
    create_shortcut()

    if event in ("", "--setup"):
        print("Setup complete.  Run: python notify.py --check")
        return

    if event in MESSAGES:
        # Boost Claude processes before sending notification – keeps
        # background performance identical to foreground.
        _run_boost()

        title, msg = MESSAGES[event]
        sound = SOUNDS.get(event)
        send_toast(title, msg)
        if sound:
            play_sound(sound)


if __name__ == "__main__":
    main()

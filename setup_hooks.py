"""setup_hooks.py - Configure Claude Code hooks for Windows notifications.

This script helps you wire up Claude Code so that desktop notifications
fire automatically when Claude:
  - Finishes responding          (Stop)
  - Needs permission approval    (PermissionRequest)
  - Is waiting for user input    (Elicitation)
  - Completes a sub-task         (TaskCompleted)

Usage:
  python setup_hooks.py install       Write hook config to CLAUDE.md
  python setup_hooks.py uninstall     Remove hook config from CLAUDE.md
  python setup_hooks.py test          Simulate all 4 event types
  python setup_hooks.py status        Show current hook status
"""

import sys
import os
import subprocess
import json
import textwrap
from pathlib import Path

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
NOTIFY_SCRIPT = os.path.join(PROJECT_DIR, "notify.py")
BOOST_SCRIPT = os.path.join(PROJECT_DIR, "boost.py")
PYTHON_EXE = sys.executable

# Marker comments that bracket our hook block inside CLAUDE.md / settings
MARKER_BEGIN = "<!-- claude-notify-hooks BEGIN -->"
MARKER_END = "<!-- claude-notify-hooks END -->"

# The hook configuration snippet (Markdown + code block)
HOOK_BLOCK = textwrap.dedent(f"""\
{MARKER_BEGIN}
## Windows Desktop Notifications + Background Boost

### 通知（4 种事件）
| 事件 | 通知内容 |
|------|---------|
| Stop（响应完成） | "Claude 已完成当前回答" |
| PermissionRequest（权限申请） | "Claude 需要你的批准" |
| Elicitation（需要交互） | "Claude 正在等待你的输入" |
| TaskCompleted（任务完成） | "一个子任务已标记为完成" |

点击通知即可跳转到对应 Claude 终端窗口。

### 后台提速
UserPromptSubmit（首次发消息）→ 自动启动 boost 守护进程，
保持 Claude 后台全速运行（禁用降频/节流/效率模式）。

**首次使用请运行：** `python setup_hooks.py test`

```bash
# 命令（由 Claude Code Hook 自动调用）
# {PYTHON_EXE} "{NOTIFY_SCRIPT}" <event>
# {PYTHON_EXE} "{BOOST_SCRIPT}" --daemon
```
{MARKER_END}""")


def _find_claude_md():
    """Locate CLAUDE.md in the project root or home directory."""
    candidates = [
        os.path.join(os.getcwd(), "CLAUDE.md"),
        os.path.join(os.path.expanduser("~"), "CLAUDE.md"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return candidates[0]  # Default: create in CWD


def _write_hook_settings(settings_path, session_name=None):
    """Merge hook commands into .claude/settings.local.json."""
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    cfg = {}
    if os.path.isfile(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except json.JSONDecodeError:
            cfg = {}

    if "hooks" not in cfg:
        cfg["hooks"] = {}

    # Build command – add --session if a name was given
    cmd = f'{PYTHON_EXE} "{NOTIFY_SCRIPT}"'
    if session_name:
        cmd += f" --session {session_name}"
    for event in ["Stop", "PermissionRequest", "Elicitation", "TaskCompleted"]:
        entry = {"command": f"{cmd} {event}"}
        if event not in cfg["hooks"]:
            cfg["hooks"][event] = [entry]
        else:
            existing_cmds = [h.get("command", "") for h in cfg["hooks"][event]]
            if entry["command"] not in existing_cmds:
                cfg["hooks"][event].append(entry)

    # UserPromptSubmit: capture window HWND first, then launch boost daemon.
    # Session auto-detected from CWD – no manual --session needed.
    # At first-message time the user IS looking at Claude, so the foreground
    # window IS the correct WT window.
    capture_cmd = f'{PYTHON_EXE} "{NOTIFY_SCRIPT}" --capture'
    if session_name:
        capture_cmd += f" --session {session_name}"
    boost_cmd = f'{PYTHON_EXE} "{BOOST_SCRIPT}" --daemon'

    if "UserPromptSubmit" not in cfg["hooks"]:
        cfg["hooks"]["UserPromptSubmit"] = [
            {"command": capture_cmd},
            {"command": boost_cmd},
        ]
    else:
        existing = [h.get("command", "") for h in cfg["hooks"]["UserPromptSubmit"]]
        for c in [capture_cmd, boost_cmd]:
            if c not in existing:
                cfg["hooks"]["UserPromptSubmit"].append({"command": c})

    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f"  Hook settings written → {settings_path}")


def install_hooks(session_name=None):
    """Write hook block into CLAUDE.md AND .claude/settings.local.json.

    If *session_name* is given, hooks will include --session so each
    Claude window can be uniquely identified for accurate toast→focus.
    """
    # 1. Write to CLAUDE.md (LLM context)
    claude_md = _find_claude_md()
    existing = ""
    if os.path.isfile(claude_md):
        with open(claude_md, "r", encoding="utf-8") as f:
            existing = f.read()
    if MARKER_BEGIN in existing and MARKER_END in existing:
        before = existing[:existing.index(MARKER_BEGIN)]
        after = existing[existing.index(MARKER_END) + len(MARKER_END):]
        existing = before.rstrip() + "\n" + after.lstrip()
    new_content = existing.rstrip() + "\n\n" + HOOK_BLOCK + "\n"
    os.makedirs(os.path.dirname(claude_md) or ".", exist_ok=True)
    with open(claude_md, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"  CLAUDE.md updated → {claude_md}")

    # 2. Write to .claude/settings.local.json (actual hook triggers)
    settings_path = os.path.join(os.getcwd(), ".claude", "settings.local.json")
    _write_hook_settings(settings_path, session_name)

    print()
    print("Next steps:")
    if session_name:
        print(f"  Session name: {session_name}")
    print(f"  1. Verify:  python setup_hooks.py test")
    print(f"  2. Verify:  python {os.path.basename(NOTIFY_SCRIPT)} --check")
    print(f"  3. Restart Claude Code to pick up the new settings")


def uninstall_hooks():
    """Remove hook block from CLAUDE.md and settings."""
    try:
        # 1. Clean CLAUDE.md
        claude_md = _find_claude_md()
        if os.path.isfile(claude_md):
            with open(claude_md, "r", encoding="utf-8") as f:
                content = f.read()
            if MARKER_BEGIN in content and MARKER_END in content:
                before = content[:content.index(MARKER_BEGIN)]
                after = content[content.index(MARKER_END) + len(MARKER_END):]
                with open(claude_md, "w", encoding="utf-8") as f:
                    f.write((before.rstrip() + "\n" + after.lstrip()).strip() + "\n")
                print(f"CLAUDE.md cleaned → {claude_md}")

        # 2. Clean settings.local.json
        settings_path = os.path.join(os.getcwd(), ".claude", "settings.local.json")
        if os.path.isfile(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if "hooks" in cfg:
                    del cfg["hooks"]
                    with open(settings_path, "w", encoding="utf-8") as f:
                        json.dump(cfg, f, indent=2, ensure_ascii=False)
                    print(f"Hooks removed from {settings_path}")
            except (json.JSONDecodeError, OSError, IOError):
                pass
    except Exception:
        pass

    print("Uninstall complete.")


def test_notifications():
    """Simulate all 4 event types."""
    events = ["Stop", "PermissionRequest", "Elicitation", "TaskCompleted"]
    print("Testing all notification events...\n")
    for i, event in enumerate(events, 1):
        print(f"[{i}/{len(events)}] {event} ... ", end="", flush=True)
        rc = subprocess.run(
            [PYTHON_EXE, NOTIFY_SCRIPT, event],
            capture_output=True, timeout=20,
        ).returncode
        print("OK" if rc == 0 else f"FAIL (rc={rc})")
    print("\nDone.  You should have seen 4 toasts + heard sounds.")
    print("Click each toast to verify focus-jump works.")


def show_status():
    """Display current configuration status."""
    print("=" * 55)
    print("  Claude Code Windows Notification - Status")
    print("=" * 55)

    # Check CLAUDE.md
    claude_md = _find_claude_md()
    has_md = os.path.isfile(claude_md)
    has_hooks = False
    if has_md:
        with open(claude_md, "r", encoding="utf-8") as f:
            has_hooks = MARKER_BEGIN in f.read()
    print(f"  CLAUDE.md hook block:    {'INSTALLED' if has_hooks else 'MISSING'}")
    print(f"  CLAUDE.md path:          {claude_md}")

    # Check shortcut
    shortcut = os.path.join(os.environ.get("APPDATA", ""),
                            "Microsoft", "Windows", "Start Menu", "Programs",
                            "Claude Code.lnk")
    print(f"  Start Menu shortcut:     {'OK' if os.path.isfile(shortcut) else 'MISSING'}")

    # Check protocol
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Classes\claude-notify\shell\open\command")
        cmd = winreg.QueryValue(key, "")
        winreg.CloseKey(key)
        print(f"  URL protocol:            REGISTERED")
        print(f"  Protocol command:        {cmd}")
    except Exception:
        print(f"  URL protocol:            NOT REGISTERED")

    # Check focus script
    focus_py = os.path.join(PROJECT_DIR, "focus.py")
    print(f"  focus.py:                {'OK' if os.path.isfile(focus_py) else 'MISSING'}")

    # Check pythonw
    pythonw = os.path.join(os.path.dirname(PYTHON_EXE), "pythonw.exe")
    print(f"  pythonw.exe:             {'OK' if os.path.isfile(pythonw) else 'MISSING'}")

    print("=" * 55)
    if not has_hooks:
        print("  Run: python setup_hooks.py install")


def main():
    # Parse --session <name> before the command
    args = sys.argv[1:]
    session_name = None
    cmd = "status"
    i = 0
    while i < len(args):
        if args[i] == "--session" and i + 1 < len(args):
            session_name = args[i + 1]
            i += 2
        else:
            cmd = args[i]
            i += 1

    if cmd == "install":
        install_hooks(session_name)
    elif cmd == "uninstall":
        uninstall_hooks()
    elif cmd == "test":
        test_notifications()
    elif cmd == "status":
        show_status()
    else:
        print(__doc__)
        print("Valid commands: install  uninstall  test  status")
        print()
        print("Options:")
        print("  --session <name>   Use a named session for multi-instance")


if __name__ == "__main__":
    main()

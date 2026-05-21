# Claude Code Windows Enhancer

Production-ready Windows companion tools for [Claude Code](https://claude.ai/code) — **desktop notifications + one-click window focus + background CPU boost + multi-instance support**.  Zero third-party dependencies.

## What It Does

| Feature | File | Description |
|---|---|---|
| Desktop notifications | `notify.py` | Windows native toast + sound when Claude finishes / needs input |
| Window focus | `focus.py` | Click toast → Claude terminal jumps to foreground (Win32 API) |
| Background boost | `boost.py` | Prevents Windows from throttling Claude when minimized |
| Hook installer | `setup_hooks.py` | One-command Claude Code hook configuration |

## Quick Start

```powershell
# One-click install
powershell -ExecutionPolicy Bypass -File install.ps1

# Or step by step:
python notify.py --setup
python notify.py --check
python setup_hooks.py install
python setup_hooks.py test
```

## How It Works

### Notification Flow

```
Claude Code (hook fires)
  → notify.py <event>
    → Discovers terminal window HWND via process tree
    → Sends WinRT toast with "reminder" priority (bypasses Focus Assist)
    → Plays system sound / custom WAV
```

### Focus Flow (click toast)

```
Toast clicked
  → claude-notify:// protocol
  → pythonw.exe focus.py (GUI subsystem, foreground rights)
  → 3-tier focus strategy:
     1. SwitchToThisWindow (Windows Alt+Tab API)
     2. AttachThreadInput + SendInput(Alt) + SetForegroundWindow
     3. LockSetForegroundWindow + TopMost brute-force
  → Window verified via GetForegroundWindow()
```

### Boost Flow (background daemon)

```
First user message → UserPromptSubmit hook → launch boost.py --daemon
  → Every 30s while Claude runs:
    ✅ Process priority → HIGH
    ✅ Power throttling → OFF
    ✅ Efficiency mode → OFF (Win11 EcoQoS)
    ✅ Memory priority → 5 (won't be trimmed)
    ✅ All threads → ABOVE_NORMAL
  → Claude exits → daemon auto-stops
```

## Multi-Instance Auto-Isolation

**Fully automatic** — each Claude window is identified by `project directory + terminal shell PID`. First user message captures the foreground window HWND; all subsequent toasts jump to that exact window. Even same-directory instances auto-isolate (different shell PIDs).

For explicit naming:
```powershell
python setup_hooks.py install --session frontend
python setup_hooks.py install --session backend
```

## Hook Events

| Hook | When | Action |
|---|---|---|
| `UserPromptSubmit` | First user message | Capture window HWND + launch boost daemon |
| `Stop` | Claude finishes response | Toast "Response complete" |
| `PermissionRequest` | Needs user approval | Toast "Permission needed" |
| `Elicitation` | Waiting for input | Toast "Input needed" |
| `TaskCompleted` | Sub-task done | Toast "Task complete" |

## Customization

### Custom Sounds

Edit `notify.py`:
```python
_CUSTOM_SOUNDS = {
    "Stop": os.path.join(_PROJECT_DIR, "task_done.wav"),
}
```

### Custom Notification Text

Edit `notify.py`:
```python
MESSAGES = {
    "Stop": ("Custom Title", "Custom body text"),
}
```

## Commands

```powershell
# One-click setup
powershell -ExecutionPolicy Bypass -File install.ps1

# Notifications
python notify.py Stop                    # Test response-complete
python notify.py PermissionRequest       # Test permission needed
python notify.py Elicitation             # Test input needed
python notify.py TaskCompleted           # Test task done

# Management
python notify.py --check                 # 5-point diagnostics
python notify.py --setup                 # Reinitialize protocol + shortcut
python setup_hooks.py install            # Install hooks
python setup_hooks.py uninstall          # Remove hooks
python setup_hooks.py status             # Show configuration
python setup_hooks.py test               # Simulate all 4 events
python boost.py                          # One-shot process boost
python boost.py --daemon                 # Run background watchdog
```

## Requirements

- Windows 10/11
- Python 3.8+ (standard library only)
- Claude Code (any version with hook support)

## Project Structure

```
├── install.ps1         # One-click installer
├── notify.py           # Toast notifications + sound + window discovery
├── focus.py            # Window focus/jump (protocol handler)
├── boost.py            # Background performance daemon
├── setup_hooks.py      # Hook installer + diagnostics
├── README.md           # English docs
├── README_ZH.md        # Chinese docs
└── LICENSE             # MIT
```

## License

MIT — do whatever you want with it.

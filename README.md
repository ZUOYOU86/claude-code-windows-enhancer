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
cd claude-code-windows-enhancer

# 1. Initialize (register protocol + shortcut)
python notify.py --setup
python notify.py --check

# 2. Install Claude Code hooks
python setup_hooks.py install

# 3. Test all 4 event types
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
    → Launches boost.py daemon (keeps Claude at full speed)
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
First notification → launch boost.py --daemon
  → Every 30s while Claude runs:
    ✅ Process priority → HIGH
    ✅ Power throttling → OFF
    ✅ Efficiency mode → OFF (Win11 EcoQoS)
    ✅ Memory priority → 5 (won't be trimmed)
    ✅ All threads → ABOVE_NORMAL
  → Claude exits → daemon auto-stops
```

## Multi-Instance Support

```powershell
# Window A (frontend work)
python setup_hooks.py install --session frontend

# Window B (backend work)
python setup_hooks.py install --session backend
```

Each window's toast only jumps to its own terminal. Perfect isolation.

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
├── notify.py           # Toast notifications + sound + window discovery
├── focus.py            # Window focus/jump (protocol handler)
├── boost.py            # Background performance daemon
├── setup_hooks.py      # Hook installer + diagnostics
├── README.md           # This file
└── LICENSE             # MIT
```

## License

MIT — do whatever you want with it.

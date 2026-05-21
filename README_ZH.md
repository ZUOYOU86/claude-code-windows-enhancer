# Claude Code Windows Enhancer

Claude Code Windows 桌面伴侣工具 —— **桌面通知 + 一键跳转 + 后台提速 + 多实例隔离**。零第三方依赖，纯 Python 标准库 + Win32 API。

## 功能

| 功能 | 文件 | 说明 |
|---|---|---|
| 桌面通知 | `notify.py` | Claude 完成任务/需要确认时弹出 Windows 原生 toast + 提示音 |
| 窗口跳转 | `focus.py` | 点击通知 → Claude 终端自动置顶（三级 Win32 抢焦点） |
| 后台提速 | `boost.py` | 守护进程持续禁用 Windows 降频/节流/效率模式 |
| 一键安装 | `setup_hooks.py` | 自动配置 Claude Code Hook，无需手动操作 |

## 快速开始

```powershell
# 一键安装
powershell -ExecutionPolicy Bypass -File install.ps1

# 或逐步安装：
python notify.py --setup
python notify.py --check
python setup_hooks.py install
python setup_hooks.py test
```

## 工作原理

### 通知流程

```
Claude Code Hook 触发
  → notify.py <event>
    → 进程树枚举发现终端窗口
    → 发送 WinRT toast（scenario="reminder"，突破 Focus Assist）
    → 播放系统提示音 / 自定义 WAV
```

### 跳转流程（点击通知）

```
点击 toast
  → claude-notify:// 协议
  → pythonw.exe focus.py（GUI 子系统，有前台权限）
  → 三级抢焦点：
     1. SwitchToThisWindow（Windows Alt+Tab API）
     2. AttachThreadInput + SendInput(Alt) + SetForegroundWindow
     3. LockSetForegroundWindow + TopMost 暴力置顶
  → GetForegroundWindow() 验证成功
```

### 提速流程（后台守护）

```
首条用户消息 → UserPromptSubmit Hook → 启动 boost.py --daemon
  → 每 30 秒自动施加 5 项优化：
    ✅ 进程优先级 → HIGH
    ✅ 电源节流 → OFF
    ✅ 效率模式 → OFF（Win11 EcoQoS）
    ✅ 内存优先级 → 5（不回收物理内存）
    ✅ 所有线程 → ABOVE_NORMAL
  → Claude 退出 → 守护自动停止
```

## 多实例自动隔离

**完全自动**。每个 Claude 窗口用 **项目目录 + 终端 Shell PID** 做唯一标识。首条消息自动抓取前台窗口 HWND，之后所有通知精准跳回，互不干扰。同目录多开也能自动区分（Shell PID 不同）。

```
窗口 A（D:\project-frontend）→ 自动 session = D_project_frontend_29048
窗口 B（D:\project-backend） → 自动 session = D_project_backend_12345
```

首条消息时自动抓取各自的前台窗口 HWND，之后所有通知精准跳回，互不干扰。

同目录多开也能自动区分（Shell PID 不同）。如需手动指定：

```powershell
# 窗口 A
python setup_hooks.py install --session frontend

# 窗口 B
python setup_hooks.py install --session backend
```

## 自定义

### 自定义声音

编辑 `notify.py`，把 `.wav` 文件放入项目目录：

```python
_CUSTOM_SOUNDS = {
    "Stop": os.path.join(_PROJECT_DIR, "task_done.wav"),
}
```

### 自定义通知文案

```python
MESSAGES = {
    "Stop": ("自定义标题", "自定义内容"),
}
```

## 命令参考

```powershell
# 一键安装
powershell -ExecutionPolicy Bypass -File install.ps1

# 通知（手动测试）
python notify.py Stop                    # 响应完成
python notify.py PermissionRequest       # 权限申请
python notify.py Elicitation             # 需要交互
python notify.py TaskCompleted           # 任务完成

# 维护
python notify.py --check                 # 5 项完整性诊断
python notify.py --setup                 # 重新初始化
python setup_hooks.py install            # 安装 Hook
python setup_hooks.py uninstall          # 卸载 Hook
python setup_hooks.py status             # 查看状态
python setup_hooks.py test               # 模拟全部 4 种通知
python boost.py                          # 单次提速
python boost.py --daemon                 # 后台持续守护
```

## Hook 事件

| Hook | 触发时机 | 行为 |
|---|---|---|
| `UserPromptSubmit` | 首次发消息 | 抓窗口 HWND + 启动 boost 守护 |
| `Stop` | Claude 完成回答 | toast "响应完成" |
| `PermissionRequest` | 需要权限批准 | toast "权限申请" |
| `Elicitation` | 等待输入/选择 | toast "需要交互" |
| `TaskCompleted` | 子任务完成 | toast "任务完成" |

## 环境要求

- Windows 10/11
- Python 3.8+（仅标准库）
- Claude Code（支持 Hook 的版本）

## 项目结构

```
├── install.ps1         # 一键安装脚本
├── notify.py           # 通知触发：toast + 声音 + 窗口发现
├── focus.py            # 窗口跳转（协议处理器）
├── boost.py            # 后台提速守护
├── setup_hooks.py      # Hook 安装 + 诊断
├── README.md           # 英文说明
├── README_ZH.md        # 中文说明（本文件）
└── LICENSE             # MIT
```

## License

MIT

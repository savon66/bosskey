#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
老板键 BossKey
一键隐藏 / 最小化指定程序（按 exe 名称匹配），再按一次恢复。
纯 Windows API + tkinter 实现，无需任何额外运行库。
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import sys
import threading
import tkinter as tk
import traceback
import winreg
from tkinter import filedialog, messagebox, ttk

APP_NAME = "BossKey"
APP_TITLE = "老板键"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LOG_PATH = os.path.join(CONFIG_DIR, "error.log")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

DEFAULT_CONFIG = {
    "targets": [],
    "mods": ["ctrl", "alt"],
    "key": "Q",
    "mode": "hide",
    "autostart": False,
}

# ---------------------------------------------------------------- Win32 常量
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
except OSError:  # pragma: no cover
    dwmapi = None

SW_HIDE = 0
SW_SHOWMINIMIZED = 2
SW_SHOW = 5
SW_MINIMIZE = 6
SW_RESTORE = 9

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_APP = 0x8000
MSG_HOTKEY_ID = 0xB055

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DWMWA_CLOAKED = 14
ERROR_ALREADY_EXISTS = 183

HWND = wt.HWND
EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, HWND, wt.LPARAM)

user32.EnumWindows.argtypes = [EnumWindowsProc, wt.LPARAM]
user32.IsWindowVisible.argtypes = [HWND]
user32.IsWindow.argtypes = [HWND]
user32.IsIconic.argtypes = [HWND]
user32.GetWindowTextW.argtypes = [HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [HWND]
user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wt.DWORD)]
user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [HWND]
user32.GetWindowLongW.argtypes = [HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.RegisterHotKey.argtypes = [HWND, ctypes.c_int, wt.UINT, wt.UINT]
user32.RegisterHotKey.restype = wt.BOOL
user32.UnregisterHotKey.argtypes = [HWND, ctypes.c_int]
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), HWND, wt.UINT, wt.UINT]

kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)
]
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.GetCurrentThreadId.restype = wt.DWORD
kernel32.GetCurrentProcessId.restype = wt.DWORD
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE

if dwmapi:
    dwmapi.DwmGetWindowAttribute.argtypes = [
        HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD
    ]

MOD_KEYS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}
MOD_LABELS = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}

KEY_VK = {}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    KEY_VK[_c] = ord(_c)
for _i in range(1, 13):
    KEY_VK["F%d" % _i] = 0x6F + _i
KEY_VK.update({
    "Space": 0x20, "Tab": 0x09, "Insert": 0x2D, "Delete": 0x2E,
    "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22,
    "Pause": 0x13, "ScrollLock": 0x91, "`": 0xC0, "-": 0xBD, "=": 0xBB,
    "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF,
})
KEY_CHOICES = (
    list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + list("0123456789")
    + ["F%d" % i for i in range(1, 13)]
    + ["Space", "Tab", "Insert", "Delete", "Home", "End", "PageUp", "PageDown",
       "Pause", "ScrollLock", "`", "-", "=", "[", "]", "\\", ";", "'", ",", ".", "/"]
)

# ---------------------------------------------------------------- 基础工具


def log_error(exc_text):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(exc_text + "\n")
        if os.path.getsize(LOG_PATH) > 200 * 1024:
            with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
                keep = f.readlines()[-200:]
            with open(LOG_PATH, "w", encoding="utf-8") as f:
                f.writelines(keep)
    except Exception:
        pass


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k in DEFAULT_CONFIG:
                if k in data:
                    cfg[k] = data[k]
    except (OSError, ValueError):
        pass
    cfg["targets"] = [str(t).lower() for t in cfg.get("targets", []) if str(t).strip()]
    cfg["mods"] = [m for m in cfg.get("mods", []) if m in MOD_KEYS]
    if cfg.get("key") not in KEY_VK:
        cfg["key"] = "Q"
    if cfg.get("mode") not in ("hide", "minimize"):
        cfg["mode"] = "hide"
    return cfg


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except OSError as exc:
        messagebox.showerror(APP_TITLE, "配置保存失败：%s" % exc)
        return False


def exe_of_pid(pid):
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(handle)
    return ""


def is_cloaked(hwnd):
    if not dwmapi:
        return False
    val = wt.DWORD(0)
    try:
        if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED,
                                        ctypes.byref(val), ctypes.sizeof(val)) != 0:
            return False
    except Exception:
        return False
    return val.value != 0


def window_title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def enum_top_windows(only_visible=True, exclude_pid=None):
    """返回 [(hwnd, exe, title)]"""
    out = []
    own = kernel32.GetCurrentProcessId()

    def _cb(hwnd, _lparam):
        try:
            if exclude_pid is None and own == _pid_of(hwnd):
                return True
            if only_visible and not user32.IsWindowVisible(hwnd):
                return True
            if exclude_pid and _pid_of(hwnd) == exclude_pid:
                return True
            title = window_title(hwnd)
            if not title:
                return True
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if ex_style & WS_EX_TOOLWINDOW:
                return True
            if is_cloaked(hwnd):
                return True
            exe = exe_of_pid(_pid_of(hwnd))
            if not exe:
                return True
            out.append((hwnd, exe, title))
        except Exception:
            pass
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return out


def _pid_of(hwnd):
    pid = wt.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def find_target_windows(names):
    names = {n.lower() for n in names}
    if not names:
        return []
    return [w for w in enum_top_windows() if w[1].lower() in names]


# ---------------------------------------------------------------- 隐藏引擎
class BossKeyEngine:
    def __init__(self):
        self.targets = []
        self.mode = "hide"
        self._touched = []  # [(hwnd, exe, title)]

    def configure(self, targets, mode):
        self.targets = list(targets)
        self.mode = mode

    def _still_hidden(self):
        alive = []
        for hwnd, exe, title in self._touched:
            if not user32.IsWindow(hwnd):
                continue
            if self.mode == "hide":
                if not user32.IsWindowVisible(hwnd):
                    alive.append((hwnd, exe, title))
            else:
                if user32.IsIconic(hwnd):
                    alive.append((hwnd, exe, title))
        self._touched = alive
        return alive

    def hide_all(self):
        wins = find_target_windows(self.targets)
        acted = []
        for hwnd, exe, title in wins:
            if self.mode == "hide":
                if not user32.IsWindowVisible(hwnd):
                    continue
                user32.ShowWindow(hwnd, SW_HIDE)
            else:
                if user32.IsIconic(hwnd):
                    continue
                user32.ShowWindow(hwnd, SW_MINIMIZE)
            acted.append((hwnd, exe, title))
        self._touched = acted
        if not acted:
            return False, "没有找到需要处理的目标窗口"
        names = sorted({a[1] for a in acted})
        return True, "已处理 %d 个窗口：%s" % (len(acted), "、".join(names))

    def restore_all(self):
        alive = self._still_hidden()
        if not alive:
            return False, "没有被隐藏的窗口"
        count = 0
        for hwnd, exe, title in alive:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
            else:
                user32.ShowWindow(hwnd, SW_SHOW)
            count += 1
        self._touched = []
        if count:
            try:
                user32.SetForegroundWindow(alive[0][0])
            except Exception:
                pass
        return True, "已恢复 %d 个窗口" % count

    def toggle(self):
        if self._still_hidden():
            return self.restore_all()
        return self.hide_all()


# ---------------------------------------------------------------- 全局热键线程
class HotkeyThread(threading.Thread):
    """独占线程跑消息循环，接收 WM_HOTKEY。hWnd 为 NULL 时热键归属该线程。"""

    def __init__(self):
        super().__init__(daemon=True, name="hotkey")
        self._tid = None
        self._lock = threading.Lock()
        self._pending = None
        self._registered = None
        self.on_hotkey = None
        self.on_status = None  # (ok: bool, msg: str)

    def set_hotkey(self, mods, vk):
        with self._lock:
            self._pending = (mods, vk)
        tid = self._tid
        if tid:
            user32.PostThreadMessageW(tid, WM_APP + 1, 0, 0)

    def _apply(self, mods, vk):
        ok = bool(user32.RegisterHotKey(None, MSG_HOTKEY_ID, mods | MOD_NOREPEAT, vk))
        if ok:
            self._registered = (mods, vk)
        if self.on_status:
            self.on_status(ok, "热键已生效" if ok else "热键注册失败，可能被其他程序占用")
        return ok

    def run(self):
        self._tid = kernel32.GetCurrentThreadId()
        with self._lock:
            pending = self._pending
        registered = None
        if pending:
            registered = pending
            self._apply(*pending)
        msg = wt.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):
                break
            if msg.message == WM_HOTKEY:
                if self.on_hotkey:
                    try:
                        self.on_hotkey()
                    except Exception:
                        log_error(traceback.format_exc())
            elif msg.message == WM_APP + 1:
                with self._lock:
                    pending = self._pending
                if pending and pending != registered:
                    if registered:
                        user32.UnregisterHotKey(None, MSG_HOTKEY_ID)
                    registered = pending if self._apply(*pending) else None
        if registered:
            user32.UnregisterHotKey(None, MSG_HOTKEY_ID)

    def shutdown(self):
        tid = self._tid
        if tid:
            user32.PostThreadMessageW(tid, 0x0012, 0, 0)  # WM_QUIT


# ---------------------------------------------------------------- 界面
class App:
    def __init__(self, root, start_minimized=False):
        self.root = root
        self.cfg = load_config()
        self.engine = BossKeyEngine()
        self.engine.configure(self.cfg["targets"], self.cfg["mode"])
        self.tray = None
        self._quitting = False
        self._first_close = True
        self._queue = queue.Queue()
        self._build_style()
        self._build_ui()
        self._load_to_ui()
        self._start_hotkey()
        self._init_tray()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._pump()
        if start_minimized:
            self.root.after(150, self.hide_to_tray)
        else:
            self.root.after(300, lambda: self.set_status(
                "待命中 · 按 %s 一键隐藏/恢复" % self.hotkey_text(), True))

    # ------------------------------------------------------------ 外观
    def _build_style(self):
        self.root.title(APP_TITLE)
        self.root.configure(bg="#f4f6fa")
        self.root.minsize(560, 470)
        try:
            self.root.iconbitmap(default=self._resource("bosskey.ico"))
        except Exception:
            pass
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        base_font = ("Microsoft YaHei UI", 10)
        self.root.option_add("*Font", base_font)
        style.configure(".", font=base_font, background="#f4f6fa", foreground="#1f2430")
        style.configure("TFrame", background="#f4f6fa")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("TLabel", background="#f4f6fa", foreground="#1f2430")
        style.configure("Card.TLabel", background="#ffffff")
        style.configure("Hint.TLabel", foreground="#7c8496", background="#f4f6fa")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 15, "bold"),
                        background="#f4f6fa", foreground="#141824")
        style.configure("TButton", padding=(12, 6), background="#ffffff",
                        borderwidth=1, focusthickness=0)
        style.map("TButton", background=[("active", "#eef2fb")])
        style.configure("Accent.TButton", background="#2b6cf6", foreground="#ffffff",
                        borderwidth=0, padding=(16, 7))
        style.map("Accent.TButton",
                  background=[("active", "#1f5be0"), ("pressed", "#1a4fc7")],
                  foreground=[("disabled", "#dddddd")])
        style.configure("TCheckbutton", background="#f4f6fa")
        style.configure("Card.TCheckbutton", background="#ffffff")
        style.configure("TRadiobutton", background="#f4f6fa")
        style.configure("TLabelframe", background="#f4f6fa", borderwidth=1,
                        relief="solid", bordercolor="#e2e6ee")
        style.configure("TLabelframe.Label", background="#f4f6fa",
                        foreground="#5a6377", font=("Microsoft YaHei UI", 9))
        style.configure("TCombobox", padding=4)
        style.configure("Status.TLabel", background="#eef1f7", foreground="#4a5468",
                        padding=(10, 6))
        style.configure("Treeview", rowheight=24, background="#ffffff",
                        fieldbackground="#ffffff", borderwidth=0)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))

    def _resource(self, name):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, name)

    # ------------------------------------------------------------ 布局
    def _build_ui(self):
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        head = ttk.Frame(root, padding=(18, 14, 18, 4))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="老板键", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.hk_hint = ttk.Label(head, text="", style="Hint.TLabel")
        self.hk_hint.grid(row=1, column=0, sticky="w", pady=(2, 0))

        body = ttk.Frame(root, padding=(18, 8, 18, 8))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        # --- 目标程序
        box = ttk.LabelFrame(body, text=" 目标程序（按 exe 名称匹配，可添加多项） ",
                             padding=(12, 10, 12, 12))
        box.grid(row=0, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)

        list_wrap = tk.Frame(box, bg="#ffffff", highlightthickness=1,
                             highlightbackground="#e2e6ee")
        list_wrap.grid(row=0, column=0, sticky="nsew")
        list_wrap.columnconfigure(0, weight=1)
        list_wrap.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(
            list_wrap, activestyle="none", borderwidth=0, highlightthickness=0,
            selectbackground="#dbe6ff", selectforeground="#141824",
            background="#ffffff", foreground="#1f2430",
            font=("Consolas", 10), selectmode="extended",
        )
        self.listbox.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        sb = ttk.Scrollbar(list_wrap, orient="vertical", command=self.listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.bind("<Delete>", lambda e: self.remove_target())

        self.placeholder = tk.Label(
            list_wrap, justify="center", bg="#ffffff", fg="#9aa3b5",
            font=("Microsoft YaHei UI", 9),
            text="还没有添加任何程序\n\n"
                 "点右侧「从运行窗口选择」，挑一个正在运行的程序；\n"
                 "或「浏览 exe 文件」直接选安装目录里的 exe。\n\n"
                 "添加后按 Ctrl+Alt+Q 就能一键隐藏它。")
        self.placeholder.bind("<Button-1>", lambda e: self.pick_running())

        btns = ttk.Frame(box)
        btns.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        ttk.Button(btns, text="从运行窗口选择", command=self.pick_running).pack(fill="x")
        ttk.Button(btns, text="浏览 exe 文件…", command=self.browse_exe).pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="手动输入名称…", command=self.manual_add).pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="移除选中", command=self.remove_target).pack(fill="x", pady=(6, 0))

        # --- 快捷键 + 模式
        opt = ttk.LabelFrame(body, text=" 快捷键与动作 ", padding=(12, 10, 12, 12))
        opt.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        opt.columnconfigure(5, weight=1)

        ttk.Label(opt, text="组合键").grid(row=0, column=0, sticky="w")
        self.mod_vars = {}
        col = 1
        for key in ("ctrl", "alt", "shift", "win"):
            var = tk.BooleanVar(value=key in self.cfg["mods"])
            self.mod_vars[key] = var
            ttk.Checkbutton(opt, text=MOD_LABELS[key], variable=var,
                            command=self.refresh_hotkey_hint).grid(row=0, column=col,
                                                                   sticky="w", padx=(8, 0))
            col += 1
        ttk.Label(opt, text="+").grid(row=0, column=col, padx=(6, 6))
        self.key_var = tk.StringVar(value=self.cfg["key"])
        self.key_box = ttk.Combobox(opt, textvariable=self.key_var, values=KEY_CHOICES,
                                    width=10, state="readonly")
        self.key_box.grid(row=0, column=col + 1, sticky="w")
        self.key_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_hotkey_hint())
        self.hk_preview = ttk.Label(opt, text="", foreground="#2b6cf6",
                                    font=("Consolas", 11, "bold"))
        self.hk_preview.grid(row=0, column=col + 2, sticky="w", padx=(12, 0))

        mode_row = ttk.Frame(opt)
        mode_row.grid(row=1, column=0, columnspan=8, sticky="w", pady=(10, 0))
        ttk.Label(mode_row, text="动作").pack(side="left")
        self.mode_var = tk.StringVar(value=self.cfg["mode"])
        ttk.Radiobutton(mode_row, text="完全隐藏（任务栏也消失）", value="hide",
                        variable=self.mode_var).pack(side="left", padx=(10, 0))
        ttk.Radiobutton(mode_row, text="仅最小化到任务栏", value="minimize",
                        variable=self.mode_var).pack(side="left", padx=(12, 0))

        self.autostart_var = tk.BooleanVar(value=bool(self.cfg.get("autostart")))
        ttk.Checkbutton(mode_row, text="开机自启", variable=self.autostart_var,
                        command=self.on_autostart_toggle).pack(side="left", padx=(20, 0))

        # --- 底部操作区
        foot = ttk.Frame(root, padding=(18, 0, 18, 10))
        foot.grid(row=2, column=0, sticky="ew")
        foot.columnconfigure(2, weight=1)
        ttk.Button(foot, text="保存并应用", style="Accent.TButton",
                   command=self.apply).grid(row=0, column=0, sticky="w")
        ttk.Button(foot, text="立即执行", command=self.run_now).grid(row=0, column=1,
                                                                 sticky="w", padx=(8, 0))
        ttk.Button(foot, text="退出", command=self.quit_app).grid(row=0, column=3, sticky="e")

        self.status = ttk.Label(root, text="", style="Status.TLabel", anchor="w")
        self.status.grid(row=3, column=0, sticky="ew")

        self.refresh_hotkey_hint()

    # ------------------------------------------------------------ 状态
    def _load_to_ui(self):
        self.listbox.delete(0, "end")
        for t in self.cfg["targets"]:
            self.listbox.insert("end", t)
        self._update_hk_hint_label()
        self._refresh_placeholder()

    def _refresh_placeholder(self):
        if self.listbox.size() == 0:
            self.placeholder.configure(text=(
                "还没有添加任何程序\n\n"
                "点右侧「从运行窗口选择」，挑一个正在运行的程序；\n"
                "或「浏览 exe 文件」直接选安装目录里的 exe。\n\n"
                "添加后按 %s 就能一键隐藏它。" % self.hotkey_text()))
            self.placeholder.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self.placeholder.place_forget()

    def current_targets(self):
        return [self.listbox.get(i).strip().lower()
                for i in range(self.listbox.size()) if self.listbox.get(i).strip()]

    def hotkey_text(self):
        mods = [MOD_LABELS[m] for m in ("ctrl", "alt", "shift", "win")
                if self.mod_vars[m].get()]
        return "+".join(mods + [self.key_var.get()])

    def refresh_hotkey_hint(self):
        self.hk_preview.configure(text=self.hotkey_text())
        self._update_hk_hint_label()
        if hasattr(self, "placeholder"):
            self._refresh_placeholder()

    def _update_hk_hint_label(self):
        self.hk_hint.configure(text="全局快捷键：%s   ·   一键隐藏 / 再按恢复" % self.hotkey_text())

    def set_status(self, text, ok=True):
        self.status.configure(text="  " + text,
                              foreground="#1a7a45" if ok else "#b42318",
                              background="#eaf6ef" if ok else "#fdeceb")

    def ui(self, fn):
        """把后台线程（热键线程 / 托盘线程）的回调丢回主线程执行。"""
        self._queue.put(fn)

    def _pump(self):
        try:
            while True:
                fn = self._queue.get_nowait()
                try:
                    fn()
                except Exception:
                    log_error(traceback.format_exc())
        except queue.Empty:
            pass
        self.root.after(60, self._pump)

    # ------------------------------------------------------------ 目标管理
    def pick_running(self):
        wins = enum_top_windows()
        if not wins:
            messagebox.showinfo(APP_TITLE, "没有检测到可见窗口")
            return
        seen = {}
        for hwnd, exe, title in wins:
            seen.setdefault(exe.lower(), (exe, title))
        dlg = tk.Toplevel(self.root)
        dlg.title("从运行中的窗口选择程序")
        dlg.configure(bg="#f4f6fa")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("620x430")
        dlg.columnconfigure(0, weight=1)
        dlg.rowconfigure(0, weight=1)

        frame = ttk.Frame(dlg, padding=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tv = ttk.Treeview(frame, columns=("exe", "title"), show="headings",
                          selectmode="extended")
        tv.heading("exe", text="程序")
        tv.heading("title", text="窗口标题")
        tv.column("exe", width=170, anchor="w")
        tv.column("title", width=400, anchor="w")
        tv.grid(row=0, column=0, sticky="nsew")
        sbar = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
        sbar.grid(row=0, column=1, sticky="ns")
        tv.configure(yscrollcommand=sbar.set)
        for exe, title in sorted(seen.values(), key=lambda x: x[0].lower()):
            tv.insert("", "end", values=(exe, title[:90]))

        bar = ttk.Frame(dlg, padding=(10, 0, 10, 10))
        bar.grid(row=1, column=0, sticky="ew")

        def add_selected():
            items = tv.selection()
            if not items:
                return
            existing = set(self.current_targets())
            for iid in items:
                exe = str(tv.item(iid, "values")[0]).lower()
                if exe and exe not in existing:
                    self.listbox.insert("end", exe)
                    existing.add(exe)
            dlg.destroy()
            self._refresh_placeholder()
            self.set_status("已添加目标，记得点击「保存并应用」")

        ttk.Button(bar, text="添加选中", style="Accent.TButton",
                   command=add_selected).pack(side="left")
        ttk.Button(bar, text="取消", command=dlg.destroy).pack(side="right")
        tv.bind("<Double-1>", lambda e: add_selected())

    def browse_exe(self):
        paths = filedialog.askopenfilenames(
            parent=self.root, title="选择要隐藏的程序",
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")])
        existing = set(self.current_targets())
        added = 0
        for p in paths:
            name = os.path.basename(p).lower()
            if name and name not in existing:
                self.listbox.insert("end", name)
                existing.add(name)
                added += 1
        if added:
            self._refresh_placeholder()
            self.set_status("已添加 %d 个程序，记得点击「保存并应用」" % added)

    def manual_add(self):
        win = tk.Toplevel(self.root)
        win.title("手动输入")
        win.configure(bg="#f4f6fa")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)
        ttk.Label(win, text="输入 exe 名称，例如 chrome.exe").pack(padx=16, pady=(16, 6), anchor="w")
        var = tk.StringVar()
        ent = ttk.Entry(win, textvariable=var, width=34)
        ent.pack(padx=16)
        ent.focus_set()

        def ok(_=None):
            name = var.get().strip().lower()
            if not name:
                return
            if not name.endswith(".exe"):
                name += ".exe"
            if name not in self.current_targets():
                self.listbox.insert("end", name)
            win.destroy()
            self._refresh_placeholder()
            self.set_status("已添加，记得点击「保存并应用」")

        bar = ttk.Frame(win)
        bar.pack(padx=16, pady=12, fill="x")
        ttk.Button(bar, text="确定", style="Accent.TButton", command=ok).pack(side="right")
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="right", padx=(0, 8))
        ent.bind("<Return>", ok)

    def remove_target(self):
        for i in reversed(self.listbox.curselection()):
            self.listbox.delete(i)
        self._refresh_placeholder()
        self.set_status("已移除，记得点击「保存并应用」")

    # ------------------------------------------------------------ 动作
    def apply(self):
        targets = self.current_targets()
        if not targets:
            if not messagebox.askyesno(APP_TITLE, "还没有添加任何目标程序，仍然保存吗？"):
                return
        mods = [m for m in ("ctrl", "alt", "shift", "win") if self.mod_vars[m].get()]
        if not mods:
            if not messagebox.askyesno(
                    APP_TITLE, "没有选择 Ctrl/Alt/Shift/Win 修饰键，单独一个键很容易在日常生活中被误触，仍要继续？"):
                return
        self.cfg["targets"] = targets
        self.cfg["mods"] = mods
        self.cfg["key"] = self.key_var.get()
        self.cfg["mode"] = self.mode_var.get()
        self.cfg["autostart"] = bool(self.autostart_var.get())
        save_config(self.cfg)
        self.engine.configure(targets, self.cfg["mode"])
        self._register_hotkey()
        self._update_hk_hint_label()
        self.set_status("已保存并应用 · 快捷键 %s" % self.hotkey_text(), True)

    def _register_hotkey(self):
        mods = 0
        for m in self.cfg["mods"]:
            mods |= MOD_KEYS[m]
        vk = KEY_VK.get(self.cfg["key"], ord("Q"))
        self.hk.set_hotkey(mods, vk)

    def _start_hotkey(self):
        self.hk = HotkeyThread()
        self.hk.on_hotkey = lambda: self.ui(self.toggle)
        self.hk.on_status = lambda ok, msg: self.ui(lambda: self._on_hotkey_status(ok, msg))
        self.hk.start()
        self._register_hotkey()

    def _on_hotkey_status(self, ok, msg):
        if ok:
            self.set_status("热键 %s 已生效，窗口可以直接关掉，我会待在托盘里" % self.hotkey_text(), True)
        else:
            self.set_status(msg + "（换一个组合键再试）", False)

    def toggle(self):
        ok, msg = self.engine.toggle()
        self.set_status(msg, ok)
        if self.tray:
            self.tray.update_menu()

    def run_now(self):
        ok, msg = self.engine.toggle()
        self.set_status(msg, ok)

    def on_autostart_toggle(self):
        self._set_autostart(bool(self.autostart_var.get()))

    def _launch_cmd(self):
        if getattr(sys, "frozen", False):
            return '"%s" --minimized' % sys.executable
        return '"%s" "%s" --minimized' % (sys.executable, os.path.abspath(__file__))

    def _set_autostart(self, enable):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
                if enable:
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, self._launch_cmd())
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                    except FileNotFoundError:
                        pass
            self.cfg["autostart"] = enable
            save_config(self.cfg)
            self.set_status("已开启开机自启" if enable else "已关闭开机自启", True)
        except OSError as exc:
            self.autostart_var.set(not enable)
            self.set_status("开机自启设置失败：%s" % exc, False)

    # ------------------------------------------------------------ 托盘
    def _init_tray(self):
        try:
            import pystray
            from pystray import Menu, MenuItem
        except Exception:
            self.tray = None
            return
        image = make_tray_image()
        menu = Menu(
            MenuItem("显示主界面", lambda *a: self.ui(self.show_window), default=True),
            MenuItem("立即隐藏", lambda *a: self.ui(self.engine_hide)),
            MenuItem("恢复窗口", lambda *a: self.ui(self.engine_restore)),
            Menu.SEPARATOR,
            MenuItem("退出", lambda *a: self.ui(self.quit_app)),
        )
        try:
            self.tray = pystray.Icon(APP_NAME, image, APP_TITLE, menu)
            self.tray.run_detached()
        except Exception:
            log_error(traceback.format_exc())
            self.tray = None

    def engine_hide(self):
        ok, msg = self.engine.hide_all()
        self.set_status(msg, ok)

    def engine_restore(self):
        ok, msg = self.engine.restore_all()
        self.set_status(msg, ok)

    def hide_to_tray(self):
        if self.tray:
            self.root.withdraw()
        else:
            self.root.iconify()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass

    def on_close(self):
        if self.tray:
            self.hide_to_tray()
            if self._first_close:
                self._first_close = False
                try:
                    self.tray.notify(
                        "程序仍在后台运行，按 %s 隐藏/恢复窗口。右键托盘图标可退出。"
                        % self.hotkey_text(), APP_TITLE)
                except Exception:
                    pass
                self.set_status(
                    "窗口已收起，程序仍在后台运行（托盘图标可能在 ^ 溢出区里）；右键可退出", True)
        else:
            self.quit_app()

    def quit_app(self):
        if self._quitting:
            return
        self._quitting = True
        try:
            self.engine.restore_all()
        except Exception:
            pass
        try:
            self.hk.shutdown()
        except Exception:
            pass
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()


def make_tray_image():
    from PIL import Image, ImageDraw
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, size - 3, size - 3], radius=15, fill=(43, 108, 246, 255))
    # 挂锁：锁梁 + 锁体
    d.arc([20, 14, 44, 42], start=180, end=360, fill=(255, 255, 255, 255), width=6)
    d.rounded_rectangle([15, 32, 49, 55], radius=7, fill=(255, 255, 255, 255))
    d.ellipse([28, 38, 36, 46], fill=(43, 108, 246, 255))
    d.rectangle([30, 43, 34, 50], fill=(43, 108, 246, 255))
    return img


def make_icon_file(path):
    from PIL import Image, ImageDraw
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    d.rounded_rectangle([8, 8, 248, 248], radius=60, fill=(43, 108, 246, 255))
    d.arc([80, 56, 176, 168], start=180, end=360, fill=(255, 255, 255, 255), width=24)
    d.rounded_rectangle([60, 128, 196, 220], radius=28, fill=(255, 255, 255, 255))
    d.ellipse([112, 152, 144, 184], fill=(43, 108, 246, 255))
    d.rectangle([120, 172, 136, 200], fill=(43, 108, 246, 255))
    base.save(path, format="ICO", sizes=[(s, s) for s in sizes])


# ---------------------------------------------------------------- 入口
def single_instance_guard():
    handle = kernel32.CreateMutexW(None, False, "Local\\BossKey_SingleInstance")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS or not handle:
        return None
    return handle


def main():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if sys.platform != "win32":
        raise SystemExit("This tool runs on Windows only.")
    guard = single_instance_guard()
    start_min = "--minimized" in sys.argv
    if guard is None:
        if not start_min:
            r = tk.Tk()
            r.withdraw()
            messagebox.showinfo(APP_TITLE, "老板键已经在运行了，请查看右下角托盘图标。")
            r.destroy()
        return

    root = tk.Tk()
    app = App(root, start_minimized=start_min)
    root.geometry("640x520")
    root.update_idletasks()
    w, h = 640, 520
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 3
    root.geometry("%dx%d+%d+%d" % (w, h, x, y))
    try:
        root.mainloop()
    except Exception:
        log_error(traceback.format_exc())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error(traceback.format_exc())
        raise

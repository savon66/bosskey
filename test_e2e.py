# -*- coding: utf-8 -*-
"""端到端测试：真实按下 Ctrl+Alt+Q，验证 exe 是否隐藏/恢复目标窗口"""
import ctypes
import json
import os
import subprocess
import sys
import time

import bosskey

CFG = bosskey.CONFIG_PATH
VICTIM_CODE = (
    "import tkinter as tk\n"
    "r = tk.Tk()\n"
    "r.title('VICTIM_TEST_WINDOW')\n"
    "r.geometry('420x260+300+200')\n"
    "r.mainloop()\n"
)
EXE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "老板键.exe")
user32 = ctypes.WinDLL("user32")


def press_hotkey():
    VK_CONTROL, VK_MENU, VK_Q, UP = 0x11, 0x12, 0x51, 0x0002
    for vk in (VK_CONTROL, VK_MENU, VK_Q):
        user32.keybd_event(vk, 0, 0, 0)
    for vk in (VK_Q, VK_MENU, VK_CONTROL):
        user32.keybd_event(vk, 0, UP, 0)


def victim_visible():
    for _hwnd, _exe, title in bosskey.enum_top_windows():
        if "VICTIM_TEST_WINDOW" in title:
            return True
    return False


def wait_victim(expect, timeout=4.0):
    end = time.time() + timeout
    while time.time() < end:
        if victim_visible() == expect:
            return True
        time.sleep(0.15)
    return victim_visible() == expect


def main():
    os.makedirs(bosskey.CONFIG_DIR, exist_ok=True)
    backup = None
    if os.path.exists(CFG):
        with open(CFG, "r", encoding="utf-8") as f:
            backup = f.read()
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump({"targets": ["python.exe"], "mods": ["ctrl", "alt"],
                   "key": "Q", "mode": "hide", "autostart": False}, f)

    victim = subprocess.Popen([sys.executable, "-c", VICTIM_CODE])
    proc = subprocess.Popen([EXE])
    results = []
    try:
        assert wait_victim(True), "目标窗口未出现"
        print("1) 启动完成，目标窗口可见: True")
        time.sleep(3.5)

        press_hotkey()
        ok = wait_victim(False)
        results.append(ok)
        print("2) 按下 Ctrl+Alt+Q -> 窗口已隐藏:", ok)

        time.sleep(1.2)
        press_hotkey()
        ok2 = wait_victim(True)
        results.append(ok2)
        print("3) 再按一次      -> 窗口已恢复:", ok2)

        print("全部通过:", all(results))
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        victim.terminate()
        time.sleep(0.6)
        if backup is not None:
            with open(CFG, "w", encoding="utf-8") as f:
                f.write(backup)
        else:
            try:
                os.remove(CFG)
            except OSError:
                pass


if __name__ == "__main__":
    main()

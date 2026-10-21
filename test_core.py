# -*- coding: utf-8 -*-
"""核心逻辑自测：枚举窗口 / 隐藏 / 恢复 / 热键注册"""
import subprocess
import sys
import time
import tkinter as tk

import bosskey

VICTIM_CODE = (
    "import tkinter as tk\n"
    "r = tk.Tk()\n"
    "r.title('VICTIM_TEST_WINDOW')\n"
    "r.geometry('320x200')\n"
    "r.mainloop()\n"
)

def visible_titles():
    return [w[2] for w in bosskey.enum_top_windows()]

def main():
    victim = subprocess.Popen([sys.executable, "-c", VICTIM_CODE])
    ok = False
    try:
        for _ in range(50):
            if any("VICTIM_TEST_WINDOW" in t for t in visible_titles()):
                ok = True
                break
            time.sleep(0.2)
        print("1) 目标窗口已出现:", ok)
        assert ok, "victim window not found"

        eng = bosskey.BossKeyEngine()
        eng.configure(["python.exe"], "hide")

        print("2) hide_all ->", eng.hide_all())
        time.sleep(0.3)
        print("   窗口可见:", any("VICTIM_TEST_WINDOW" in t for t in visible_titles()))

        print("3) toggle(应恢复) ->", eng.toggle())
        time.sleep(0.4)
        print("   窗口可见:", any("VICTIM_TEST_WINDOW" in t for t in visible_titles()))

        print("4) toggle(应隐藏) ->", eng.toggle())
        time.sleep(0.3)
        print("   窗口可见:", any("VICTIM_TEST_WINDOW" in t for t in visible_titles()))

        eng.restore_all()
        time.sleep(0.3)
        print("5) 最终恢复后可见:", any("VICTIM_TEST_WINDOW" in t for t in visible_titles()))

        # 热键注册
        hk = bosskey.HotkeyThread()
        result = {}
        hk.on_status = lambda o, m: result.update(ok=o, msg=m)
        hk.start()
        hk.set_hotkey(bosskey.MOD_CONTROL | bosskey.MOD_ALT, ord("Q"))
        time.sleep(1.0)
        print("6) 热键注册 Ctrl+Alt+Q ->", result)
        hk.shutdown()
        time.sleep(0.3)
    finally:
        victim.terminate()
    print("ALL DONE")

if __name__ == "__main__":
    main()

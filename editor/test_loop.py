# -*- coding: utf-8 -*-
"""loop 属性面板与帧延时联动自检。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import canvas_designer as D  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  OK   " if cond else "  FAIL ") + name + " " + str(detail))
    if not cond:
        FAILED.append(name)


def main():
    app = D.Designer()
    app.geometry("1200x820+20+20")
    app.update()

    print("[模式切换]")
    app.theme = D.C.template_theme("bounce")
    app.sel = 0
    app.refresh_all(rebuild_props=True)
    app.update()
    check("初始为元素模式", app._props_mode == "element",
          app._props_mode)

    # 进入 loop 模式
    app.loop_tree.selection_set("0")
    app._on_loop_select(None)
    app.update()
    check("选中 loop 后为 loop 模式", app._props_mode == "loop",
          app._props_mode)

    # 点元素树切回元素模式
    app.tree.selection_set("0")
    app._on_tree_select(None)
    app.update()
    check("点元素后切回元素模式", app._props_mode == "element",
          app._props_mode)

    # 再进 loop，再点「同一个元素」（sel 不变，靠 Button-1 兜底）
    app.loop_tree.selection_set("0")
    app._on_loop_select(None)
    app.update()
    app._on_tree_click(None)   # 模拟点已选中的元素
    app.update()
    check("点击已选中元素也切回元素模式", app._props_mode == "element",
          app._props_mode)

    print("[帧延时联动]")
    # 进入 loop 模式改帧延时
    app.loop_tree.selection_set("0")
    app._on_loop_select(None)
    app.update()
    entry = app._loop_entries()[0]
    groups = app._sprite_groups()
    ref = int(entry.get("sprite", 0) or 0)
    frame_count = len(groups[ref])
    print("  帧数", frame_count)

    # 直接改 frameDelay 后触发联动
    entry["frameDelay"] = 300
    app._sync_loop_delay(0)
    check("loopDelay 同步为 frameDelay×帧数", entry["loopDelay"] == 300 * frame_count,
          "loopDelay=%s" % entry["loopDelay"])

    # 界面上的循环周期输入框也应同步
    check("界面上 loopDelay 框同步", int(app._loop_loop_delay_var.get()) == 300 * frame_count,
          app._loop_loop_delay_var.get())

    app.destroy()
    print()
    if FAILED:
        print("失败 %d 项: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

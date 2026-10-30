#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""界面交互自检（需要桌面会话，会短暂弹出窗口）。

覆盖：增删元素、方向键微调、画布拖动、撤销/重做、保存/读取往返、图片导入校验。

    python editor/test_ui.py
"""

import base64
import io
import json
import os
import sys
import tempfile

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cw_core as C  # noqa: E402
import canvas_designer as D  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print("  OK   %s %s" % (name, detail))
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILED.append(name)


class Evt(object):
    def __init__(self, x, y):
        self.x = x
        self.y = y


def main():
    app = D.Designer()
    app.geometry("1200x820+30+30")
    app.update()

    print("[元素增删]")
    app.theme = C.template_theme("minimal")
    app.sel = 0
    app.refresh_all(rebuild_props=True)
    base = len(app.theme["setup"])
    check("模板元素数", base == 4, "%d" % base)
    app.add_element("text")
    check("添加文字", len(app.theme["setup"]) == base + 1, "%d" % len(app.theme["setup"]))
    check("选中新元素", app.sel == base)
    el = app.current()
    check("新元素居中", el["x"] == (64 - 40) // 2 or 0 <= el["x"] <= 64, "x=%s" % el["x"])

    print("[方向键微调]")
    x0, y0 = el["x"], el["y"]
    app.nudge((1, 0))
    app.nudge((1, 0))
    check("右移 2px", el["x"] == x0 + 2, "x=%s" % el["x"])
    app.nudge((0, -1))
    check("上移 1px", el["y"] == y0 - 1, "y=%s" % el["y"])

    print("[撤销 / 重做]")
    app.do_undo()
    check("撤销回原位", app.current()["y"] == y0, "y=%s" % app.current()["y"])
    app.do_redo()
    check("重做生效", app.current()["y"] == y0 - 1, "y=%s" % app.current()["y"])

    print("[画布拖动]")
    app.update()
    el = app.current()
    bbox = app.canvas.bbox(app.img_item)
    z = app.zoom
    ex0, ey0, ex1, ey1 = C.element_box(el, app.sim_time())
    cx = bbox[0] + ((ex0 + ex1) // 2) * z
    cy = bbox[1] + ((ey0 + ey1) // 2) * z
    before = (el["x"], el["y"])
    app._on_press(Evt(cx, cy))
    check("按下命中元素", app.current() is el and app._drag is not None)
    app._on_drag(Evt(cx + 2 * z, cy + 3 * z))
    app._on_release(Evt(cx + 2 * z, cy + 3 * z))
    after = (app.current()["x"], app.current()["y"])
    check("拖动位移 +2,+3", after == (before[0] + 2, before[1] + 3),
          "%s -> %s" % (before, after))

    print("[属性面板改值]")
    app.rebuild_props()
    app.update()
    var = app._prop_vars.get("x")
    if var is not None:
        var.set(7)
        app.update()
        check("改 x=7", app.current()["x"] == 7, "x=%s" % app.current()["x"])
    else:
        check("属性面板有 x 输入框", False)

    print("[保存 / 读取往返]")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    app.path = path
    ok = app._write(path)
    check("保存成功", bool(ok) and os.path.getsize(path) > 100,
          "%d B" % os.path.getsize(path))
    saved = json.load(open(path, encoding="utf-8"))
    check("文件里有 setup", len(saved.get("setup", [])) == len(app.theme["setup"]))
    app.theme = C.default_theme()
    app.refresh_all(rebuild_props=True)
    app.theme = C.load_theme_file(path)
    app.sel = 0
    app.refresh_all(rebuild_props=True)
    check("读回元素数一致", len(app.theme["setup"]) == len(saved["setup"]))
    check("读回 x 一致", app.theme["setup"][-1]["x"] == 7,
          "x=%s" % app.theme["setup"][-1]["x"])
    os.remove(path)

    print("[图片元素 + 校验]")
    img = Image.new("RGB", (80, 80))
    for y in range(80):
        for x in range(80):
            img.putpixel((x, y), (x * 3 % 256, y * 3 % 256, 128))
    res = C.auto_fit_image(img, bg=(0, 0, 0))
    check("自动压缩到 4096 内", res is not None and res.ok,
          "%dx%d %d B" % (res.width, res.height, res.size) if res else "None")
    app.theme["setup"].append({"type": "image", "image": res.b64, "x": 8, "y": 8})
    app.sel = len(app.theme["setup"]) - 1
    app.refresh_all(rebuild_props=True)
    issues = C.validate(app.theme, app.sim_time())
    check("整份主题无 error", not [i for i in issues if i[0] == "error"],
          str([m for lvl, m in issues if lvl == "error"]))
    lit = sum(1 for p in C.render_theme(app.theme).getdata() if p != (0, 0, 0))
    check("渲染有内容", lit > 300, "%d 个亮点" % lit)

    print("[设备接口（本地 mock 服务器）]")
    import http.server
    import threading
    received = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            received["body"] = self.rfile.read(n)
            received["path"] = self.path
            self.send_response(204)
            self.end_headers()

        def do_GET(self):
            body = b"pac-man\ndemo\n" if self.path.startswith("/themes") else b""
            self.send_response(200 if body else 204)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 8899), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    app.ip_var.set("127.0.0.1:8899")
    payload = C.theme_to_json(app.theme).encode("utf-8")
    status, _ = app._request("POST", "/theme?name=demo", body=payload, timeout=5)
    check("上传返回 204", status == 204, "status=%s" % status)
    check("服务端收到完整 JSON", received.get("body") == payload,
          "%d 字节，路径 %s" % (len(received.get("body") or b""), received.get("path")))
    status, body = app._request("GET", "/themes", timeout=5)
    check("主题列表可读", status == 200 and b"pac-man" in body, str(body))
    srv.shutdown()
    app.ip_var.set("192.168.137.99")

    print("[删除元素]")
    n = len(app.theme["setup"])
    app.delete_sel()
    check("删除成功", len(app.theme["setup"]) == n - 1)

    print("[精灵动画操作]")
    app.theme = C.template_theme("bounce")
    app.sel = 0
    app.refresh_all(rebuild_props=True)
    check("载入弹跳模板", len(app._sprite_groups()) == 1 and len(app._loop_entries()) == 1)

    app.sprite_add_group()
    check("添加精灵组", len(app._sprite_groups()) == 2)
    app.sprite_tree.selection_set("1")
    app._refresh_frame_preview()

    # 加帧（用合成图片）
    frame_img = Image.new("RGB", (8, 8), (255, 0, 0))
    res = C.prepare_image(frame_img, 8, 8, 2, bg=(0, 0, 0))
    app._sprite_groups()[1].append({"image": res.b64})
    app._refresh_sprite_tab()
    check("加帧成功", len(app._sprite_groups()[1]) == 1)

    app.loop_add()
    check("加 loop 实例", len(app._loop_entries()) == 2)
    # 编辑 loop：改位移
    entry = app._loop_entries()[1]
    entry["moveDuration"] = 500
    entry["moveTargetX"] = 40
    entry["moveTargetY"] = -1
    st = C.sprite_state(app.theme, entry, 250)
    check("位移生效", st[1] > 0, "x=%s" % st[1])

    # 动画渲染 + 校验
    img = C.render_theme_animated(app.theme, 0)
    check("动画渲染", img.size == (64, 64))
    issues = C.validate(app.theme)
    check("精灵主题无 error", not [i for i in issues if i[0] == "error"])

    # loop 删除精灵组时引用同步
    app.sprite_tree.selection_set("1")
    app.sprite_del()
    check("删组后剩 1 组", len(app._sprite_groups()) == 1)

    print("[loop 实例画布拖拽]")
    app._refresh_sprite_tab()
    app.loop_tree.selection_set("0")
    app.update()
    entry = app._loop_entries()[0]
    sx0, sy0 = int(entry.get("x", 0)), int(entry.get("y", 0))
    # 命中起始点标记并拖动
    hit = app._hit_loop_marker(sx0, sy0)
    check("命中起始点", hit is not None and hit[1] == "start", str(hit))
    bbox = app.canvas.bbox(app.img_item)
    z = app.zoom
    px = bbox[0] + sx0 * z + z // 2
    py = bbox[1] + sy0 * z + z // 2
    app._on_press(Evt(px, py))
    check("按下进入 loop 拖拽", app._drag is not None and app._drag.get("kind") == "loop")
    app._on_drag(Evt(px + 3 * z, py + 2 * z))
    app._on_release(Evt(px + 3 * z, py + 2 * z))
    check("起始点移动 +3,+2", (int(entry["x"]), int(entry["y"])) == (sx0 + 3, sy0 + 2),
          "(%s,%s)->(%s,%s)" % (sx0, sy0, entry["x"], entry["y"]))
    # 目标点拖拽
    entry["moveTargetX"] = 40
    entry["moveTargetY"] = 20
    hit = app._hit_loop_marker(40, 20)
    check("命中目标点", hit is not None and hit[1] == "target", str(hit))
    tpx = bbox[0] + 40 * z + z // 2
    tpy = bbox[1] + 20 * z + z // 2
    app._on_press(Evt(tpx, tpy))
    app._on_drag(Evt(tpx - 2 * z, tpy + z))
    app._on_release(Evt(tpx - 2 * z, tpy + z))
    check("目标点移动 -2,+1", (int(entry["moveTargetX"]), int(entry["moveTargetY"])) == (38, 21),
          "(%s,%s)" % (entry["moveTargetX"], entry["moveTargetY"]))

    print("[裁剪与多方案]")
    from PIL import Image as _I
    src = _I.new("RGB", (120, 80))
    for y in range(80):
        for x in range(120):
            src.putpixel((x, y), (x * 2 % 256, y * 3 % 256, 100))
    cropped = C.crop_image(src, (30, 20, 90, 60))
    check("裁剪尺寸", cropped.size == (60, 40), str(cropped.size))
    opts = C.gen_image_options(src, bg=(0, 0, 0))
    check("多方案有可选", len([o for o in opts if o["ok"]]) > 0,
          "%d 个可用" % len([o for o in opts if o["ok"]]))

    # 导出往返：sprites/loop 应保留
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    app.path = path
    app._write(path)
    saved = json.load(open(path, encoding="utf-8"))
    check("sprites 保留", len(saved.get("sprites", [])) == len(app.theme["sprites"]))
    check("loop 保留", len(saved.get("loop", [])) == len(app.theme["loop"]))
    os.remove(path)

    app.destroy()
    print()
    if FAILED:
        print("失败 %d 项: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cw_core 自检：颜色换算 / 字体度量 / PNG 编码 / 图片压缩 / 主题校验。

    python editor/test_core.py
"""

import base64
import io
import json
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import cw_core as C  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print("  OK   %s %s" % (name, detail))
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILED.append(name)


def test_colors():
    print("[颜色 RGB565]")
    cases = {
        "#000000": 0, "#FFFFFF": 65535, "#FF0000": 63488, "#00FF00": 2016,
        "#0000FF": 31, "#FFFF00": 65504, "#00C8C8": 1625, "#303030": 12678,
        "#212121": 8452, "#FFB000": 64896,
    }
    for hx, want in cases.items():
        got = C.hex_to_565(hx)
        check(hx, got == want, "-> %d (期望 %d)" % (got, want))
    for v in (0, 31, 2016, 65535, 8452):
        check("roundtrip %d" % v, C.rgb_to_565(C.rgb565_to_rgb(v)) == v)


def test_fonts():
    print("[字体度量]")
    fonts = C.load_fonts(os.path.join(HERE, "fontdata.json"))
    check("载入字体", set(fonts) >= {"big", "medium", "square", "picopixel", "default"},
          str(sorted(fonts)))

    big = fonts["big"]
    x1, y1, w, h, adv = big.text_bounds("12:34", 0, 0)
    # canvas/README.md 实测：big 的 "12:34" 墨迹宽 42，居中 x=11
    check("big 12:34 宽度", w == 42, "w=%d h=%d x1=%d y1=%d adv=%d" % (w, h, x1, y1, adv))
    check("big 12:34 居中 x", (64 - w) // 2 - x1 == 11, "x=%d" % ((64 - w) // 2 - x1))

    med = fonts["medium"]
    _, _, w2, _, _ = med.text_bounds("12:34", 0, 0)
    check("medium 12:34 宽度", w2 == 22, "w=%d" % w2)

    sq = fonts["square"]
    _, _, w3, _, _ = sq.text_bounds("12:34", 0, 0)
    check("square 12:34 宽度", w3 == 34, "w=%d" % w3)

    pico = fonts["picopixel"]
    _, _, w4, _, _ = pico.text_bounds("12:34", 0, 0)
    check("picopixel 12:34 宽度", w4 == 16, "w=%d" % w4)

    # square 的坑：'H' 等字母没有字形
    _, _, wh, _, _ = sq.text_bounds("H", 0, 0)
    check("square 'H' 几乎为空", wh <= 2, "w=%d" % wh)

    # 位图渲染必须真的画出像素
    canvas = C.Canvas(0)
    canvas.draw_text(big, 11, 21, "12:34", 65535, 0)
    colored = sum(1 for p in canvas.img.getdata() if p != (0, 0, 0))
    check("big 渲染出像素", colored > 100, "%d 个亮点" % colored)


def test_png():
    print("[索引色 PNG 编码]")
    for n_colors, bd in ((2, 1), (4, 2), (8, 4), (32, 8)):
        pal = [((i * 37) & 0xFF, (i * 91) & 0xFF, (i * 13) & 0xFF) for i in range(n_colors)]
        idx = [(x * y + x) % n_colors for y in range(16) for x in range(16)]
        png = C.encode_indexed_png(idx, pal, 16, 16)
        im = Image.open(io.BytesIO(png))
        ok_mode = im.mode == "P"
        ok_size = im.size == (16, 16)
        im = im.convert("RGB")
        want = [tuple(pal[i]) for i in idx]
        got = list(im.getdata())
        ok_px = want == got
        check("%d 色 PNG" % n_colors, ok_mode and ok_size and ok_px,
              "位深=%d 体积=%dB 像素一致=%s" % (bd, len(png), ok_px))


def _fake_photo(w=160, h=120):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x * 255 // w, y * 255 // h, (x * y) % 255)
    return img


def test_image_compress():
    print("[图片压缩 ≤1024B]")
    photo = _fake_photo()
    res = C.auto_fit_image(photo, limit=C.IMAGE_DECODE_LIMIT, bg=(0, 0, 0))
    check("auto_fit 有结果", res is not None)
    if res:
        check("auto_fit 体积", res.size <= C.IMAGE_DECODE_LIMIT,
              "%dx%d %d 色 %d B" % (res.width, res.height, res.colors, res.size))
        im = Image.open(io.BytesIO(res.png)).convert("RGB")
        check("auto_fit 可解码", im.size == (res.width, res.height), str(im.size))

    # 强行指定 32x32 / 8 色，验证体积会超标时能被发现
    res2 = C.prepare_image(photo, 32, 32, 8, dither=True, bg=(0, 0, 0))
    print("       32x32/8色/抖动 = %d B (ok=%s)" % (res2.size, res2.ok))

    # 纯色块图应该很小
    flat = Image.new("RGB", (32, 32), (255, 0, 0))
    for y in range(10, 20):
        for x in range(10, 20):
            flat.putpixel((x, y), (0, 0, 255))
    res3 = C.prepare_image(flat, 32, 32, 4, bg=(0, 0, 0))
    check("色块图很小", res3.size < 200, "%d B" % res3.size)

    # 等比缩放：宽图不能超过上限
    wide = _fake_photo(200, 50)
    res4 = C.prepare_image(wide, 32, 32, 8, mode="contain", bg=(0, 0, 0))
    check("等比缩放宽度", res4.width <= 32 and res4.height <= 32,
          "%dx%d" % (res4.width, res4.height))


def test_theme():
    print("[主题读写与校验]")
    path = os.path.join(ROOT, "canvas", "theme.json")
    if os.path.isfile(path):
        theme = C.load_theme_file(path)
        issues = C.validate(theme)
        errors = [i for i in issues if i[0] == "error"]
        check("示例主题无 error", not errors, str(errors))
        img = C.render_theme(theme)
        check("渲染尺寸", img.size == (64, 64))
        lit = sum(1 for p in img.getdata() if p != (0, 0, 0))
        check("示例主题有内容", lit > 200, "%d 个亮点" % lit)
        text = C.theme_to_json(theme)
        again = json.loads(text)
        check("JSON 往返", again["setup"] == theme["setup"])

    # 超限检测
    fat = C.default_theme()
    fat["setup"] = [{"type": "text", "content": "X" * 3000, "font": "medium",
                     "fgColor": 65535, "bgColor": 0, "x": 0, "y": 0}] * 20
    issues = C.validate(fat)
    check("超大 JSON 报 error", any(i[0] == "error" for i in issues),
          "估算 %d B" % C.theme_bytes(fat))

    # 图片超限检测
    big_img = Image.effect_noise((64, 64), 80).convert("RGB")
    raw = io.BytesIO()
    big_img.save(raw, "PNG")
    bad = C.default_theme()
    bad["setup"] = [{"type": "image", "image": base64.b64encode(raw.getvalue()).decode(),
                     "x": 0, "y": 0}]
    issues = C.validate(bad)
    check("超大图片报 error", any("IMAGE_BUFFER_SIZE" in m for _, m in issues),
          str([m for _, m in issues])[:90])


def test_datetime():
    print("[时间格式]")
    from datetime import datetime
    t = datetime(2026, 10, 28, 14, 7, 33)
    cases = {
        "H:i": "14:07", "H:i:s": "14:07:33", "m-d": "10-28",
        "A": "PM", "Y/m/d": "2026/10/28", "D, m/d": "Wed, 10/28",
        "g:i A": "2:07 PM", "H\\hi": "14h07",
    }
    for fmt, want in cases.items():
        got = C.php_datetime(fmt, t)
        check("格式 %r" % fmt, got == want, "-> %r" % got)


def test_sprites():
    print("[精灵动画]")
    theme = C.template_theme("bounce")
    check("弹跳模板有精灵", len(theme["sprites"]) == 1 and len(theme["sprites"][0]) == 3,
          "%d 帧" % len(theme["sprites"][0]))
    check("弹跳模板有 loop", len(theme["loop"]) == 1)

    entry = theme["loop"][0]

    # 帧动画：frameDelay=200，loopDelay=800，周期 800ms 内帧 0,1,2
    st0 = C.sprite_state(theme, entry, 0)
    st1 = C.sprite_state(theme, entry, 200)
    st2 = C.sprite_state(theme, entry, 400)
    st3 = C.sprite_state(theme, entry, 800)  # 循环回帧 0
    check("帧推进", st0[0] == 0 and st1[0] == 1 and st2[0] == 2, "%s,%s,%s" % (st0[0], st1[0], st2[0]))
    check("循环归零", st3[0] == 0, "frame=%s" % st3[0])

    # 位移：moveStartTime=2000, moveDuration=1000, 4->54, shouldReturnToOrigin
    # 第一次位移从 t=0 就开始（_lastResetMoveTime 初始为 0）
    # 0~1000 去程 4->54，1000~2000 回程 54->4，之后每 2000ms 重复
    p0 = C.sprite_state(theme, entry, 0)
    check("t=0 在起点", (p0[1], p0[2]) == (4, 54), "pos=(%s,%s)" % (p0[1], p0[2]))
    p300 = C.sprite_state(theme, entry, 300)
    check("t=300 去程 x=19", p300[1] == 19, "x=%s" % p300[1])
    # 周期 2000ms：0~1000 去程 4->54，1000~2000 回程 54->4
    mid = C.sprite_state(theme, entry, 500)
    check("去程中点 ~29", 24 <= mid[1] <= 34, "x=%s" % mid[1])
    back = C.sprite_state(theme, entry, 1500)
    check("回程中点 ~29", 24 <= back[1] <= 34, "x=%s" % back[1])
    end = C.sprite_state(theme, entry, 1999)
    check("回程接近起点", end[1] <= 10, "x=%s" % end[1])

    # 渲染动画不抛异常，且球所在处有非背景像素
    img = C.render_theme_animated(theme, 0)
    check("动画渲染尺寸", img.size == (64, 64))
    img2 = C.render_theme_animated(theme, 500)
    lit = sum(1 for p in img2.getdata() if p != (0, 0, 0))
    check("动画帧有内容", lit > 50, "%d 亮点" % lit)

    # 校验：精灵引用正确不报 error
    issues = C.validate(theme)
    check("弹跳模板无 error", not [i for i in issues if i[0] == "error"],
          str([m for l, m in issues if l == "error"]))

    # 坏引用：loop 指向不存在的精灵组
    bad = C.default_theme()
    bad["sprites"] = []
    bad["loop"] = [{"type": "sprite", "sprite": 5, "x": 0, "y": 0}]
    issues = C.validate(bad)
    check("坏精灵引用报 error", any(i[0] == "error" for i in issues))

    # 帧尺寸不一致：应报 warn
    import base64 as _b64mod
    import io as _io
    big = Image.new("RGB", (10, 10), (255, 0, 0))
    small = Image.new("RGB", (6, 6), (0, 255, 0))
    def _b64(img):
        b = _io.BytesIO()
        img.save(b, "PNG")
        return _b64mod.b64encode(b.getvalue()).decode()
    mismatch = C.default_theme()
    mismatch["sprites"] = [[{"image": _b64(big)}, {"image": _b64(small)}]]
    mismatch["loop"] = [{"type": "sprite", "sprite": 0, "x": 0, "y": 0}]
    issues = C.validate(mismatch)
    check("帧尺寸不一致报 warn", any(i[0] == "warn" and "尺寸不一致" in i[1] for i in issues),
          str([m for l, m in issues if l == "warn"]))

    # 一致尺寸不报该 warn
    ok_frames = C.default_theme()
    ok_frames["sprites"] = [[{"image": _b64(big)}, {"image": _b64(big)}]]
    ok_frames["loop"] = [{"type": "sprite", "sprite": 0, "x": 0, "y": 0}]
    issues = C.validate(ok_frames)
    check("帧尺寸一致无警告", not any("尺寸不一致" in i[1] for i in issues))


def test_crop_and_options():
    print("[裁剪与多方案]")
    img = Image.new("RGB", (100, 60), (10, 20, 30))
    for y in range(60):
        for x in range(100):
            img.putpixel((x, y), (x * 2 % 256, y * 3 % 256, 128))

    cropped = C.crop_image(img, (20, 10, 80, 50))
    check("裁剪尺寸", cropped.size == (60, 40), str(cropped.size))
    check("裁剪越界被 clamp", C.crop_image(img, (-10, -10, 200, 200)).size == img.size)

    # 多方案：应返回多个可选，且都 <= 1024
    opts = C.gen_image_options(img, bg=(0, 0, 0))
    check("多方案数量 > 3", len(opts) > 3, "%d 个" % len(opts))
    ok_opts = [o for o in opts if o["ok"]]
    check("有可用的方案", len(ok_opts) > 0, "%d 个 <=1024B" % len(ok_opts))
    check("方案排序递减", all(opts[i]["bytes"] >= opts[i + 1]["bytes"]
                              for i in range(len(opts) - 1)))

    # mode 参数应生效：cover 模式下所有候选都是正方形（填满）
    opts_cover = C.gen_image_options(img, bg=(0, 0, 0), mode="cover", max_w=32, max_h=32)
    if opts_cover:
        check("cover 模式填满", all(o["size"][0] == o["size"][1] for o in opts_cover),
              str([o["size"] for o in opts_cover[:3]]))

    # 裁剪后图片也能压缩
    res = C.prepare_image(cropped, 32, 32, 8, bg=(0, 0, 0))
    check("裁剪图可压缩", res.width <= 32 and res.height <= 32, str((res.width, res.height)))


def main():
    test_colors()
    test_fonts()
    test_png()
    test_image_compress()
    test_theme()
    test_datetime()
    test_sprites()
    test_crop_and_options()
    print()
    if FAILED:
        print("失败 %d 项: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

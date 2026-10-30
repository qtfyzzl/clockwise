# -*- coding: utf-8 -*-
"""生成「月薪喵」精灵动画草稿：32x32 像素猫，4 帧循环。

先输出放大预览图看造型，确认后再封成主题 JSON。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

BLACK = (0, 0, 0)
FUR = (242, 232, 213)
FUR_SH = (208, 194, 172)
ORANGE = (232, 162, 75)
INK = (38, 38, 38)
PINK = (228, 132, 146)
RED = (210, 72, 56)
RED_D = (156, 44, 34)
GOLD = (245, 194, 66)
WHITE = (255, 255, 255)

S = 32
S64 = 64


def cat64(idx):
    """64x64 全屏版本：细节翻倍，6 帧小剧情。"""
    img = Image.new("RGB", (S64, S64), BLACK)
    d = ImageDraw.Draw(img)
    tail_a = idx % 2 == 0
    eyes = "open"
    if idx == 1:
        eyes = "blink"
    elif idx == 3:
        eyes = "yen"
    elif idx >= 4:
        eyes = "happy"
    purse = idx >= 2
    star = idx == 3

    # 尾巴
    if tail_a:
        d.rectangle([42, 48, 54, 54], fill=FUR)
        d.rectangle([50, 40, 55, 50], fill=FUR)
        d.rectangle([51, 38, 56, 43], fill=ORANGE)
    else:
        d.rectangle([42, 50, 55, 56], fill=FUR)
        d.rectangle([52, 42, 57, 52], fill=FUR)
        d.rectangle([53, 40, 58, 45], fill=ORANGE)

    # 身体
    d.rectangle([20, 40, 43, 59], fill=FUR)
    d.rectangle([22, 60, 41, 62], fill=FUR)
    d.rectangle([24, 60, 29, 62], fill=FUR_SH)
    d.rectangle([34, 60, 39, 62], fill=FUR_SH)
    d.rectangle([28, 42, 35, 50], fill=ORANGE)

    # 前爪
    d.rectangle([21, 55, 26, 60], fill=WHITE)
    d.rectangle([37, 55, 42, 60], fill=WHITE)
    d.rectangle([21, 58, 26, 60], fill=FUR_SH)
    d.rectangle([37, 58, 42, 60], fill=FUR_SH)

    # 头
    d.rectangle([14, 12, 49, 38], fill=FUR)
    d.rectangle([16, 10, 47, 40], fill=FUR)
    # 耳朵
    d.polygon([(14, 15), (16, 2), (27, 11)], fill=FUR)
    d.polygon([(49, 15), (47, 2), (36, 11)], fill=FUR)
    d.polygon([(17, 13), (18, 6), (24, 11)], fill=PINK)
    d.polygon([(46, 13), (45, 6), (39, 11)], fill=PINK)
    # 虎斑
    d.rectangle([24, 11, 27, 18], fill=ORANGE)
    d.rectangle([36, 11, 39, 18], fill=ORANGE)
    d.rectangle([18, 13, 20, 17], fill=ORANGE)
    d.rectangle([43, 13, 45, 17], fill=ORANGE)

    # 眼睛（8x8）
    if eyes == "open":
        d.rectangle([19, 20, 27, 27], fill=INK)
        d.rectangle([36, 20, 44, 27], fill=INK)
        d.rectangle([21, 21, 23, 23], fill=WHITE)
        d.rectangle([38, 21, 40, 23], fill=WHITE)
    elif eyes == "blink":
        d.rectangle([19, 24, 27, 25], fill=INK)
        d.rectangle([36, 24, 44, 25], fill=INK)
    elif eyes == "yen":
        for x in (20, 37):
            d.line([(x, 20), (x + 4, 24)], fill=GOLD, width=2)
            d.line([(x + 7, 20), (x + 3, 24)], fill=GOLD, width=2)
            d.line([(x, 24), (x + 7, 24)], fill=GOLD, width=2)
            d.line([(x + 1, 28), (x + 6, 28)], fill=GOLD, width=2)
            d.line([(x + 3, 25), (x + 3, 29)], fill=GOLD, width=2)
    else:
        d.line([(19, 26), (23, 22), (27, 26)], fill=INK, width=2)
        d.line([(36, 26), (40, 22), (44, 26)], fill=INK, width=2)

    # 鼻子与嘴
    d.rectangle([30, 28, 33, 31], fill=PINK)
    d.rectangle([30, 32, 33, 32], fill=INK)
    d.line([(29, 34), (31, 34)], fill=INK, width=2)
    d.line([(33, 34), (35, 34)], fill=INK, width=2)

    # 胡须
    for y, dy in ((24, 2), (30, 0), (36, -2)):
        d.line([(7, y), (14, y + dy)], fill=FUR_SH, width=1)
        d.line([(57, y), (50, y + dy)], fill=FUR_SH, width=1)

    # 红包与手臂
    if purse:
        d.rectangle([18, 43, 22, 51], fill=FUR)
        d.rectangle([42, 43, 46, 51], fill=FUR)
        d.rectangle([22, 40, 42, 54], fill=RED)
        d.rectangle([22, 40, 42, 42], fill=RED_D)
        d.line([(28, 44), (32, 49)], fill=GOLD, width=2)
        d.line([(36, 44), (32, 49)], fill=GOLD, width=2)
        d.line([(27, 49), (37, 49)], fill=GOLD, width=2)
        d.line([(29, 53), (35, 53)], fill=GOLD, width=2)
        d.line([(32, 49), (32, 53)], fill=GOLD, width=2)

    if star:
        d.rectangle([52, 14, 56, 16], fill=GOLD)
        d.rectangle([53, 12, 55, 18], fill=GOLD)
    return img



def cat_body(d, tail_dir=1, eyes="open", arms="down", purse=False, star=False):
    """画一只正面坐姿的猫。"""
    # 尾巴（先画，压在身体后面）
    if tail_dir > 0:
        d.rectangle([22, 25, 27, 27], fill=FUR)
        d.rectangle([26, 22, 28, 26], fill=FUR)
        d.rectangle([27, 21, 29, 23], fill=ORANGE)
    else:
        d.rectangle([22, 27, 28, 29], fill=FUR)
        d.rectangle([27, 24, 29, 28], fill=FUR)
        d.rectangle([28, 23, 30, 25], fill=ORANGE)

    # 身体
    d.rectangle([10, 19, 22, 29], fill=FUR)
    d.rectangle([11, 30, 21, 31], fill=FUR)      # 底盘
    d.rectangle([12, 30, 14, 31], fill=FUR_SH)
    d.rectangle([18, 30, 20, 31], fill=FUR_SH)
    # 胸前橘斑
    d.rectangle([15, 21, 18, 25], fill=ORANGE)

    # 前爪
    d.rectangle([11, 27, 13, 29], fill=WHITE)
    d.rectangle([19, 27, 21, 29], fill=WHITE)

    # 头
    d.rectangle([6, 5, 25, 18], fill=FUR)
    d.rectangle([7, 4, 24, 19], fill=FUR)
    # 耳朵
    d.polygon([(6, 7), (7, 1), (12, 5)], fill=FUR)
    d.polygon([(25, 7), (24, 1), (19, 5)], fill=FUR)
    d.polygon([(7, 6), (8, 3), (11, 5)], fill=PINK)
    d.polygon([(24, 6), (23, 3), (20, 5)], fill=PINK)
    # 额头虎斑
    d.rectangle([12, 5, 13, 8], fill=ORANGE)
    d.rectangle([18, 5, 19, 8], fill=ORANGE)
    d.rectangle([9, 6, 9, 7], fill=ORANGE)
    d.rectangle([22, 6, 22, 7], fill=ORANGE)

    # 眼睛
    if eyes == "open":
        d.rectangle([9, 10, 12, 13], fill=INK)
        d.rectangle([19, 10, 22, 13], fill=INK)
        d.rectangle([10, 11, 10, 11], fill=WHITE)
        d.rectangle([20, 11, 20, 11], fill=WHITE)
    elif eyes == "blink":
        d.rectangle([9, 12, 12, 13], fill=INK)
        d.rectangle([19, 12, 22, 13], fill=INK)
    elif eyes == "yen":
        for x in (9, 19):
            d.line([(x, 10), (x + 1, 12)], fill=GOLD)
            d.line([(x + 3, 10), (x + 2, 12)], fill=GOLD)
            d.line([(x, 12), (x + 3, 12)], fill=GOLD)
            d.line([(x, 14), (x + 3, 14)], fill=GOLD)
            d.rectangle([x + 1, 13, x + 2, 15], fill=GOLD)
    elif eyes == "happy":
        d.arc([9, 10, 12, 14], 200, 340, fill=INK)
        d.arc([19, 10, 22, 14], 200, 340, fill=INK)

    # 鼻子与嘴
    d.rectangle([15, 14, 16, 15], fill=PINK)
    d.line([(15, 16), (16, 16)], fill=INK)
    d.line([(14, 17), (15, 17)], fill=INK)
    d.line([(16, 17), (17, 17)], fill=INK)

    # 胡须
    d.line([(4, 13), (7, 14)], fill=FUR_SH)
    d.line([(4, 16), (7, 16)], fill=FUR_SH)
    d.line([(27, 13), (24, 14)], fill=FUR_SH)
    d.line([(27, 16), (24, 16)], fill=FUR_SH)

    # 手臂与工资袋
    if arms == "up" or purse:
        d.rectangle([8, 17, 9, 23], fill=FUR)       # 左臂
        d.rectangle([23, 17, 24, 23], fill=FUR)     # 右臂
    if purse:
        d.rectangle([11, 19, 21, 26], fill=RED)
        d.rectangle([11, 19, 21, 20], fill=RED_D)
        d.rectangle([10, 19, 11, 21], fill=RED)
        d.rectangle([21, 19, 22, 21], fill=RED)
        # 金色 ¥
        d.line([(14, 21), (16, 24)], fill=GOLD)
        d.line([(18, 21), (16, 24)], fill=GOLD)
        d.line([(14, 24), (18, 24)], fill=GOLD)
        d.line([(15, 26), (17, 26)], fill=GOLD)
        d.line([(16, 25), (16, 26)], fill=GOLD)
        # 手臂抱袋
        d.rectangle([9, 20, 10, 23], fill=FUR)
        d.rectangle([22, 20, 23, 23], fill=FUR)

    if star:
        d.rectangle([28, 7, 28, 7], fill=GOLD)
        d.rectangle([27, 8, 29, 8], fill=GOLD)
        d.rectangle([28, 9, 28, 9], fill=GOLD)


def frame(idx):
    img = Image.new("RGB", (S, S), BLACK)
    d = ImageDraw.Draw(img)
    if idx == 0:
        cat_body(d, tail_dir=1, eyes="open")
    elif idx == 1:
        cat_body(d, tail_dir=-1, eyes="blink")
    elif idx == 2:
        cat_body(d, tail_dir=1, eyes="yen", arms="up", purse=True, star=True)
    else:
        cat_body(d, tail_dir=-1, eyes="happy", arms="up", purse=True)
    return img


def _build(frames, size, frame_delay, loop_delay, pos, setup=None):
    import cw_core as C
    b64s = []
    for i, img in enumerate(frames):
        res = C.prepare_image(img, size, size, 16, bg=(0, 0, 0), mode="stretch")
        print("  帧 %d: %dx%d %d 色 %d B ok=%s"
              % (i, res.width, res.height, res.colors, res.size, res.ok))
        b64s.append(res.b64)
    return {
        "name": "", "version": 1, "author": "WorkBuddy",
        "bgColor": 0, "delay": loop_delay,
        "setup": setup or [],
        "sprites": [[{"image": b} for b in b64s]],
        "loop": [{"type": "sprite", "sprite": 0, "x": pos[0], "y": pos[1],
                  "frameDelay": frame_delay, "loopDelay": loop_delay,
                  "moveStartTime": 0, "moveDuration": 0,
                  "moveTargetX": -1, "moveTargetY": -1,
                  "shouldReturnToOrigin": False}],
    }


def _gif(theme, path, loop_ms, box=256, step=50):
    import cw_core as C
    imgs = [C.render_theme_animated(theme, t).resize((box, box), Image.NEAREST)
            for t in range(0, loop_ms, step)]
    imgs[0].save(path, save_all=True, append_images=imgs[1:],
                 duration=step, loop=0, optimize=True)


def _strip(theme, path, times, scale=4):
    import cw_core as C
    gap = 12
    w = C.PANEL * scale
    out = Image.new("RGB", ((w + gap) * len(times) - gap, w), (30, 30, 30))
    for i, t in enumerate(times):
        out.paste(C.render_theme_animated(theme, t).resize((w, w), Image.NEAREST),
                  (i * (w + gap), 0))
    out.save(path)


def main():
    import cw_core as C
    from datetime import datetime

    out_dir = os.path.join(os.path.dirname(os.path.dirname(HERE)), "canvas", "themes")
    os.makedirs(out_dir, exist_ok=True)
    demo = datetime(2026, 10, 30, 10, 9, 0)

    print("[64x64 全屏动画]")
    t64 = _build([cat64(i) for i in range(6)], 64, 180, 1080, (0, 0))
    t64["name"] = "月薪喵"
    print("  校验:", C.validate(t64, demo) or "无问题")
    p64 = os.path.join(out_dir, "月薪喵.json")
    with open(p64, "w", encoding="utf-8") as f:
        f.write(C.theme_to_json(t64, indent=2))
    print("  %s  %.1f KB" % (p64, os.path.getsize(p64) / 1024.0))
    _gif(t64, os.path.join(out_dir, "月薪喵-预览.gif"), 1080)
    _strip(t64, os.path.join(out_dir, "月薪喵-整屏预览.png"),
           (0, 180, 360, 540, 720, 900))

    print("[32x32 表盘版]")
    clock = {"type": "datetime", "content": "H:i", "font": "big",
             "fgColor": 65535, "x": 0, "y": 14}
    t32 = _build([frame(i) for i in range(4)], 32, 220, 880, (16, 28), [clock])
    clock["x"], _ = C.center_element(t32, clock, "h", demo)
    t32["name"] = "月薪喵-表盘"
    print("  校验:", C.validate(t32, demo) or "无问题")
    p32 = os.path.join(out_dir, "月薪喵-表盘.json")
    with open(p32, "w", encoding="utf-8") as f:
        f.write(C.theme_to_json(t32, indent=2))
    print("  %s  %.1f KB" % (p32, os.path.getsize(p32) / 1024.0))
    _gif(t32, os.path.join(out_dir, "月薪喵-表盘-预览.gif"), 880)
    _strip(t32, os.path.join(out_dir, "月薪喵-表盘-整屏预览.png"),
           (0, 220, 440, 660))

if __name__ == "__main__":
    main()

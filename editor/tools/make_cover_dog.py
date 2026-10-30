# -*- coding: utf-8 -*-
"""把捂嘴憋笑小狗 GIF 像素化成 64x64 点阵钟精灵主题。

处理链：抽帧 → 白底压成深底（保留白脸棕耳）→ 加白描边 → 裁透明边 →
等比缩放 → 共享调色板量化（帧间颜色稳定）→ 8-bit RGB PNG。
产出画布模式 JSON + 预览。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageFilter, ImageSequence  # noqa: E402

import cw_core as C  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
GIF = r"C:\Users\26541\Pictures\二次元\6a1208acd1fd4IET.gif"
OUT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "canvas", "themes")

BG = (255, 255, 255)    # 白色背景板
N_FRAMES = 12           # 抽帧数
COLORS = 6
SIZE = 56               # 目标边长（有效内容 64x59 → 56x56）
FRAME_DELAY = 170
LOOP_DELAY = N_FRAMES * FRAME_DELAY


def white_bg_to_dark(rgba, bg=BG, thresh=235):
    """白底换深底：只换接近纯白的背景，白脸/白手（被描边包围）保留。

    阈值放到 235：原 GIF 的抗锯齿灰边（半透明）落在 200~250 之间，
    一并归入背景，避免缩到 56px 后变成噪点碎块。
    """
    w, h = rgba.size
    a = rgba.convert("RGB")
    mask = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b = a.getpixel((x, y))
            if r >= thresh and g >= thresh and b >= thresh:
                mask[y][x] = True
    result = Image.new("RGB", (w, h), bg)
    px = result.load()
    for y in range(h):
        for x in range(w):
            if not mask[y][x]:
                px[x, y] = a.getpixel((x, y))
                continue
            keep = False
            for dy in (-2, -1, 0, 1, 2):
                for dx in (-2, -1, 0, 1, 2):
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < w and 0 <= yy < h and not mask[yy][xx]:
                        keep = True
                        break
                if keep:
                    break
            px[x, y] = a.getpixel((x, y)) if keep else bg

    # 加一圈白色描边：紧贴形象、且在背景里的像素 → 浅色轮廓
    content = result.convert("L").point(lambda p: 255 if p > 8 else 0)
    edge = content.filter(ImageFilter.MaxFilter(3))
    out = Image.new("RGB", (w, h), bg)
    po = out.load()
    rp = result.load()
    for y in range(h):
        for x in range(w):
            if content.getpixel((x, y)) == 0 and edge.getpixel((x, y)) > 0:
                po[x, y] = (255, 255, 255)
            else:
                po[x, y] = rp[x, y]
    return out


def enhance_outline(img, bg=BG):
    """保留白底，加深描边，让白脸/白肚子和白背景区分开。

    原图白底 + 白脸 + 棕描边。问题：脸/肚子的白和背景白一样，
    缩到 56px 后分不清。解法：把深棕描边加深加粗，让轮廓撑起形状。
    """
    w, h = img.size
    a = img.convert("RGB")
    # 找出深色（描边）像素，膨胀一圈形成更强的轮廓
    dark = a.convert("L").point(lambda p: 255 if p < 150 else 0)
    edge = dark.filter(ImageFilter.MaxFilter(3))
    out = a.copy()
    px = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b = a.getpixel((x, y))
            # 描边像素（原深棕）加深成更深的棕，和白底/白脸拉开对比
            if r < 160 and g < 140 and b < 130:
                px[x, y] = (72, 48, 42)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    im = Image.open(GIF)
    src_frames = [f.convert("RGBA") for f in ImageSequence.Iterator(im)]
    total = len(src_frames)
    idx = [round(i * (total - 1) / (N_FRAMES - 1)) for i in range(N_FRAMES)]

    all_bbox = None
    cleaned = []
    for i in idx:
        # 保留白底 + 加深描边，白脸白肚子自然保留，靠描边区分
        clean = enhance_outline(src_frames[i].convert("RGB"))
        # 用描边（深色）作为内容 mask，裁出有效区域
        mask = clean.convert("L").point(lambda p: 255 if p < 150 else 0)
        mask = mask.filter(ImageFilter.MaxFilter(3)).filter(
            ImageFilter.MinFilter(3))
        bb = mask.getbbox()
        if bb:
            all_bbox = bb if all_bbox is None else (
                min(all_bbox[0], bb[0]), min(all_bbox[1], bb[1]),
                max(all_bbox[2], bb[2]), max(all_bbox[3], bb[3]))
        cleaned.append(clean)
    print("统一内容 bbox", all_bbox)

    # 共享调色板：用第一帧生成，所有帧都映射到它，帧间颜色稳定
    ref = C.prepare_image(cleaned[0].crop(all_bbox), SIZE, SIZE, COLORS,
                          bg=BG, mode="fit", smooth=False)
    ref_colors = [tuple(ref.palette[i]) for i in range(ref.colors)]

    def nearest(p):
        return min(ref_colors, key=lambda c:
                   (c[0] - p[0]) ** 2 + (c[1] - p[1]) ** 2 + (c[2] - p[2]) ** 2)

    b64s = []
    for k, clean in enumerate(cleaned):
        crop = clean.crop(all_bbox)
        fit = C._fit_image(crop, SIZE, SIZE, "fit", False).convert("RGB")
        px = fit.load()
        for y in range(fit.size[1]):
            for x in range(fit.size[0]):
                px[x, y] = nearest(px[x, y])
        png = C.encode_rgb_png(fit.tobytes(), fit.size[0], fit.size[1], level=9)
        res = C.ImageResult(png, None, ref_colors, fit.size[0], fit.size[1],
                            ref.colors)
        print("  帧 %02d: %dx%d %d 色 %d B ok=%s"
              % (k, res.width, res.height, res.colors, res.size, res.ok))
        b64s.append(res.b64)

    theme = {
        "name": "捂嘴小狗", "version": 1, "author": "WorkBuddy",
        "bgColor": 0, "delay": LOOP_DELAY,
        "setup": [], "sprites": [[{"image": b} for b in b64s]],
        "loop": [{"type": "sprite", "sprite": 0, "x": 4, "y": 4,
                  "frameDelay": FRAME_DELAY, "loopDelay": LOOP_DELAY,
                  "moveStartTime": 0, "moveDuration": 0,
                  "moveTargetX": -1, "moveTargetY": -1,
                  "shouldReturnToOrigin": False}],
    }
    issues = C.validate(theme)
    print("校验:", issues or "无问题")

    path = os.path.join(OUT, "捂嘴小狗.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(C.theme_to_json(theme, indent=2))
    print("主题 %s  %.1f KB" % (path, os.path.getsize(path) / 1024.0))

    imgs = [C.render_theme_animated(theme, t).resize((256, 256), Image.NEAREST)
            for t in range(0, LOOP_DELAY, 50)]
    gif_path = os.path.join(OUT, "捂嘴小狗-预览.gif")
    imgs[0].save(gif_path, save_all=True, append_images=imgs[1:],
                 duration=50, loop=0, optimize=True)

    gap = 12
    w = 64 * 4
    sel = list(range(0, N_FRAMES, N_FRAMES // 6))[:6]
    strip = Image.new("RGB", ((w + gap) * len(sel) - gap, w), (30, 30, 30))
    for i, t in enumerate(sel):
        strip.paste(C.render_theme_animated(theme, t * FRAME_DELAY).resize(
            (w, w), Image.NEAREST), (i * (w + gap), 0))
    strip.save(os.path.join(OUT, "捂嘴小狗-整屏预览.png"))
    print("预览完成")


if __name__ == "__main__":
    main()

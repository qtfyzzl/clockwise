#!/usr/bin/env python3
"""
主题 JSON 合规检查（针对 Canvas 主题引擎 cw-cf-0x07）

用法：
    python tools/check_theme.py canvas/themes/snake-text.json
    python tools/check_theme.py canvas/themes/*.json      # 批量

为什么要检查：
  设备端 PNGdec 1.0.1 对「索引色/调色板 PNG」（颜色类型 3，尤其位深 1/2/4）
  的解码有缺陷，会跳到空指针导致设备不断重启（Guru Meditation / BREAK instr）。
  实测能正常工作的主题，图片无一例外都是 8-bit 的 RGB(2) 或 RGBA(6)。

退出码：0 = 全部通过，1 = 有问题
"""
import base64
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pngkit          # PNG 读写统一在 pngkit 里

# ---- 设备端硬限制 ----
MAX_FILE_BYTES = 16 * 1024      # DynamicJsonDocument 16384
MAX_IMAGE_BYTES = 4096          # IMAGE_BUFFER_SIZE（设备端已从 1024 提到 4096）
MAX_IMAGE_W = 64
MAX_IMAGE_H = 64
MAX_THEME_PIXELS = 40000        # 精灵总像素预算（RAM 保护的经验值）

ALLOWED_TYPES = {"text", "datetime", "image", "rect", "fillrect", "line", "sprite"}

CT_NAME = {0: "灰度(0)", 2: "RGB(2)", 3: "调色板(3)", 4: "灰度+Alpha(4)", 6: "RGBA(6)"}


def check_file(path):
    print(f"\n{'=' * 62}\n检查: {path}")
    ok = True
    warnings = []       # 非致命提示（例如 4/8 位调色板 PNG）
    size = os.path.getsize(path)
    print(f"  文件大小: {size} 字节", end="")
    if size > MAX_FILE_BYTES:
        print(f"  ❌ 超过 {MAX_FILE_BYTES}（JSON 缓冲装不下）")
        ok = False
    else:
        print(f"  ✅ (上限 {MAX_FILE_BYTES})")

    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        print(f"  ❌ JSON 解析失败: {e}")
        return False

    for k in ("name", "version", "author", "bgColor", "setup"):
        if k not in d:
            print(f"  ⚠️  缺少顶层字段: {k}")

    # ---- setup / loop 元素 ----
    for sect in ("setup", "loop"):
        arr = d.get(sect) or []
        bad = [i for i, e in enumerate(arr) if not isinstance(e, dict) or "type" not in e]
        unknown = [e.get("type") for e in arr
                   if isinstance(e, dict) and e.get("type") not in ALLOWED_TYPES]
        print(f"  [{sect}] {len(arr)} 个元素", end="")
        if bad:
            print(f"  ❌ 第 {bad} 个缺 type 字段（设备端 strcmp(nullptr) 会崩）")
            ok = False
        elif unknown:
            print(f"  ⚠️  有未知类型 {set(unknown)}，设备会忽略")
        else:
            print("  ✅")

    # ---- 图片检查（关键）----
    sprites = d.get("sprites") or []
    total_px = 0
    frame_count = 0
    problems = []
    for gi, group in enumerate(sprites):
        if not isinstance(group, list):
            problems.append(f"sprites[{gi}] 不是数组")
            continue
        for fi, fr in enumerate(group):
            if not isinstance(fr, dict) or "image" not in fr:
                problems.append(f"sprites[{gi}][{fi}] 缺少 image 字段")
                continue
            b64 = fr["image"]
            if not b64:
                # 空字符串是「这一帧不绘制」（用于停顿），属于正常写法
                warnings.append(f"sprites[{gi}][{fi}] 是空帧（不绘制），仅作停顿")
                continue
            frame_count += 1
            raw = base64.b64decode(b64 + "=" * (-len(b64) % 4))
            # 必须先验签名：JPEG 按 PNG 的偏移去读也能读出"数字"来，
            # 会得到 bit depth=69、宽 4718592 这种垃圾值，反而蒙混过关。
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                kind = ("JPEG" if raw.startswith(b"\xff\xd8\xff") else
                        "GIF" if raw.startswith(b"GIF8") else
                        "BMP" if raw.startswith(b"BM") else "未知格式")
                problems.append(
                    f"sprites[{gi}][{fi}] 不是 PNG（检测到 {kind}）→ 设备只支持 PNG")
                continue
            info = pngkit.info(raw)
            if info is None:
                problems.append(f"sprites[{gi}][{fi}] PNG 头损坏")
                continue
            w, h, bd, ct, plte = info
            total_px += w * h
            if ct == 3 and bd in (1, 2):
                problems.append(
                    f"sprites[{gi}][{fi}] 是 {bd}-bit 索引色 PNG → PNGdec 位解包有缺陷，设备会闪退")
            elif ct == 3:
                warnings.append(
                    f"sprites[{gi}][{fi}] 是 {bd}-bit 调色板 PNG（官方主题常用，一般可用；"
                    f"若想最保险请导出 8-bit RGB/RGBA）")
            elif ct not in (0, 2, 6):
                problems.append(f"sprites[{gi}][{fi}] 颜色类型 {ct} 不受支持")
            elif ct != 3 and bd != 8:
                warnings.append(f"sprites[{gi}][{fi}] 位深 {bd}（建议 8）")
            if w > MAX_IMAGE_W or h > MAX_IMAGE_H:
                problems.append(f"sprites[{gi}][{fi}] 尺寸 {w}x{h} 超过 {MAX_IMAGE_W}x{MAX_IMAGE_H}")
            if len(raw) > MAX_IMAGE_BYTES:
                problems.append(f"sprites[{gi}][{fi}] 解码后 {len(raw)}B 超过 {MAX_IMAGE_BYTES}")

    print(f"  [sprites] {len(sprites)} 组 / {frame_count} 帧", end="")
    if warnings:
        for w in warnings[:3]:
            print(f"      ⚠️  {w}")
        if len(warnings) > 3:
            print(f"      ⚠️  ...另有 {len(warnings)-3} 处同类提示")
    if problems:
        print(f"  ❌ {len(problems)} 处问题")
        for p in problems[:8]:
            print(f"      · {p}")
        if len(problems) > 8:
            print(f"      · ...还有 {len(problems) - 8} 处")
        ok = False
    else:
        print("  ✅")

    # ---- 精灵内存估算 ----
    if total_px:
        print(f"  精灵总像素: {total_px}（{frame_count} 帧）")
        if total_px > MAX_THEME_PIXELS:
            print(f"  ⚠️  超过建议值 {MAX_THEME_PIXELS}，动画可能卡顿")

    # ---- loop 里的 sprite 引用 ----
    for i, e in enumerate(d.get("loop") or []):
        if isinstance(e, dict) and e.get("type") == "sprite":
            ref = e.get("sprite")
            if not isinstance(ref, int) or ref < 0 or ref >= len(sprites):
                print(f"  ❌ loop[{i}].sprite={ref} 超出 sprites 范围（共 {len(sprites)} 组）")
                ok = False

    print(f"  → {'✅ 通过' if ok else '❌ 需要修改'}")
    return ok


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    results = [check_file(p) for p in args]
    total, passed = len(results), sum(1 for r in results if r)
    print(f"\n{'=' * 62}\n汇总: {passed}/{total} 个文件通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())

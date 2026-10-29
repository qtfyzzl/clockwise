#!/usr/bin/env python3
"""
把本地 canvas/themes 里的主题批量上传到设备。

用途：分区表改动后 SPIFFS 偏移变了，原有主题会失联（列表变空），
需要一次性重传。也可以日常用来给设备同步主题库。

用法：
    python tools/upload_themes.py 192.168.137.216
    python tools/upload_themes.py 192.168.137.216 --only pac-man,nyan-cat
    python tools/upload_themes.py 192.168.137.216 --max-kb 14

默认只传 ≤14KB 的（JSON 缓冲 16KB，超过的解析不了），并跳过设备上已有的。
"""
import argparse
import glob
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME_DIR = os.path.join(ROOT, "canvas", "themes")


def http(ip, path, method="GET", data=None, timeout=30):
    req = urllib.request.Request(f"http://{ip}{path}", data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ip")
    ap.add_argument("--only", help="只传这些（逗号分隔，不带 .json）")
    ap.add_argument("--max-kb", type=int, default=14, help="单个 JSON 的大小上限（KB）")
    ap.add_argument("--force", action="store_true", help="设备上已有的也覆盖")
    args = ap.parse_args()

    # 设备上已有的主题
    existing = set()
    try:
        _, body = http(args.ip, "/themes", timeout=15)
        existing = {l.strip() for l in body.decode("utf-8", "replace").splitlines() if l.strip()}
        print(f"设备当前 {len(existing)} 个主题")
    except Exception as e:
        print(f"读取主题列表失败：{e}")
        return 1

    wanted = None
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}

    files = sorted(glob.glob(os.path.join(THEME_DIR, "*.json")))
    todo = []
    for f in files:
        name = os.path.splitext(os.path.basename(f))[0]
        if wanted is not None and name not in wanted:
            continue
        size = os.path.getsize(f)
        if size > args.max_kb * 1024:
            continue
        if name in existing and not args.force:
            continue
        todo.append((name, f, size))

    if not todo:
        print("没有需要上传的主题")
        return 0

    print(f"待上传 {len(todo)} 个\n")
    ok = fail = 0
    fails = []
    for name, path, size in todo:
        data = open(path, "rb").read()
        t = time.time()
        try:
            status, _ = http(args.ip, f"/theme?name={name}", "POST", data, timeout=40)
            dt = time.time() - t
            if status == 204:
                ok += 1
                print(f"  ✓ {name:<22} {size//1024:>3}KB  {dt:.2f}s")
            else:
                fail += 1
                fails.append((name, f"HTTP {status}"))
                print(f"  ✗ {name:<22} {size//1024:>3}KB  HTTP {status}")
        except Exception as e:
            fail += 1
            fails.append((name, str(e)[:40]))
            print(f"  ✗ {name:<22} {size//1024:>3}KB  {str(e)[:40]}")
        time.sleep(0.3)

    print(f"\n完成：成功 {ok}，失败 {fail}")
    for n, why in fails:
        print(f"  {n}: {why}")

    # 上传会把当前主题指到最后一个，恢复成一个确定的值
    try:
        http(args.ip, "/set?canvasFile=pac-man", "POST", b"", timeout=15)
        print("当前主题已重置为 pac-man")
    except Exception:
        pass

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

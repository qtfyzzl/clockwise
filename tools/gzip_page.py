#!/usr/bin/env python3
"""
把 SettingsWebPage.h 里的页面 gzip 压缩，生成 C 头文件。

为什么这么做：ESP32 的 TCP 吞吐在弱链路/高 RTT 下只有几 KB/s，
32KB 的设置页要十几次才传完。而 HTTP 支持 Content-Encoding: gzip——
**解压是浏览器做的，设备只负责发压缩后的字节**，不需要在设备上跑 deflate。
压缩比一般 4~5 倍。

用法（改完 SettingsWebPage.h 后必须重新跑）：
    python tools/gzip_page.py
"""
import gzip
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "firmware", "lib", "cw-commons", "SettingsWebPage.h")
DST = os.path.join(ROOT, "firmware", "lib", "cw-commons", "SettingsWebPage_gz.h")


def main():
    src = open(SRC, encoding="utf-8").read()
    m = re.search(r'R""""\((.*)\)"""";', src, re.S)
    if not m:
        raise SystemExit("在 SettingsWebPage.h 里没找到 R\"\"\"\"(...)\"\"\"\" 页面正文")

    page = m.group(1).lstrip()          # 去掉开头的换行，与原页面一致
    raw = page.encode("utf-8")

    # mtime=0 让输出可复现（同样的输入 -> 同样的字节，避免无意义重编译）
    packed = gzip.compress(raw, compresslevel=9, mtime=0)

    lines = []
    for i in range(0, len(packed), 20):
        chunk = packed[i:i + 20]
        lines.append("  " + "".join("0x%02x," % b for b in chunk))

    out = """// 自动生成，请勿手改。改完 SettingsWebPage.h 后运行：python tools/gzip_page.py
#pragma once
#include <stdint.h>

// 原始页面 %d 字节，gzip 后 %d 字节（压缩率 %.0f%%）
static const uint32_t SETTINGS_PAGE_GZ_LEN = %d;
static const uint8_t SETTINGS_PAGE_GZ[] = {
%s
};
""" % (len(raw), len(packed), len(packed) * 100.0 / len(raw), len(packed), "\n".join(lines))

    open(DST, "w", encoding="utf-8").write(out)
    print("原始 %d 字节 -> gzip %d 字节（%.0f%%），已写入 %s"
          % (len(raw), len(packed), len(packed) * 100.0 / len(raw), os.path.relpath(DST, ROOT)))


if __name__ == "__main__":
    main()

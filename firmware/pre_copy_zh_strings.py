"""PlatformIO 构建钩子：把 WiFiManager 配网页文案替换为中文。

背景：WiFiManager 的 Captive Portal 文案由 wm_strings_en.h 提供，默认英文。
官方支持用 WM_STRINGS_FILE 宏换语言包，但那个宏要用双引号 include，
且 build_flags 的 -D 值转义在 PlatformIO → gcc 之间极易出错（反复验证
`\\"` 转义都无法让 #include 正确命中）。

因此放弃宏覆盖，改用最直接的方式：构建前把中文语言包的内容覆盖写到
libdeps 里 WiFiManager 的 wm_strings_en.h（文件名不变）。这样
WiFiManager.h 的默认 `#include "wm_strings_en.h"` 直接命中中文内容，
零宏、零转义、零 include 路径问题。

libdeps 重拉库会还原英文，但每次构建前本脚本都会重新覆盖，不受影响。
"""
import shutil
import os

Import("env")

def apply_zh():
    env_name = env.get("PIOENV", "esp32dev")
    src = os.path.join(env.subst("$PROJECT_DIR"), "lib", "cw-commons", "wm_strings_zh.h")
    dst_dir = env.subst("$PROJECT_LIBDEPS_DIR") + os.sep + env_name + os.sep + "WiFiManager"
    dst = os.path.join(dst_dir, "wm_strings_en.h")

    if not os.path.exists(src):
        print("[pre:zh] 中文源文件不存在，跳过：", src)
        return

    os.makedirs(dst_dir, exist_ok=True)
    # 先备份英文原版（若还没备份过），便于回溯
    bak = os.path.join(dst_dir, "wm_strings_en.h.orig")
    if not os.path.exists(bak):
        try:
            shutil.copyfile(dst, bak)
        except OSError:
            pass

    # 内容变了才重写，避免无谓触发重编
    if os.path.exists(dst):
        try:
            if open(src, "rb").read() == open(dst, "rb").read():
                return
        except OSError:
            pass
    shutil.copyfile(src, dst)
    print("[pre:zh] 已覆盖 WiFiManager 文案为中文 ->", dst)

# Import 阶段立即执行（早于库编译），再挂 pre 保险（针对增量构建）
apply_zh()
env.AddPreAction("buildprog", lambda *a, **k: apply_zh())

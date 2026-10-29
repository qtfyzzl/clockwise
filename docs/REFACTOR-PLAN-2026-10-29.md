# 代码库结构审计与优化方案

> 审计日期：2026-10-29
> 范围：`firmware/`（自研部分，不含 submodule 与第三方库）、`tools/`、`editor/`
> 原则：**只做结构调整，不改功能与行为**；每项都给出验证方式

---

## 一、现状概览

| 模块 | 文件数 | 行数 | 说明 |
|---|---|---|---|
| `firmware/src` | 5 | 694 | 入口 + 离线时钟 + 时间存档 |
| `firmware/lib/cw-commons` | 13 | 2,835 | 网络、配置、Web 服务、状态显示 |
| `firmware/custom-themes/canvas` | 8 | 1,236 | JSON 主题引擎 |
| `firmware/lib/native-mario` | 8 | 737 | 原生主题（复制自 cw-cf-0x01） |
| `firmware/lib/cw-gfx-engine` | 13 | 289 | 2D 精灵/游戏引擎 |
| `tools` | 6 | 870 | 主题校验、转换、打包、上传 |
| `editor` | 10 | 5,441 | 桌面主题设计器（Tkinter） |

分层是清楚的：`src`（应用）→ `lib`（基础服务）→ 主题（渲染）。问题集中在**重复**和**文件粒度**，不在架构方向。

---

## 二、问题清单

### P1 · PNG 编解码逻辑重复 4 遍（234 行）

同一套 PNG chunk 构造 / CRC32 / zlib 压缩逻辑，在四个地方各写了一遍：

| 位置 | 函数 | 行数 |
|---|---|---|
| `editor/cw_core.py` | `encode_rgb_png` | 28 |
| `editor/cw_core.py` | `encode_indexed_png` | 51 |
| `tools/fix_theme_images.py` | `encode_png_rgb` | 19 |
| `tools/preview_clockface.py` | `png()` | 22 |
| `tools/fix_theme_images.py` | `decode_png` | 95 |
| `tools/check_theme.py` | `parse_png` | 19 |

**影响**：PNG 相关的坑（位深 1/2 会崩设备、单帧超 4096 字节）需要在 4 处同步修，漏一处就复发。
这次 `encode_indexed_png` 生成 1/2-bit 图导致设备闪退，就是因为它和 `encode_rgb_png` 是两套独立逻辑。

**方案**：抽出 `tools/pngkit.py`（纯标准库，无新依赖）

```
pngkit.py
├── encode_rgb(w, h, pixels, level=9)      # 8-bit RGB，设备唯一支持的格式
├── encode_indexed(...)                    # 保留，但标注「设备不支持 1/2-bit」
├── decode(raw) -> (w, h, [(r,g,b,a)])     # 完整解码
├── info(raw) -> (w, h, bitdepth, colortype)  # 只读 IHDR，给校验用
└── is_png(raw) / kind(raw)                # 签名判断
```

`editor/` 与 `tools/` 都 `import pngkit`。`editor` 是独立发布的 GUI，可以把它作为同级模块引用，或用 `sys.path` 注入。

**验证**：拿现有 33 个主题跑 `tools/fix_theme_images.py`，新旧实现输出**逐像素对比必须为 0 差异**（这次改造时已经验证过类似路径：39 帧、0 差异）。

**风险**：低。纯函数，无状态。

---

### P2 · 两个模块把实现全写在头文件里（398 行）

> **执行后修正**：原方案把 `WiFiSetupStateMachine.h` 也列为待拆项，这是错的。
> 它是纯逻辑状态机（无 Arduino 依赖），被 `test/test_native/` 的单元测试直接
> include，header-only 正是为了让原生测试无需链接即可运行。拆成 `.cpp`
> 会破坏可测性，因此**保持原样**。实际只拆了下面两个。

```
WiFiController.h         208 行  ← 含 WiFi 状态机、Improv 回调、AP 配网
StatusController.h       190 行  ← 含 LED、启动动画、屏幕提示（前 127 行是 PROGMEM 位图）
```

**影响**：
1. **编译耦合**：任何包含它们的 TU 都会重编。`main.cpp` 和 `CWWebServer.cpp` 都包含 `StatusController.h`，改一行 LED 逻辑就要重编这两个文件。当前全量编译 24~64 秒，增量编译也常到 20 秒以上。
2. **单例实现散落**：`static WiFiManager &wifiManager()` 这类函数内静态单例，在头文件里每处包含都有独立副本的语义风险（C++11 起 inline 保证唯一，但可读性差）。
3. `WiFiController.h` 反向依赖 `CWWebServer.h`（调 `startWebServer()`），头文件包含链变长。

**方案**：拆成 `.h`（声明）+ `.cpp`（实现），与已经拆好的 `CWWebServer` 保持一致。

```
WiFiController.h   208 → 46   声明 + extern improvSerial
WiFiController.cpp         190   实例定义 + 11 个方法
StatusController.h 190 → 27   仅 struct 声明
StatusController.cpp       181   位图数据 + 7 个方法
```

顺带修掉一处隐患：`ImprovWiFi improvSerial(&Serial);` 原来直接定义在头文件里，
只要有第二个编译单元包含就会重复定义，现改为 `.cpp` 定义 + 头文件 `extern` 声明。

**验证**：
- 编译通过 + Flash/RAM 变化在 ±1KB 内
- OTA 推送后设备全功能回归：配网、NTP 对时、设置页读写、主题切换、离线时钟
- 重点看 `StatusController` 的启动动画 —— 它依赖时序，拆文件不应改变调用顺序（纯搬运，不改逻辑）

**风险**：中。`StatusController` 有启动动画的时序依赖，`WiFiController` 有静态单例。做法是**纯搬运**（函数体原样移动，不改一行逻辑），不做任何"顺手优化"。

---

### P3 · 设置页 907 行全内联，JS 占 80%

```
SettingsWebPage.h   907 行 / 32,840 字节
├── CSS   5,316 字节
├── JS   26,191 字节   ← 80%
└── HTML  1,333 字节
```

当前做法：HTML + CSS + JS 全塞进一个 `const char*` 原始字符串，`tools/gzip_page.py` 用正则抽出 `<script>` 做语法检查、再 gzip 成 `SettingsWebPage_gz.h`。

**影响**：
- 编辑器里没有语法高亮、没有自动格式化、没有补全
- JS 错误只能靠 `node --check` 事后发现（这次 `requestGet` 的 204/200 不匹配就是这么漏掉的）
- 改动需要重跑 `gzip_page.py`，忘记跑就会用旧页面

**方案**：源码外置，构建时打包

```
firmware/web/
├── index.html      ← 结构
├── app.css
└── app.js
        ↓ tools/gzip_page.py（改造为资源打包器）
firmware/lib/cw-commons/SettingsWebPage_gz.h   ← 生成物（保持现有格式）
```

`gzip_page.py` 改成：读三个文件 → 内联成一个 HTML → gzip → 输出 C 数组。产物格式不变，`CWWebServer` 一行都不改。

**收益**：JS 能用 ESLint、能格式化、能拆分模块；产物完全等价。
**风险**：中。构建链多一层，要确保「忘记跑脚本」不会发生 —— 可以让 `platformio.ini` 的 `extra_scripts` 在编译前自动执行。

**这一项我建议缓做**：它改变最大、收益偏"开发者体验"，而当前页面功能是稳定的。等 P1/P2 完成后视情况再定。

---

### P4 · editor 两个巨型文件

```
canvas_designer.py  2,651 行   ← Tkinter GUI
cw_core.py          1,198 行   ← PNG 编解码 + 主题模型 + 预览渲染 + 固件校验
```

`cw_core.py` 一个文件承担了四种职责：图片处理、主题数据结构、预览渲染、固件二进制解析。改任何一处都要在 1200 行里找。

**方案**（在 P1 抽走 PNG 之后自然变小）：

```
cw_core.py    1,198 → ~700   主题模型 + 构建
pngkit.py              ~200   （P1 抽出）
preview.py             ~250   预览渲染
```

`canvas_designer.py` 的拆分收益较低（GUI 代码本身就是长），而且回归成本高（要点界面）。**建议不动**。

---

### P5 · 命名与组织的小不一致

| 现状 | 问题 | 建议 |
|---|---|---|
| `firmware/lib/native-mario/` | 从 `clockfaces/cw-cf-0x01` 复制改名，与 `custom-themes/canvas` 风格不一致 | 统一为 `firmware/themes/native-mario/` 和 `firmware/themes/canvas/` |
| `tools/` 6 个独立脚本 | `check_theme.py` / `fix_theme_images.py` / `preview_clockface.py` / `upload_themes.py` / `gzip_page.py` / `canvas_tool.py` | 可选：合成 `cwtool.py <子命令>`，共享参数解析 |
| `PNGRender.h` 153 行全是实现 | `.h` 后缀误导，实际是 `.cpp` 私有实现 | 改名 `PNGRender.cpp` |

**`PNGRender.h` 改名**成本极低（只改 `CanvasClockface.cpp` 的 include），建议随 P1 一起做。

---

## 三、不建议改动的部分

明确划出边界，避免过度重构：

| 模块 | 原因 |
|---|---|
| `IClockface` + 两个主题实现 | 接口只有 3 个方法，重复度低（一个是解释器、一个是硬编码），强行抽基类收益小于耦合成本 |
| `CWPreferences` | 22 个字段的扁平结构，加元编程抽象反而难读。上次已通过 `saveLastEpoch()` 解决了磨损问题 |
| `main.cpp` 的 `displaySetup()` | HUB75 面板配置是一次性代码，拆分只是搬家 |
| `cw-gfx-engine`（289 行） | 上游组件，且已经是清晰的小文件 |
| `canvas/THEME-SPEC.md` 等文档 | 内容准确，不需要动 |

---

## 四、建议执行顺序

| 批次 | 内容 | 风险 | 预计收益 | 建议 |
|---|---|---|---|---|
| **第 1 批** | P1 PNG 统一 + `PNGRender.h` 改名 | 低 | 消除 234 行重复，PNG 逻辑单点维护 | **建议做** |
| **第 2 批** | P2 三个模块拆 .h/.cpp | 中 | 增量编译时间下降，头文件依赖变浅 | **建议做** |
| **第 3 批** | P4 `cw_core.py` 拆分（P1 之后自然变小） | 中 | editor 可维护性 | 视需要 |
| **第 4 批** | P3 设置页外置 | 中高 | 前端可 lint、可格式化 | 缓做 |
| **第 5 批** | P5 目录与命名统一 | 低 | 一致性 | 可与任意批次合并 |

---

## 五、预期效果（量化）

| 指标 | 现状 | 优化后 | 依据 |
|---|---|---|---|
| PNG 编解码实现份数 | **4 份** | 1 份 | 234 行合并为 ~200 行单点 |
| 净减少重复代码 | — | **~180 行** | 234 − 新增 200 中的净差 |
| 头文件承载实现行数 | **567 行** | ~165 行（仅声明） | 三个模块拆出 |
| 全量编译时间 | 24~64 秒 | 预计 −15~25% | 头文件改动不再触发全量重编 |
| 设置页 JS 可 lint | ❌ | ✅（若做 P3） | 外置为 `.js` |
| 固件产物体积 | 1,685,377 B | 基本不变（±2KB） | 纯结构调整 |

**不变的部分**：所有功能、所有 HTTP 接口、NVS 存储格式、分区表、UI 行为。

---

## 六、验证策略（每批通用）

1. **编译**：`pio run -e esp32dev`，Flash/RAM 变化在预期内（±2KB）
2. **静态**：`node --check` 校验 JS，`py_compile` 校验 Python
3. **行为等价**：改造前的实现保留一份做对照，对同一输入比对输出
   （PNG 改造用 33 个主题做逐像素对比）
4. **设备回归**：OTA 推送后逐项确认
   - 设置页加载、参数读写
   - 主题列表、主题切换、预览
   - 原生/画布引擎切换
   - 离线时钟（断网 20 秒后的 7 段显示）
   - OTA 本身
5. **回退**：每批一个独立 commit，出问题 `git revert` 即可，不跨批混合

---

## 七、一句话总结

架构方向没问题，问题在**同一件事被实现了多次**（PNG 4 份）和**文件粒度粗**（567 行实现塞在头文件、907 行前端内联、1198 行工具模块）。

优先做 P1（消除重复）和 P2（拆头文件），收益明确、风险可控；P3（前端外置）改动最大但收益偏开发者体验，可以缓。

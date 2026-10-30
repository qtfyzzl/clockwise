# ClockWise Canvas 主题编辑器 · 技术手册（AI 版）

> 面向 AI 智能体的维护/操作参考。含实现细节、数据契约、接口、文件位置、边界与已知坑。
> **约束基线：THEME-SPEC.md（2026-10-29 设备端实测；仓库 `canvas/`，发行包 `docs/`）**，本手册与它冲突时以 THEME-SPEC 为准。
> 面向最终用户的操作说明见同目录 `使用说明书-用户版.md`。

---

## 0. 设备端硬约束速览（先看这一节）

### 0.1 图片（最容易把设备搞崩的地方）

| 项 | 要求 |
|---|---|
| 格式 | **PNG**（JPEG/BMP/GIF/WebP 都不认） |
| 位深 | **8 bit** |
| 颜色类型 | **2（RGB）或 6（RGBA）** 最稳；3（调色板）4/8-bit 一般可用 |
| **禁止** | **1-bit / 2-bit 索引色 PNG** |
| 尺寸 | 宽 ≤64、高 ≤64 |
| 单张体积 | base64 解码后 **≤4096 字节**（`IMAGE_BUFFER_SIZE`） |
| 隔行 | **不要隔行扫描** |
| 透明 | 支持；透明像素按主题 `bgColor` 处理，半透明按不透明处理 |

**为什么禁止 1/2-bit 索引色**：设备端 PNGdec 1.0.1 在位解包时有缺陷，会跳到空指针：

```
Guru Meditation Error: Core 1 panic'ed (Unhandled debug exception)
Debug exception reason: BREAK instr
EXCVADDR: 0xffffffe0
```

表现是**无限重启**；因为 `canvasFile` 指向该主题，重启后继续崩，设备出不来。
`snake-text.json`（旧版）就是 1/2-bit 索引色，已确认是此故障。

### 0.2 JSON

| 项 | 要求 |
|---|---|
| 整个 JSON | **≤16384 字节**（`DynamicJsonDocument doc(16384)`，超出解析失败） |
| 每个元素 | **必须有 `type`**（缺失会 `strcmp(nullptr)` 崩溃） |
| 可用 `type` | `text` `datetime` `image` `rect` `fillrect` `line` `sprite` |
| `loop[].sprite` | 必须在 `sprites` 下标范围内 |
| 坐标 `x`/`y` | 0~63 |
| 精灵总像素 | 帧数 × 宽 × 高 **建议 <40000**，超过易掉帧 |

---

## 1. 项目定位与产物

- **用途**：为 ClockWise（ESP32 + 64×64 HUB75E 点阵钟，固件 `jnthas/clockwise` 的 Canvas 主题引擎 cw-cf-0x07）生成 Canvas JSON 主题的桌面 GUI。
- **产物**：`editor/dist/ClockCanvasDesigner.exe`，单文件、免安装、无第三方运行时依赖（PyInstaller onefile + windowed）。
- **技术栈**：Python 3.8 + tkinter（GUI）+ Pillow（图像处理）。打包用 PyInstaller 5.13.2。
- **关键差异点**：编辑器**逐像素复刻固件渲染**——直接解析固件的位图字体 `.h`（hour8pt7b / minute7pt7b / atariFont / Picopixel + 经典 5×7），自己实现 `getTextBounds` 与 `drawChar` 的位读取算法，**不是**用系统字体近似。
- **编码输出**：图片一律输出 **8-bit RGB PNG**（经 `tools/pngkit.py`），绝不输出 1/2-bit 索引色。

---

## 2. 文件结构（`editor/` 目录）

| 文件 | 作用 |
|---|---|
| `cw_core.py` | 纯逻辑核心，无 GUI。渲染、字体、PNG 编码、图片压缩、精灵动画、校验、模板 |
| `canvas_designer.py` | tkinter GUI。所有窗口/对话框/交互 |
| `build_data.py` | 从固件字体 `.h` 提取位图 → 生成 `fontdata.json` |
| `fontdata.json` | 字体数据（构建产物，随 exe 打包进 `_MEIPASS`） |
| `build_exe.py` | 打包脚本（含图标生成；用 `--paths tools` + `--hidden-import pngkit` 把编码器打进 exe） |
| `test_core.py` | 核心库自检（纯逻辑，无需 GUI） |
| `test_ui.py` | 界面交互自检（会短暂弹窗，需桌面会话） |
| `icon.ico` | 程序图标（由 64×64 渲染结果生成） |
| `../tools/pngkit.py` | **运行时依赖**：8-bit RGB / 索引色 PNG 编码器。打包必须包含 |

---

## 3. 核心数据契约

### 3.1 固件限制（`cw_core.py` 顶部常量，校验器直接对齐）

```python
PANEL = 64                    # 屏幕 64×64
JSON_DOC_CAPACITY = 16384     # CanvasClockface.cpp: DynamicJsonDocument doc(16384)
JSON_SAFE_BYTES = 15000       # 留 ~1.4KB 余量（ArduinoJson 池按 token 计，非文件字节）
IMAGE_DECODE_LIMIT = 4096     # PNGRender.h: IMAGE_BUFFER_SIZE（上游 1024，定制固件提到 4096）
IMAGE_MAX_WIDTH = 64          # usPixels[64]
IMAGE_MAX_HEIGHT = 64
MAX_THEME_PIXELS = 40000      # 精灵总像素建议上限
```

> 历史坑：旧版曾写 `49152 / 46080 / 1024`，与当前固件不符，已全部改正。

### 3.2 主题 JSON 结构（与固件 cw-cf-0x07 一致）

```jsonc
{
  "name": "...", "version": 1, "author": "...",
  "bgColor": 0, "delay": 300,
  "setup": [ /* 静态元素，开机画一次，每秒刷新 datetime */ ],
  "sprites": [ [ {"image": "base64png"}, ... ] ],  // 精灵组 = 帧数组
  "loop": [ { "type":"sprite","sprite":0,"x":..,"y":..,"frameDelay":..,"loopDelay":..,
              "moveStartTime":..,"moveDuration":..,"moveTargetX":..,"moveTargetY":..,
              "shouldReturnToOrigin":false } ]
}
```

- `sprites` 是二维数组：`sprites[组][帧]`。
- `loop[].sprite` 指向组下标；固件用 `doc["loop"][spriteRef]` 读该组的 `frameDelay/loopDelay/位移参数`（下标按**精灵引用号**，不是 loop 序号）。
- 坐标 0~63；超出部分由屏幕裁剪。

### 3.3 setup 元素类型（6 种）

| type | 字段 |
|---|---|
| `text` / `datetime` | `content`(格式串) `font` `fgColor` `bgColor` `x` `y` |
| `rect` | `color` `x` `y` `width` `height`（空心） |
| `fillrect` | 同上（实心） |
| `line` | `color` `x` `y` `x1` `y1` |
| `image` | `image`(base64 PNG) `x` `y` |

`datetime` 的 `content` 用 **ezTime PHP 风格**格式符（不是 strftime）：`H:i`、`H:i:s`、`m-d`、`D, m/d`、`A`。

### 3.4 颜色 = RGB565 十进制

```
value = ((R>>3)<<11) | ((G>>2)<<5) | (B>>3)
```

### 3.5 图片格式硬约束（THEME-SPEC 摘要）

- 只接受 **PNG**；**8-bit、颜色类型 2/6** 最稳。
- **绝对不要 1-bit / 2-bit 索引色**（PNGdec 崩溃）。4-bit 调色板官方在用、一般可用，但不推荐。
- 宽/高 ≤64；解码后 ≤4096B；**不要隔行**。
- 透明像素按主题 `bgColor` 处理。
- 编辑器侧对应：`prepare_image()` 量化后统一 `.convert("RGB")` 再经 `pngkit.encode_rgb()` 输出 8-bit RGB；`encode_indexed_png()` 仅为旧脚本/测试保留，**不要用于生成上机主题**。

---

## 4. 关键算法实现（维护必读）

### 4.1 字体位读取（`cw_core.py: BitmapFont.pixels`）

复刻 `Adafruit_GFX::drawChar`：**MSB 先出，每 8 像素换一个字节**。

```python
bitmask = 0x80
for row in range(h):
    for col in range(w):
        if bo & bitmask: yield (col, row)
        bitmask >>= 1
        if bitmask == 0:
            bitmask = 0x80; idx += 1; bo = bitmaps[idx]
```

> 坑：早期实现用 `bitmask=1` 且不换字节，导致字形错乱，已修。改这里务必跑 `test_core.py` 的 `big 12:34 宽度==42` 断言。

### 4.2 文本包围盒（`text_bounds`）

复刻 `getTextBounds(text, 0, 0)`，返回 `(x1, y1, w, h, advance)`。注意 y1 常为负（字形有上偏移）。居中公式：
`x = (64-w)//2 - x1`，`y = (64-h)//2 - y1`。

### 4.3 8-bit RGB PNG 编码（`tools/pngkit.py`）

- `pngkit.encode_rgb(rgb_bytes, w, h)`：只输出 IHDR（color type 2、bit depth 8）/IDAT/IEND，**无 gAMA/EXIF 等附加块**，非隔行。
- `prepare_image()` 的流程是：缩放 → 调色板量化（ADAPTIVE，降低熵）→ `.convert("RGB")` → `encode_rgb`。量化只是为了压体积，**输出仍是真彩 8-bit**。
- 为什么不用浏览器 canvas 的 PNG：它只能出 32 位 PNG，体积压不下去；而低位深索引色会崩设备。`pngkit` 是这两者之间的唯一安全解。

### 4.4 图片压缩管线（`prepare_image`）

`压平透明(按 bgColor) → 缩放(_fit_image，mode 见下) → 调色板量化(ADAPTIVE) → 8-bit RGB PNG`。

`mode`：`contain`(不放大) / `fit`(等比放大) / `cover`(裁切填满) / `stretch`(拉伸)。

### 4.5 精灵动画模拟（`sprite_state` + `render_theme_animated`）

复刻固件 `handleSpriteAnimation` + `handleSpriteMovement`：

- **帧推进**：`within = t_ms % loopDelay`，`frame = within // frameDelay`（封顶 total-1）。
- **位移**：`moveDuration>0` 且 `(moveTargetX>-1 或 moveTargetY>-1)` 时，周期 `moveStartTime` 内前 `moveDuration` 走「去程」；`shouldReturnToOrigin` 则后 `moveDuration` 走「回程」。

真机行为差异（写动画时必须知道）：

1. **`renderImage(const char*, uint8_t x, uint8_t y)` 的坐标是 `uint8_t`**，而精灵内部是 `int8_t`。**x<0 会回绕成 200+，整块精灵直接不可见**（不是从左边裁掉）。所以不要设计"向左滑出屏幕"的位移。
2. 位移启用条件是 `(moveTargetX > -1 || moveTargetY > -1)`：**负目标会被当成"未设置"**；要负向移动只能让 `moveTargetY` 非负来通过判定。
3. 帧推进条件是 `_currentFrameCount < totalFrames`：**单帧精灵每 `loopDelay` 才推进一次**，位移类动画要把 `loopDelay/frameDelay` 设小（约 10ms），否则一步跨太大、擦除矩形会吃掉相邻精灵。
4. 帧计数重置条件是 `(currentSecond*1000) % loopDelay == 0`：`loopDelay` 必须是 1000 的因数/倍数，否则永不重置。
5. 擦除矩形 = 旧位置 ∪ 新位置；右移回程会擦到左邻精灵右边缘（绘制顺序 0..N）。

> 结论：**复杂的连续滚动/流动字，用「预渲染帧动画」最稳**（精灵固定 x/y，不参与位移），既绕开 1/2/3/5，又能精确控制每一帧。

---

## 5. GUI 结构与交互（`canvas_designer.py`）

### 5.1 主窗口 `Designer(tk.Tk)`

- 三栏：左（主题属性 + Notebook「元素/动画」标签页）、中（64×64 画布）、右（属性面板）。
- 布局用 `grid`（左 col0 宽 262 / 中 col1 expand / 右 col2 宽 320）。**注意**：左右栏子控件是 `pack` 的，锁宽度必须用 `pack_propagate(False)`（不是 grid_propagate，早期踩过坑）。
- `self.theme` 是当前主题 dict；`self.sel` 是选中的 setup 元素下标；`self.zoom` 画布缩放。
- 画布渲染：`render_theme` 出 64×64 → `resize` 到 `64*zoom` → `_compose`（叠加网格 + 选中框 + loop 标记，用独立 RGBA 层 `alpha_composite`，避免盖内容）→ `PhotoImage` 贴到 canvas。
- 动画播放：`anim_var` 勾选后 `_anim_tick` 每 40ms 用 `render_theme_animated(t_ms)` 重画；此时 `redraw()` 会短路跳过。

### 5.2 撤销/重做（`snapshot`）

`theme_to_json` 全量序列化存 `self.undo`（上限 80 条）。`snapshot(key)` 带 key 节流（0.9s 内同 key 只记一次）。

### 5.3 loop 实例画布拖拽

`_compose` 画标记：橙色方块=起点 `(x,y)`，绿色圆圈=目标 `(moveTargetX,moveTargetY)`，连线。
`_on_press` 里 `_hit_loop_marker` 优先命中；`_on_drag` 增量更新坐标。
> 依赖 `_sel_loop_entry()`；`_refresh_sprite_tab` 重建列表时**必须保留 selection**。

### 5.4 图片导入 `ImageDialog` + `CropDialog`

- `ImageDialog`：缩放/色数/抖动/平滑/适配 + 裁剪 + 多方案缩略图 + 实时体积（**阈值 4096B**）。
- `CropDialog`：tk.Canvas 拖框选，支持比例，`_select_all` 需先 `_fit()`。
- 多方案用 `gen_image_options`（6 尺寸 × 4 色数，去重排序，取 ≤4096B 前 10 个）。

---

## 6. 设备交互（HTTP 接口）

设备是自写 HTTP 服务（`firmware/lib/cw-commons/CWWebServer.h`），编辑器用 `urllib`：

| 路由 | 方法 | 说明 |
|---|---|---|
| `/get` | GET | 测试连通（204 + `X-*` 头） |
| `/themes` | GET | 纯文本，每行一个主题名 |
| `/theme?name=x` | POST | 上传（body=JSON，204=成功，自动设 canvasFile） |
| `/theme?name=x` | GET | 回读某主题 JSON |
| `/theme-delete?name=x` | POST | 删除 |
| `/rotate` | POST | 切下一个 + 重启 |
| `/restart` | POST | 重启 |

> 坑：① 设备开机 10 秒内（本地无主题时）会阻塞拉远程，不响应连接；② 上传后需重启才生效；③ 主题名仅 `[A-Za-z0-9_-]{1,40}`。

---

## 7. 构建 / 测试 / 打包

```bash
# 依赖：Python 3.8+（含 tkinter）、Pillow、PyInstaller
python editor/build_data.py   # 字体 .h → fontdata.json
python editor/test_core.py    # 核心库自检（无需 GUI）
python editor/test_ui.py      # 界面自检（会弹窗，需桌面会话）
python editor/build_exe.py    # 打包 dist/ClockCanvasDesigner.exe
```

`build_exe.py` 关键参数（**缺一不可**）：

```python
"--paths", os.path.join(ROOT, "tools"),   # 让 PyInstaller 找到 pngkit
"--hidden-import", "pngkit",              # 显式打入，防止 try/except import 被漏掉
"--add-data", "fontdata.json" + os.pathsep + ".",
```

> 环境注意：本项目实际用 `C:\Users\26541\AppData\Local\Programs\Python\Python38-32\python.exe`（含 tkinter）。默认的 workbuddy Python 3.13 无 tkinter。

---

## 8. 主题合规工具链（生成后必跑）

### 8.1 `tools/check_theme.py`（设备可运行性，权威）

```bash
python tools/check_theme.py canvas/themes/你的主题.json
```

检查：文件 ≤16384B、元素都有 `type`、PNG 是否 1/2-bit 索引色（直接判失败）、尺寸/单张体积、`loop[].sprite` 引用、精灵总像素。退出码 0=通过。

### 8.2 `tools/fix_theme_images.py`（救火）

```bash
python tools/fix_theme_images.py canvas/坏主题.json     # → 坏主题-fixed.json
```

把每帧解码后用 8-bit RGB 重编码（透明填 `bgColor`），像素级一致。已做好但位深不对的主题不用重画。

### 8.3 `canvas/theme.schema.json`（结构校验）

Draft 2020-12 JSON Schema，由 35 个官方主题反推校准。VS Code 里给主题加 `"$schema": "../theme.schema.json"` 可获得补全与报错。

| 能拦住 | 拦不住（需 check_theme.py） |
|---|---|
| 缺字段、类型错、多余字段 | 文件总大小 >16384 |
| `type` 拼错、坐标 >63 | 图片不是 PNG / 是 JPEG |
| 图片 base64 超上限 | 1/2-bit 索引色（会闪退） |
| `sprite` 下标为负 | base64 数据损坏 |
| 颜色 >65535 | `loop` 引用不存在的 sprite |

> schema 管"结构与值域"，`check_theme.py` 管"设备能不能真的跑起来"。上线前两个都过。

---

## 9. 已知边界与坑（改动前必读）

1. **1/2-bit 索引色 PNG 会让设备无限重启**——这是 `snake-text` 闪退的根因；编辑器只输出 8-bit RGB。
2. 图片解码后 **>4096B 设备静默不显示**（`renderImage` 不检查返回值）；编辑器在导入环节卡 4096B。
3. **JSON >16384B** 设备报 `Error! Check logs`；`validate()` 在 15000B 就提示精简。
4. 精灵总像素 >40000 会掉帧；校验器给 warn。
5. 精灵组各帧**尺寸要一致**（固件 `setDimensions` 用第一帧尺寸）。
6. `square` 字体 95 字形里 83 个是空的，只有数字可用。
7. 文字 x/y 是**基线起点**非左上角，y1 常为负。
8. 设备 IP 会变（DHCP），默认 `192.168.137.99` 存于 `~/.clockwise_canvas_editor.json`。
9. 不碰固件代码——本编辑器纯 PC 侧，通过 JSON + HTTP 交互。

---

## 10. 后续可扩展方向（供 AI 参考）

- 精灵帧序列**时间轴**（可视化每帧时长与切换点）
- 撤销历史**按操作分组**
- 多帧同尺寸**批量约束**
- 上传前**自动跑 `check_theme` 同款检查**并把结果弹窗（目前 `validate()` 已覆盖大部分）

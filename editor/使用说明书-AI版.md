# ClockWise Canvas 主题编辑器 · 技术手册（AI 版）

> 面向 AI 智能体的维护/操作参考。含实现细节、数据契约、接口、文件位置、边界与已知坑。
> 面向最终用户的操作说明见同目录 `使用说明书-用户版.md`。

---

## 1. 项目定位与产物

- **用途**：为 ClockWise（ESP32 + 64×64 HUB75E 点阵钟，固件 `jnthas/clockwise` 的 Canvas 主题引擎 cw-cf-0x07）生成 Canvas JSON 主题的桌面 GUI。
- **产物**：`editor/dist/ClockCanvasDesigner.exe`，单文件、免安装、无第三方运行时依赖（PyInstaller onefile + windowed）。
- **技术栈**：Python 3.8 + tkinter（GUI）+ Pillow（图像处理）。打包用 PyInstaller 5.13.2。
- **关键差异点**：编辑器**逐像素复刻固件渲染**——直接解析固件的位图字体 `.h`（hour8pt7b / minute7pt7b / atariFont / Picopixel + 经典 5×7），自己实现 `getTextBounds` 与 `drawChar` 的位读取算法，**不是**用系统字体近似。

---

## 2. 文件结构（`editor/` 目录）

| 文件 | 作用 |
|---|---|
| `cw_core.py` | 纯逻辑核心，无 GUI。渲染、字体、PNG 编码、图片压缩、精灵动画、校验、模板 |
| `canvas_designer.py` | tkinter GUI（约 2600 行）。所有窗口/对话框/交互 |
| `build_data.py` | 从固件字体 `.h` 提取位图 → 生成 `fontdata.json` |
| `fontdata.json` | 字体数据（构建产物，随 exe 打包进 `_MEIPASS`） |
| `build_exe.py` | 打包脚本（含图标生成） |
| `test_core.py` | 核心库自检（纯逻辑，无需 GUI） |
| `test_ui.py` | 界面交互自检（会短暂弹窗，需桌面会话） |
| `icon.ico` | 程序图标（由 64×64 渲染结果生成） |

---

## 3. 核心数据契约

### 3.1 固件硬限制（校验器直接对齐这些常量）

```python
PANEL = 64                    # 屏幕 64×64
JSON_DOC_CAPACITY = 49152     # DynamicJsonDocument(49152)，firmware Clockface.cpp:10
JSON_SAFE_BYTES = 46080       # 预留 3KB（ArduinoJson 按 token 计池，非文件字节）
IMAGE_DECODE_LIMIT = 1024     # IMAGE_BUFFER_SIZE，PNGRender.h:7
IMAGE_MAX_WIDTH = 64          # usPixels[64]，PNGRender.h:17
```

### 3.2 主题 JSON 结构（与固件 cw-cf-0x07 一致）

```jsonc
{
  "name": "...", "version": 1, "author": "...",
  "bgColor": 0, "delay": 300,
  "setup": [ /* 静态元素，开机画一次 */ ],
  "sprites": [ [ {"image": "base64png"}, ... ] ],  // 精灵组 = 帧数组
  "loop": [ { "type":"sprite","sprite":0,"x":..,"y":..,"frameDelay":..,"loopDelay":..,
              "moveStartTime":..,"moveDuration":..,"moveTargetX":..,"moveTargetY":..,
              "shouldReturnToOrigin":false } ]
}
```

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

### 4.3 索引色 PNG 编码（`encode_indexed_png`）

自写最小 PNG 编码器：按色数选位深（≤2→1bit，≤4→2bit，≤16→4bit，否则 8bit），只输出 IHDR/PLTE/IDAT/IEND，**无 gAMA/EXIF 等附加块**。这是图片能压进 1024B 的关键（浏览器 canvas 只能出 32 位 PNG，体积压不下去）。

### 4.4 图片压缩管线（`prepare_image`）

`压平透明(按 bgColor) → 缩放(_fit_image，mode 见下) → 调色板量化(ADAPTIVE) → 索引色 PNG`。

`mode`：`contain`(不放大) / `fit`(等比放大) / `cover`(裁切填满) / `stretch`(拉伸)。

### 4.5 精灵动画模拟（`sprite_state` + `render_theme_animated`）

复刻固件 `handleSpriteAnimation` + `handleSpriteMovement`：

- **帧推进**：`within = t_ms % loopDelay`，`frame = within // frameDelay`（封顶 total-1）。
- **位移**：`moveDuration>0` 且 `(moveTargetX>-1 或 moveTargetY>-1)` 时，周期 `moveStartTime` 内前 `moveDuration` 走「去程」；`shouldReturnToOrigin` 则后 `moveDuration` 走「回程」。

> **关键固件行为**：`_lastResetTime`/`_lastResetMoveTime` 初始为 0，所以**首次位移从 t=0 就开始**（不是等 moveStartTime）。编辑器按同规则模拟，故周期/速率一致，但真机上电时刻不同会导致起始相位偏差。

---

## 5. GUI 结构与交互（`canvas_designer.py`）

### 5.1 主窗口 `Designer(tk.Tk)`

- 三栏：左（主题属性 + Notebook「元素/动画」标签页）、中（64×64 画布）、右（属性面板）。
- 布局用 `grid`（左 col0 宽 262 / 中 col1 expand / 右 col2 宽 320）。**注意**：左右栏子控件是 `pack` 的，锁宽度必须用 `pack_propagate(False)`（不是 grid_propagate，早期踩过坑）。
- `self.theme` 是当前主题 dict；`self.sel` 是选中的 setup 元素下标；`self.zoom` 画布缩放。
- 画布渲染：`render_theme` 出 64×64 → `resize` 到 `64*zoom` → `_compose`（叠加网格 + 选中框 + loop 标记，用独立 RGBA 层 `alpha_composite`，避免盖内容）→ `PhotoImage` 贴到 canvas。
- 动画播放：`anim_var` 勾选后 `_anim_tick` 每 40ms 用 `render_theme_animated(t_ms)` 重画；此时 `redraw()` 会短路跳过（避免每秒 tick 覆盖动画帧）。

### 5.2 撤销/重做（`snapshot`）

`theme_to_json` 全量序列化存 `self.undo`（上限 80 条）。`snapshot(key)` 带 key 节流（0.9s 内同 key 只记一次）。拖拽等连续操作都走 `snapshot`。

### 5.3 loop 实例画布拖拽

`_compose` 画标记：橙色方块=起点 `(x,y)`，绿色圆圈=目标 `(moveTargetX,moveTargetY)`，连线。
`_on_press` 里 `_hit_loop_marker` 优先命中（返回 `(li,'start'|'target')`），`_on_drag` 增量更新坐标。
> 依赖 `_sel_loop_entry()` = `loop_tree.selection()`，因此 `_refresh_sprite_tab` 重建列表时**必须保留 selection**（已实现，否则拖一次就丢失选中，无法连续拖）。

### 5.4 图片导入 `ImageDialog` + `CropDialog`

- `ImageDialog`：缩放/色数/抖动/平滑/适配 + 裁剪按钮 + 多方案缩略图网格 + 实时体积。
- `CropDialog`：tk.Canvas 上拖框选，支持比例，`_select_all` 需先 `_fit()`（否则偏移未算）。
- 多方案用 `gen_image_options`（6 尺寸 × 4 色数 = 24 候选，去重后排序，取 ≤1024B 前 10 个展示）。

---

## 6. 设备交互（HTTP 接口）

设备是自写 HTTP 服务（`firmware/lib/cw-commons/CWWebServer.h`），编辑器用 `urllib` 直接请求：

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

> 环境注意：本项目实际用 `C:\Users\26541\AppData\Local\Programs\Python\Python38-32\python.exe`（含 tkinter）。默认的 workbuddy Python 3.13 无 tkinter。改字体 `.h` 后重跑 `build_data.py` 再打包。

---

## 8. 已知边界与坑（改动前必读）

1. **只编辑 setup + sprites + loop**，三者都支持。精灵动画预览是近似（见 4.5）。
2. 图片超 1024B 设备**静默不显示**（`renderImage` 不检查返回值）——编辑器在导入环节卡住 1024B。
3. 精灵组各帧**尺寸要一致**（固件 `setDimensions` 用第一帧尺寸），校验器已加 warn。
4. `square` 字体 95 字形里 83 个是空的，只有数字可用（`text_bounds("H")` 返回 w=0）。
5. 文字 x/y 是**基线起点**非左上角，y1 常为负。
6. 设备 IP 会变（DHCP），默认 `192.168.137.99` 存于 `~/.clockwise_canvas_editor.json`。
7. 不碰固件代码——本编辑器纯 PC 侧，与固件解耦，通过 JSON + HTTP 交互。

---

## 9. 后续可扩展方向（供 AI 参考）

- 精灵帧序列**时间轴**（可视化每帧时长与切换点）
- 撤销历史**按操作分组**（当前拖拽每步记一条）
- 多帧同尺寸**批量约束**（加帧时自动对齐第一帧尺寸）
- 上传前主题名**自动规整**（当前 `dev_upload` 已过滤非法字符，可再增强提示）

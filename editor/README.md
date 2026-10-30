# ClockWise Canvas 主题编辑器

给 ClockWise（ESP32 + 64×64 HUB75 点阵钟）做 Canvas JSON 主题的桌面编辑器。
**预览与设备逐像素一致**：直接解析固件的位图字体（`hour8pt7b` / `minute7pt7b` / `atariFont` / `Picopixel` / 经典 5×7），
自己复刻 `getTextBounds` 与 `drawChar`，不是用系统字体近似。

产物：`dist/ClockCanvasDesigner.exe`（单文件、免安装、无依赖）。

---

## 1. 为什么是 exe 而不是网页

HANDOFF 第 9 节原计划做纯前端 HTML。改成 exe 的原因：

| | 纯 HTML | 本 exe |
|---|---|---|
| 位图字体精度 | 要手抄 4 个 GFX 字体数据到 JS | 构建期从 `.h` 解析，永远和固件同步 |
| 图片量化/PNG 编码 | 浏览器 canvas 只能出 32 位 PNG，体积压不到 1KB | 自写索引色 PNG（1/2/4/8 位深，无冗余块） |
| 离线可用 | 打开本地文件即可 | 双击即可 |
| 上传设备 | 受 CORS 限制，需额外代理 | 直接 POST |

## 2. 用法

双击 `dist/ClockCanvasDesigner.exe`。界面三栏：

- **左**：主题属性（名称/作者/版本/延时/背景色）+ 元素列表（**列表顺序 = 绘制顺序**，越靠下越后画、盖住别人）
- **中**：64×64 画布。点选元素、直接拖动、方向键微调 1px；`网格` 开关；`模拟时间` 可以验证 `H:i:s`、日期等格式实际显示效果
- **右**：选中元素的属性。文字类元素有「水平居中 / 垂直居中」，按**真实字体度量**算，别手算

底部状态栏实时显示 **JSON 体积 / 16KB**、元素数、校验结果（红色=会出问题，黄色=提醒，点开看明细）。

常用快捷键：`Ctrl+Z/Y` 撤销重做、`Ctrl+D` 复制、`Del` 删除、`Ctrl+S` 保存、`Ctrl+U` 上传、`Ctrl+↑/↓` 调层级。

### 图片元素

`＋添加 → 图片`，或选中已有图片元素点「选择图片…」。导入对话框里：

- 最大宽/高（默认 32）、色数（2/4/8/16/32）、抖动、平滑缩放、适配方式（等比不放大 / 等比放大 / 裁切 / 拉伸）
- 左下角实时显示 **`宽x高 · 色数 · PNG 字节数`**，绿色=能放进设备，红色=超限，超限时「确定」是灰的
- 「自动压到 4096B 以内」会自动在尺寸×色数里搜一个体积达标、观感最好的组合
- **裁剪**：点「裁剪…」拖出选框，支持比例（1:1 / 4:3 / 16:9 等），也可「全图」
- **多方案选择**：底部自动列出多个「尺寸×色数」组合的缩略图，点一个直接用，不用手调参数

压缩链路：缩放 → 透明像素按背景色压平（设备端 `drawRGBBitmap` 没有透明度）→ 调色板量化 →
**8-bit RGB PNG 编码**（`tools/pngkit.py`，只保留 IHDR/IDAT/IEND，无 gAMA/EXIF，非隔行）。
输出始终是颜色类型 2、位深 8；**绝不输出 1/2-bit 索引色**（PNGdec 会崩）。一张 32×24 的图通常几百字节。

### 精灵动画（动态效果）

左栏「动画」标签页，管理固件的 `sprites[]` / `loop[]`：

- **精灵组**：一组 = 多帧图片（每帧都是压缩后的 PNG）。点「＋ 组」建组、「＋ 帧」往当前组加帧；
  帧预览里点某帧重新选图、双击删帧。
- **loop 实例**：引用一个精灵组，配置起始位置、帧延时 `frameDelay`、循环周期 `loopDelay`、
  位移触发 `moveStartTime`、位移时长 `moveDuration`、目标位置 `moveTargetX/Y`、是否往返
  `shouldReturnToOrigin`。
- **播放动画预览**：勾选后画布实时播放帧动画 + 线性位移，所见即设备所显（复刻固件
  `handleSpriteAnimation` / `handleSpriteMovement` 的 lerp 逻辑）。
- 菜单「文件 → 从模板新建 → 弹跳球动画」可直接看到效果。

### 上传到设备

工具栏填设备 IP → `测试`（打 `/get`）→ `上传`（`POST /theme?name=xxx`，成功后设备会把
`canvasFile` 指向它）→ 选「是」让设备重启生效。`读取` 走 `GET /theme?name=xxx`，可以把设备上
现有主题拉回来改。

> 上传别赶在设备开机 10 秒内：本地没有主题时它会阻塞去拉远程，期间 Web 服务不接连接。

## 3. 与固件实现的对应关系

| 编辑器 | 固件 |
|---|---|
| 文字渲染 | `Clockface::renderText`：`getTextBounds(text,0,0)` → 先 `fillRect(x+x1, y+y1, w, h, bgColor)` → 再打点 |
| 字形位图 | `Adafruit_GFX::drawChar`：MSB 先出，每 8 像素换字节 |
| 直线 | `Adafruit_GFX::drawLine` 的 Bresenham（含 steep 交换） |
| 矩形/实心矩形 | `drawRect` / `fillRect`，带裁剪 |
| 颜色 | RGB565：`((R>>3)<<11)｜((G>>2)<<5)｜(B>>3)` |
| 时间 | ezTime（PHP 风格 `H:i:s` / `m-d` / `D, m/d`），**不是 strftime** |

限制校验直接对着固件常量：`JSON_DOC_CAPACITY=16384`（`DynamicJsonDocument(16384)`）、
`IMAGE_DECODE_LIMIT=4096`（`IMAGE_BUFFER_SIZE`）、图片宽高 ≤64（`usPixels[64]`）、精灵总像素 <40000。

## 4. 已知边界

- **动画预览是近似**：`sprite_state()` 按理想时钟复刻固件的帧推进 + 位移逻辑，但固件里帧循环和位移触发
  都拿 `currentSecond*1000 % N` 对齐整秒、且 `_lastResetTime`/`_lastResetMoveTime` 初始为 0（首次位移从 t=0 就
  开始），编辑器按同规则模拟。设备上的实际相位可能因上电时刻有偏差，但周期/速率一致。
- **精灵位移不擦除旧位置**：编辑器预览直接逐帧重画整个画面（和固件 `fillRect` 擦除不同），观感一致但
  抗闪烁表现以真机为准。
- 预览的 `default`（font 留空）字体取自 `glcdfont.c` 的经典 5×7；若构建机没有该文件，会退回 picopixel 并在校验里提示。
- 设备端 `renderImage()` 不检查返回值，体积超限是**静默不显示**——所以编辑器把 4096B 卡在导入环节。
- 1/2-bit 索引色 PNG 会让 PNGdec 跳到空指针、设备无限重启；编辑器只输出 8-bit RGB。

## 5. 开发

```bash
# 依赖（Python 3.8+，需要 tkinter）
pip install pillow pyinstaller

python editor/build_data.py     # 从固件字体头文件生成 fontdata.json
python editor/test_core.py      # 核心库自检（颜色/字体/PNG/压缩/校验）
python editor/test_ui.py        # 界面交互自检（会短暂弹窗）
python editor/build_exe.py      # 打包 exe
```

改了固件字体（`firmware/custom-themes/canvas/fonts/*.h`）后重跑 `build_data.py` 再打包，
编辑器里的字宽字高就会跟着变。

文件：

| 文件 | 作用 |
|---|---|
| `cw_core.py` | 渲染核心：RGB565、GFX 字体、64×64 画布、索引色 PNG、图片压缩、校验、模板 |
| `canvas_designer.py` | tkinter 界面 |
| `build_data.py` | 字体数据提取器 |
| `build_exe.py` | 打包脚本（含图标生成） |
| `fontdata.json` | 生成产物，随 exe 打包 |
| `test_core.py` / `test_ui.py` | 自检 |

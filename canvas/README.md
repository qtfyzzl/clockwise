# Canvas 自定义界面指南（cw-cf-0x07）

> 面向 Clockwise v1.4.4 源码实测整理。所有结论都对照过 `firmware/clockfaces/cw-cf-0x07/` 的实现。

---

## 0. 先纠正一个前提：这块屏不是 OLED

Clockwise 驱动的是 **64×64 RGB LED 点阵屏（HUB75 / HUB75E）**，不是 OLED：

| | Clockwise 实际硬件 | 你提到的 OLED |
|---|---|---|
| 像素 | 64 × 64 | 常见 128×64 / 128×32 |
| 颜色 | RGB565，16 位真彩（65,536 色） | 单色（白/蓝/黄），1 位 |
| 驱动 | I2S DMA 并行刷屏（`ESP32-HUB75-MatrixPanel-I2S-DMA`） | I²C/SPI（SSD1306 / SH1106） |
| 亮度 | 整屏 PWM 调光 + LDR 自动亮度 | 对比度寄存器 |

所以要看你想做的是哪件事：

| 你的目标 | 该走的路 | 本目录是否适用 |
|---|---|---|
| 改这块点阵钟的界面外观 | **Canvas（本文档）** | ✅ 直接用 |
| 界面要精细控制、要动效性能 | C++ Clockface（`cw-cf-0x00` 模板） | 参考第 8 节对比 |
| 真的要接一块 OLED 屏 | 换显示后端，非配置项 | ❌ 见第 9 节成本 |

下面全部按「改点阵钟界面」来讲。

---

## 1. Canvas 是什么

Clockwise 的主题分两种存在形式：

- **编译期 C++ 主题**（cw-cf-0x01 ~ 0x06）：一个 C++ 类，随固件编译进去，换主题要重编 + 重烧。
- **运行期 JSON 主题**（cw-cf-0x07 Canvas）：固件里只有一个小型 JSON 解释器，界面描述放在远程 `xxx.json` 里，**改 JSON 不用重编固件**，重启即可生效。

Canvas 只做三件事：拉 JSON → 解析 → 按元素调用 Adafruit_GFX 画图。

---

## 2. 工作原理（源码级）

```
setup()  ──> drawSplashScreen("Downloading")
         ──> deserializeDefinition()
                ├─ 读 NVS: canvasServer / canvasFile
                ├─ WiFiClientSecure.setInsecure()      ← 不校验证书
                ├─ GET /<canvasFile>.json  HTTPS
                └─ deserializeJson(doc, ...)            ← DynamicJsonDocument(32768)
         ──> clockfaceSetup()
                ├─ fillRect 铺 bgColor
                ├─ renderElements(setup[])   ← 静态元素，只画一次
                ├─ refreshDateTime()         ← 画 datetime 元素
                └─ createSprites()

loop()   ──> clockfaceLoop()              ← 精灵动画/移动
         ──> 每 1000ms: refreshDateTime() ← 只重绘 datetime 元素
```

关键点：

1. **取文件只讲 HTTPS**，`client->setInsecure()` 意味着自签名证书可用。
2. **端口逻辑有硬编码**（`Clockface.cpp:311-318`）：

   | `canvasServer` 填什么 | 端口 | 实际请求路径 |
   |---|---|---|
   | `raw.` 开头（如 `raw.githubusercontent.com`） | 443 | `/robegamesios/clock-club/main/shared/<file>.json` |
   | 其他任意值（如 `192.168.1.20`） | **4443** | `/<file>.json` |

   ⚠️ 这行硬编码决定了：**你自己的 JSON 放不到自己的 GitHub raw 上**（路径会被改写成别人仓库）。要么本地起服务，要么给 `robegamesios/clock-club` 的 `shared/` 提 PR。

3. `doc` 是 `static DynamicJsonDocument doc(32768)` —— **32KB 静态内存**，这就是 Canvas 版本比 C++ 主题多吃 49KB RAM 的主因（实测：Mario 15.9% → Canvas 31.0%）。

---

## 3. JSON 结构

### 根对象

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 主题名（只打日志） |
| `version` | number | 版本（只打日志） |
| `author` | string | 作者（只打日志） |
| `bgColor` | number | 背景 RGB565 十进制 |
| `delay` | number | 默认帧/循环间隔 ms |
| `setup` | array | 启动时画一次的元素 |
| `sprites` | array | 二维数组：`sprites[精灵号][帧号].image` |
| `loop` | array | 精灵实例（位置、动画参数） |

### setup 元素类型

| type | 必填字段 | 对应 GFX 调用 |
|---|---|---|
| `datetime` | `content`(格式串) `font` `fgColor` `bgColor` `x` `y` | `print()` + 背景 `fillRect()` |
| `text` | `content` `font` `fgColor` `bgColor` `x` `y` | 同上（静态文本） |
| `rect` | `color` `x` `y` `width` `height` | `drawRect()` 空心 |
| `fillrect` | `color` `x` `y` `width` `height` | `fillRect()` 实心 |
| `line` | `color` `x` `y` `x1` `y1` | `drawLine()` |
| `image` | `image`(base64 PNG) `x` `y` | `drawRGBBitmap()` 逐行 |

`datetime` 的 `content` 用 **ezTime 的 PHP 风格格式符**（不是 strftime）：

| 写法 | 效果 | 示例 |
|---|---|---|
| `H:i` | 24 小时制 时分 | `14:07` |
| `h:i` | 12 小时制 | `02:07` |
| `H:i:s` | 带秒（每秒重绘，能走起来） | `14:07:33` |
| `m-d` | 月-日 | `10-28` |
| `D, m/d` | 周三 10/28 | `Wed, 10/28` |
| `A` | AM/PM | `PM` |

### sprites / loop

```json
"sprites": [
  [ {"image":"iVBOR..."}, {"image":"iVBOR..."} ],
  [ {"image":"iVBOR..."} ]
],
"loop": [
  {
    "type": "sprite",
    "sprite": 0,          // 引用 sprites[0]
    "x": 0, "y": 50,      // 初始位置
    "frameDelay": 200,    // 每帧时长 ms
    "loopDelay": 1000,    // 动画重新开始的周期 ms
    "moveStartTime": 2000,
    "moveDuration": 3000,
    "moveTargetX": 50, "moveTargetY": 50,
    "shouldReturnToOrigin": true
  }
]
```

---

## 4. 字体：实测尺寸 + 一个坑

Canvas 里 `font` 只认四个名字（其余/空字符串 = GFX 默认字体）。用 `tools/canvas_tool.py metrics` 可以算任意字符串的真实尺寸：

| `font` | 实际字体 | 字高 | 字符覆盖 | `"12:34"` 宽 | 居中 x |
|---|---|---|---|---|---|
| `big` | hour8pt7b | 14 px | 全 95 字符 | 42 | 11 |
| `medium` | minute7pt7b | 9 px | 全 95 字符 | 22 | 20 |
| `square` | atariFont | 11 px | ⚠️ **只有 12 个字符有字形** | 34 | 14 |
| `picopixel` | Picopixel | 5 px | 全 95 字符（空格为空） | 16 | 23 |

> ⚠️ **`square` 是个陷阱**：95 个字形里 83 个是空的，只有数字、冒号等少数符号有内容。
> 用它写 `"H:i"` 会几乎什么都看不到（实测包围盒只有 2×7 像素）。**它只能配纯数字时间**。

```bash
# 算你的字符串在该字体下的尺寸和居中坐标
python tools/canvas_tool.py metrics big "12:34"
```

---

## 5. 颜色：RGB565 十进制整数

JSON 里不能写 `#RRGGBB`，必须写 RGB565 的十进制值：

```
value = ((R >> 3) << 11) | ((G >> 2) << 5) | (B >> 3)
```

常用值：

| 颜色 | HEX | RGB565 十进制 |
|---|---|---|
| 黑（灭） | `#000000` | `0` |
| 白 | `#FFFFFF` | `65535` |
| 红 | `#FF0000` | `63488` |
| 绿 | `#00FF00` | `2016` |
| 蓝 | `#0000FF` | `31` |
| 黄 | `#FFFF00` | `65504` |
| 青（示例） | `#00C8C8` | `1625` |
| 暗灰线 | `#303030` | `12678` |
| 暗灰边框 | `#212121` | `8452` |
| 琥珀 | `#FFB000` | `64896` |

```bash
python tools/canvas_tool.py color "#1E90FF"     # 任意颜色换算
```

---

## 6. 图片与精灵的硬限制

| 限制 | 值 | 来源 |
|---|---|---|
| 单张 PNG 的**解码后字节数** | **≤ 1024 B** | `PNGRender.h:7` `IMAGE_BUFFER_SIZE` |
| 即 base64 字符串长度 | ≲ 1368 字符 | 1024 × 4/3 |
| 图片宽度 | ≤ 64 px | `PNGRender.h:17` `uint16_t usPixels[64]` |
| 整个 JSON | ≤ 32 KB（含所有 base64） | `Clockface.cpp:7` |
| 格式 | 必须是 PNG（不是 JPG） | `png.openRAM()` |

超限的后果：`renderImage()` **不检查返回值**，失败就静默不画，屏幕上什么都不出现，日志里也没有错误。所以图不显示时优先怀疑体积。

压缩建议：64×64 以内、纯色块多、导出时去掉所有元数据（EXIF/gamma/注释）。实在压不下去就用几何图形代替。

---

## 7. 本地调试完整流程

### 7.1 把固件的主题切成 Canvas

```bash
cd firmware/lib
# 删掉现有主题联接（当前是 mario 或 canvas）
cmd //c "rmdir mario"          # 按实际存在的目录名
cmd //c "mklink /J canvas ..\\clockfaces\\cw-cf-0x07"
```

> Windows 下不要用 `ln -s`，Git Bash 会建出一个空目录导致编译失败。用 `mklink /J`（不需要管理员权限）。

### 7.2 编译烧写

```bash
cd firmware
FW_NAME=Clockwise ~/.platformio/penv/Scripts/pio.exe run -e esp32dev -t upload
```

### 7.3 起本地 HTTPS 服务

固件只讲 HTTPS 且默认连 4443，所以要一个自签名 HTTPS 服务：

```bash
python canvas/serve-https.py
```

首次运行会自动用 openssl 生成 `cert.pem` / `key.pem`，然后打印本机所有 IPv4（内网地址排前面）。**选和 ESP32 同网段的那个**。

自测：浏览器打开 `https://127.0.0.1:4443/theme.json`，证书告警选「继续」。

### 7.4 在设置页填参数

浏览器打开 `http://clockwise.local`（或设备 IP），填两项：

- **[Canvas] Server Address**：`10.3.88.102`（你的内网 IP，**不要填 raw.xxx**）
- **[Canvas] Description file**：`theme`（不带 `.json`）

保存后重启设备。

### 7.5 看日志定位问题

串口 115200，正常会看到：

```
[Canvas] Building clockface 'Custom Minimal' by @you, version 1
```

失败时依次是这些信号：

| 屏幕显示 | 含义 |
|---|---|
| `Params werent set` | 两个 Canvas 参数有一个为空 |
| `Downloading` 卡住 | 连不上服务器 / 端口不对 |
| `Error! Check logs` | JSON 解析失败，看串口 `deserializeJson() failed: xxx` |

常见串口错误：

```
[HTTP] GET request to '10.3.88.102/theme.json' on port 4443
Connection failed                        → 防火墙 / 不在同网段 / 服务没起
deserializeJson() failed: EmptyInput      → 服务器返回空（404 或路径错）
```

---

## 8. Canvas vs C++ 主题：怎么选

| 维度 | Canvas（JSON） | C++（cw-cf-0x00） |
|---|---|---|
| 改界面要重编 | ❌ 不用 | ✅ 要 |
| RAM 占用 | 高（+49KB，静态 32KB JSON buffer） | 低 |
| 元素能力 | 只有矩形/线/文本/图/精灵 | 任意 GFX + 自己写逻辑 |
| 条件逻辑（if/循环/计算） | ❌ 完全没有 | ✅ |
| 动画 | 只能是帧序列 + 线性位移 | 任意 |
| 抗闪烁 | 元素重绘会闪烁（无帧缓冲） | 可自己控 |
| 调试成本 | 改 JSON + 重启，快 | 每次全量编译 ~60s |

**建议**：静态排版类界面（极简时钟、日期+时间+装饰）走 Canvas，改起来最快；要有天气图标动效、秒针旋转、条件显隐这类逻辑，直接写 C++，别跟 JSON 较劲。

---

## 9. 如果真要驱动 OLED

Canvas 帮不上，而且改动不小。要点：

1. `displaySetup()` 在 `firmware/src/main.cpp` 里是 HUB75 专用（`HUB75_I2S_CFG`、E 引脚、shift driver），要整个换掉。
2. `Locator::provide(display)` 传的是 `Adafruit_GFX*`，所以只要新驱动继承 `Adafruit_GFX`，**渲染层接口是兼容的**。
3. 但 Canvas 的 `image`/`sprite` 走 `drawRGBBitmap()`，SSD1306 没有这个 API（只有单色 `drawBitmap`），**图片相关能力全部失效**。
4. 颜色模型要重做：RGB565 → 单色阈值化。
5. 分辨率 128×64 ≠ 64×64，所有坐标、`StatusController` 里的居中文字（按 64 宽硬编码）都要重排。

工作量：做出能走时的 OLED 版本约 1~2 天；只借用它的 WiFi 配网 + NTP + 网页配置骨架、显示层自己重写，反而更省事。

---

## 10. 本目录文件

| 文件 | 用途 |
|---|---|
| `theme.json` | 可直接用的示例主题（极简风：边框 + 分隔线 + 大号时间 + 小日期），坐标已按真实字体宽度算好 |
| `serve-https.py` | 本地 HTTPS 调试服务器（4443，自签名，自动列内网 IP） |
| `cert.pem` / `key.pem` | 脚本自动生成的自签名证书，**仅本地调试**，别提交 |

配套工具在仓库根的 `tools/canvas_tool.py`：

```bash
python tools/canvas_tool.py color   "#00C8C8"      # 颜色 → RGB565
python tools/canvas_tool.py metrics big "12:34"    # 字体尺寸 + 居中坐标
```

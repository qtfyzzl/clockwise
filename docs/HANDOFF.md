# Clockwise 定制固件 — 交接文档

> 最后更新：2026-10-28 17:2x
> 本文件是跨会话的唯一上下文入口。新会话开始时，先读这个文件。

---

## 1. 一句话现状

用户有一台 **MonsterYuan 出品的 ClockWise Plus**（P3 64×64 点阵挂钟），跑的是 upstream `jnthas/clockwise` 固件 + 一套本地深度定制：**中文设置页、Canvas 主题引擎（存设备闪存、不依赖网络）、主题上传/删除/切换/自动轮盘、离线兜底**。

**当前设备状态**：正常运行，主题从 SPIFFS 本地加载。**已换到路由器 `R`**，IP **`192.168.6.21`**（DHCP 可能变，开机屏幕会显示 5 秒）。电脑也连在 `R` 上（192.168.6.55）。

> 🔑 **设置页地址：`http://192.168.6.21`**
>
> ⚠️ **改完 `SettingsWebPage.h` 必须重跑 `python tools/gzip_page.py`**
> 页面是以 gzip 形式发给浏览器的（32,446 → 11,885 字节），不重跑就是旧页面。

**设备里已预装 25 个可用主题**，SPIFFS 占用 160,891 / 836,081 字节（19.2%）。清单见第 5.3 节。

> ⚠️ **未完成的验证（2026-10-28 17:50 状态）**
> - JSON 缓冲已提到 48KB 的固件**已烧进设备并正常启动**（`PNG 缓冲就绪 size=48156 free=108732`，加载 mymelo-3 成功）。
> - 但 **8 个大主题（mario-1 / mario-1-moving / bugcat-1 / bugcat-2 / kuromi-3 / peach-1 / peach-gomo-22 / mymelo-1）还没上传成功** —— 上传途中设备 WiFi 掉线（ping 不通、ARP 里 MAC 还在、也没进 AP 模式），需要**断电重插一次**再补传。
> - 补传命令见第 7.2 节；`dist/_up2.txt` 里是 25 个普通主题，大主题用文件名单独传。
> - `canvasFile` 当前是 `mymelo-3`，建议重连后设回 `pac-man`。

---

## 2. 硬件

| 项 | 值 |
|---|---|
| 主控 | ESP32-D0WD-V3，MAC `88:57:21:b7:62:fc` |
| 面板 | **P3** 全彩 64×64，19.2×19.2cm，3mm 点距，**HUB75E**，1:32 扫描 |
| USB 串口 | CH340 → **COM6**（`VID:PID=1A86:7523`） |
| 光敏电阻 | GL5539 + 10K 分压，接 **GPIO35**（实测暗≈40，亮≈3700） |
| 供电 | 面板独立 5V/3A，与 ESP32 共地 |
| 来源 | MonsterYuan（GitHub `yuan910715`）的 ClockWise Plus，站点 `topyuan.top/clock` |

### ⚠️ 烧录必须先按住 BOOT

这块成品板 **RTS→EN 已接、DTR→IO0 未接**（省了两个三极管），所以 esptool 的自动复位进不了下载模式，必然报：

```
Wrong boot mode detected (0x13)
```

**唯一可行组合**：手动按住 `BOOT` 不放 + **默认复位模式**（不要加 `--before no-reset`）。

成功标志：串口出现 `boot:0x3 (DOWNLOAD_BOOT)` + `waiting for download`，屏幕黑掉。

---

## 3. 工具链

| 项 | 值 |
|---|---|
| PlatformIO | Core 6.2.0，在 `~/.platformio/penv/Scripts/pio.exe` |
| 平台 | espressif32 **8.0.0**，Arduino core **3.3.12**（IDF5，gcc 14.2.0） |
| 分区表 | `huge_app.csv`：app 3MB，**spiffs 896KB @0x310000**，NVS @0x9000 |
| esptool | v5.4.0，`~/.platformio/packages/tool-esptool/esptool.exe`。**子命令用连字符**：`write-flash` / `erase-flash` / `verify-flash` / `merge-bin` / `chip-id` / `read-mac` |

> Arduino core 3.x 比 upstream 当年用的 2.0.17 大很多，这是必须换 `huge_app` 分区的原因。

---

## 4. 目录结构（关键）

```
clockwise/
├── firmware/
│   ├── platformio.ini          # 关键配置都在这里，见下方说明
│   ├── src/main.cpp            # 入口 + 自动亮度 + 离线兜底 + 自动换盘
│   ├── lib/
│   │   ├── cw-commons/         # ★ 主要改动区
│   │   │   ├── CWWebServer.h        HTTP 服务 + SPIFFS 上传/删除/列表 + 主题切换
│   │   │   ├── SettingsWebPage.h    ★ 整个中文设置页（内联 CSS，17 张卡）
│   │   │   ├── CWPreferences.h      NVS 参数（含 autoRotate）
│   │   │   ├── WiFiController.h     非阻塞配网
│   │   │   ├── CWDateTime.h/.cpp    ezTime 封装
│   │   │   └── ...
│   │   ├── cw-gfx-engine/      # 图形引擎（Sprite::name() 在此修复）
│   │   └── canvas -> ../custom-themes/canvas     # junction，当前生效主题
│   ├── custom-themes/
│   │   ├── canvas/             # ★ Canvas 主题本地分支（改了 PNGRender）
│   │   └── adaptive/           # 自写的三档光照主题（当前未启用）
│   └── clockfaces/             # 官方主题 submodule（未修改）
├── canvas/
│   ├── themes/                 # ★ 下载的全部官方主题 JSON（34 个）
│   ├── serve-https.py          # 本地 HTTPS 4443 调试服务器
│   ├── pac-man.json / theme.json
│   └── README.md               # Canvas JSON 格式说明
├── dist/                       # ★ 烧录产物与工具
│   ├── flash.ps1               # 生产烧录脚本（按住 BOOT，分段烧录保 NVS）
│   ├── *.bin                   # 固件与合并镜像
│   ├── settings-preview.html   # 设置页离线预览
│   └── recovery.md / manual-flash.md
├── tools/
│   ├── canvas_tool.py          # 颜色 RGB565 换算 + 字体尺寸计算
│   └── preview_clockface.py    # 64×64 渲染预览（改几何前必跑）
├── hardware/WIRING.md          # 引脚表、LDR 电路、排障
└── docs/ARCHITECTURE.md        # upstream 架构文档
```

### 空中升级（OTA）

分区表用 `firmware/partitions_ota.csv`（不是 upstream 的 huge_app.csv）：

```
nvs 20K | otadata 8K | app0 1.81M | app1 1.81M | spiffs 256K | coredump 64K
```

两条通道，都不需要按 BOOT：

```bash
# 1. 命令行
pio run -e ota -t upload --upload-port 192.168.137.216

# 2. 设置页最下面「OTA 空中升级」选 dist/firmware.bin
```

实测（2026-10-29）：1.66MB 固件一次 20~33 秒，速度 52~85 KB/s，
两次分别写入 app1 / app0，SPIFFS 主题一个没丢。
上传中断会在 30 秒后 abort 并继续用旧分区，不会变砖。

⚠️ 注意：固件现在占 1.81MB 分区的 88.7%，只剩 215KB 代码空间。
再加功能要先看 `pio run -e esp32dev` 的 Flash 百分比。

### 主题是怎么"选中"的

> **2026-10-29 更新：这个"只能有一个"的限制已经解除了。**
> 现在原生主题和 Canvas 引擎同时编进固件，运行时按 NVS 的 `clockfaceEngine` 选择：
> `"canvas"`（默认，解析 JSON）/ `"native-mario"`（图片在 Flash，零内存）。
> 做法是给每个主题的类改名（`MarioClockface` / `CanvasClockface`）并把
> 两个 .cpp 里同名的全局 `lastMillis` 改成 `static`，冲突就没了。
> 加一个原生主题的实测成本：Flash +11.7 KB、RAM +272 B（余量 1.4 MB，还能加 5 个）。
> 设置页顶部有「主题引擎」下拉，切换后重启生效。
>
> 下面这段 junction 的做法**只在新增原生主题时**还需要用到。

历史做法：`firmware/lib/` 下只能存在**一个**提供 `Clockface` 类的目录（否则符号冲突）。切换方式是 junction：

```bash
cd firmware/lib
cmd //c "rmdir canvas"                                        # 删除旧联接
cmd //c "mklink /J canvas ..\\custom-themes\\canvas"          # 建新联接
```

> Windows 下**不要用 `ln -s`**，Git Bash 会建出一个空目录导致编译失败。用 `mklink /J`（不需要管理员权限）。

---

## 5. 已实现功能

### 5.1 中文设置页（`SettingsWebPage.h`）

- **完全自包含**：所有 CSS 内联，零外部依赖（原来靠 w3.css + Font Awesome 的 CDN，断网就变裸文字）
- UTF-8，17 张卡片分 4 组：显示 / 时间 / 硬件（高级）/ Canvas 主题
- 顶部固定栏显示固件版本、WiFi 名、当前主题
- 保存后底部 toast 提示「重启后生效」

### 5.2 Canvas 主题引擎（本地优先）

```
设备启动 → SPIFFS 有 /<canvasFile>.json ?
              ├─ 有 → 直接解析，不碰网络，开机秒出画面
              └─ 无 → 去 canvasServer 拉（4443 或 raw. 强制 443）
```

**已实测：关掉 PC 全部服务后重启，日志零网络请求。**

### 5.3 主题管理

| 功能 | 实现 |
|---|---|
| 上传 | `POST /theme?name=xxx`（Content-Length body，512B 缓冲分块写 SPIFFS）；上传后自动把 `canvasFile` 指向它 |
| 预览 | `GET /theme?name=xxx` 回读 JSON 原文；设置页在 128×128 canvas 里按 `setup` 数组实时渲染（背景色/文字/矩形/线/图片，精灵用淡色方块示意）。**字体是近似值**，布局配色准、字形不准 |
| 删除 | `POST /theme-delete?name=xxx`；设置页「删除当前主题」按钮 |
| 列表 | `GET /themes`（纯文本，每行一个名字），设置页下拉框自动填充 |
| 手动切换 | `POST /rotate` → 改 NVS + 重启；设置页「立即切到下一个」按钮 |
| 自动换盘 | NVS `autoRotate=1`，每天 **00:00** 切下一个（按名字字母序循环），用「一年中第几天」去重 |
| 占用显示 | `X-fsUsed` / `X-fsTotal`，页面画进度条 + 估算还能放几个 |

> **切换主题用「改 NVS + 重启」而不是热切换**：主题 `setup()` 会重读 JSON、重建精灵与 DMA 状态，热切换要拆解旧状态、容易留野指针。重启 2 秒，但干净。

### 5.3 已预装的主题（25 个，均在设备 SPIFFS 里）

```
amazon             christmassnoopy    cinnamoroll-1      clock-club
donkey-kong        eletrogate         goomba_move        hello-world
keqing-1           kuromi-1           kuromi-2           mymelo-3
nyan-cat           pac-man            peach-18           peach-20
peach-25           peach-gomo-1       peach-gomo-6       pepsi-final-2
retro-computer     sanrio-2           snoopy3            space-invaders
star-wars
```

本地 `canvas/themes/` 里共 **33 个**。**JSON 缓冲已提到 48KB（49152），全部 33 个都能装。**

早期用 16KB 缓冲时，有 8 个主题放不进去（mario-1 33KB、bugcat-1 40KB 等）。核算结果（`ArduinoJson` 需要把字符串复制进池，需求 ≈ 文件大小 + 5%）：

| 主题 | 文件 | 预估内存需求 |
|---|---|---|
| bugcat-1.json | 40,277 | 40,586 |
| mario-1.json | 34,438 | 34,773 |
| mario-1-moving.json | 34,301 | 34,596 |
| peach-1.json | 26,733 | 26,879 |
| bugcat-2.json | 21,010 | 21,071 |
| kuromi-3.json | 20,675 | 20,730 |
| peach-gomo-22.json | 18,557 | 18,758 |
| mymelo-1.json | 16,647 | 16,752 |

48KB 缓冲下最大占用 40.6KB，余量 18%。代价是空闲堆从 142KB 降到 **108KB**（启动日志 `PNG 缓冲就绪 size=48156 free=108732`）。

另外官方库里有个 `big-sample.json` 达 **8.4MB**（压力测试用），下载时已跳过。

批量上传清单在 `dist/_up2.txt`（已用 `tr -d '\r'` 修正过换行——python 在 Windows 写文件会自动转 CRLF，导致 curl 读不到文件）。

### 5.4 自动亮度（`main.cpp`）

- 10 档映射 + 迟滞（跨 2 档才写寄存器，防闪烁）
- 双端钳位（Arduino `map()` 不检查边界，低于下限会算出负数并回绕）
- 阈值复用设置页的「自动亮度 最小/最大」；`最大=0` 表示关闭
- 当前用户配置：`min=300 / max=1000 / 亮度上限 50`

### 5.5 离线兜底

WiFi 连不上时 `clockface->setup()` **永远不会被调用**（它挂在 `onNetworkReady`），所以兜底放在 `loop()` 里：30 秒未联网就自己画界面，每秒刷新。

- 时间可信（`time(nullptr) > 1700000000`）→ 大号 7 段时间 + 红字 `no wifi`
- 不可信 → `--:--` + `no wifi / no time`

> **不假装走时**：ESP32 无电池 RTC，掉电后是 1970，没有 NTP 就没有准确时间。

### 5.6 adaptive 主题（备用，未启用）

`firmware/custom-themes/adaptive/` —— 三档光照：亮 100% 正常界面 / 中 50% 正常界面 / 暗 25% **大数字模式**。数值用 7 段手绘（64×64 放不下 4 位大号字）。
启用方式：删 `lib/canvas` 联接，建 `mklink /J adaptive ..\custom-themes\adaptive`。

---

## 6. 修过的 bug（都在这个仓库里，别回退）

| # | 问题 | 根因 | 修法 | 位置 |
|---|---|---|---|---|
| 1 | 编译失败 `dsps_fft2r_platform.h not found` | PNGdec 1.1.6 的 `s3_simd_rgb565.S` 守卫是 `#ifdef ARDUINO_ARCH_ESP32`，对普通 ESP32 也成立 | 锁 `bitbank2/PNGdec@1.0.1` | `platformio.ini` |
| 2 | 链接失败 `vtable for Sprite` | `Sprite::name()` 只有声明没有定义（key function 缺失 → vtable 不生成） | 补默认实现返回 `"Sprite"` | `cw-gfx-engine/Sprite.cpp` |
| 3 | Flash 104.8% 超限 | core 3.x 镜像比 2.0.17 大 | `board_build.partitions = huge_app.csv` | `platformio.ini` |
| 4 | **烧完无限重启** `assert esp_startup_start_app` | `static PNG png;` 占 **48,156 字节 .bss**（PNGdec 把 32KB zlib 状态机塞在结构体里），静态内存 52KB→101KB，主任务栈分配失败 | 改 `new PNG()` 堆分配，且**在 WiFi 启动前的构造函数里**预分配 | `custom-themes/canvas/PNGRender.h` + `Clockface.cpp` |
| 5 | 图片/精灵全不显示 | 48KB 申请失败（32KB JSON doc 在静态初始化就占位，WiFi 再切碎堆） | JSON doc 32768→**16384** | `custom-themes/canvas/Clockface.cpp` |
| 6 | 设置页乱码 + 没样式 | ①`Content-Type` 缺 charset ②依赖外网 CDN | 加 `charset=utf-8` + 全内联 CSS | `CWWebServer.h` / `SettingsWebPage.h` |
| 7 | WiFi 名中文乱码 | SSID 走 HTTP 头，而 HTTP 头只能是 latin1 | 服务端 percent 编码 + 前端 `decodeURIComponent` | `CWWebServer.h` / `SettingsWebPage.h` |
| 8 | 画布配置组永不显示 | `CLOCKFACE_NAME` 宏只有 Canvas 主题定义了，cw-commons 独立编译看不到 → 恒为 `UNKNOWN` | 加成员变量 + `main.cpp` 运行时赋值 | `CWWebServer.h` / `main.cpp` |
| 9 | 自动亮度乱跳 | `map()` 无下限钳位，读数<下限时负数强转 uint8_t 回绕 | 双端钳位 + 阈值无效保护 | `main.cpp` |
| 10 | 烧录误报"校验失败" | `write-flash` 已做 hash 校验，脚本又单独跑 `verify-flash`（需重新进下载模式，松手就连不上） | 回读校验改「尽力而为」，失败只警告 | `dist/flash.ps1` |
| 11 | **设备"连上但不可达"、屏幕冻结、只能复位恢复** | `handleHttpRequest()` 的读循环 `while (client.connected())` **没有超时**。浏览器预连接、curl 超时中断、端口扫描器这些"连上但不发完整请求行"的行为，会让 `connected()` 恒为 true、`available()` 恒为 0 → 死循环卡住整个 `loop()`。lwIP 在独立任务里，所以 **ping 仍通但 HTTP 永不响应** | 加 2 秒 `requestDeadline`、空转时 `delay(1)` 让出 CPU、超时后清空 `httpBuffer` 再 `client.stop()` | `CWWebServer.h` |
| 12 | 自动换盘只生效一次 | `getFormattedTime("z")` 去重——ezTime 里 `z` 是**时区缩写**（`CST`），`toInt()` 恒为 0，`lastRotateDay` 永远等于 0，第二次就被判为"今天已经换过" | 改用 `getFormattedTime("Ymd")` 字符串去重 | `main.cpp` |
| 13 | 删除当前主题后重启停在报错页 | `theme-delete` 只删文件，`canvasFile` 仍指向它 | 删除后自动切到 `firstLocalTheme()` | `CWWebServer.h` |
| 14 | 慢客户端上传失败 | `client.setTimeout(5)` —— 单位是**毫秒**，5ms 读请求头几乎必然超时 | 改 1000ms | `CWWebServer.h` |
| 16 | **设置页加载不出来、切主题卡死** | ①页面 32KB 一次 `println` 发出，实测只有 255 B/s；②`client.write` 超时 1 秒，缓冲满时每块卡 1 秒，主循环被占死；③页面里 `/set` 和 `/theme` 并发，单连接服务器顶不住 | ①**gzip 预压缩**页面（32KB→11.9KB，浏览器解压，设备零成本）；②写响应 `setTimeout(150)` + 2048 块 + 缓冲满重试 + 总时限；③页面加请求队列 `qrun()` 串行化；④预览加缓存 | `CWWebServer.h` / `SettingsWebPage.h` / `tools/gzip_page.py` |
| 17 | WiFi 时通时不通、ping 仅 3/8、RTT 700~1300ms | 之前连的是 **Windows 移动热点**，极不稳定（每约 20 秒只有 3 秒可达）。后来发现连电脑的 WiFi 本身也掉了（169.254.x.x） | 用 **Improv Serial** 推路由器凭据，设备改连 `R`；PC 用 netsh 连回 `R`。链路：RSSI -34dBm、省电模式 0，但吞吐仍只有 ~3KB/s（丢包重传，属链路层） | `WiFiController.h` |

---

## 7. 日常操作手册

### 7.1 编译 + 烧录

```powershell
cd C:\Users\26541\WorkBuddy\clockwise\firmware
~/.platformio/penv/Scripts/pio.exe run -e esp32dev          # 编译

cd ..\dist
.\flash.ps1                                                 # 烧录（按住 BOOT 不放）
```

`flash.ps1` 参数：`-Port COM6`（默认）、`-Erase`（整片擦除，会清 NVS/WiFi）、`-Merged`（单文件烧 0x0，救砖用）、`-Baud`、`-TimeoutSec`。

**默认是分段烧录**（bootloader@0x1000 / partitions@0x8000 / boot_app0@0xe000 / app@0x10000），**不覆盖 NVS**，所以 WiFi 和设置会保留。

### 7.2 上传主题

```bash
# 命令行
curl -X POST --data-binary "@canvas/themes/pac-man.json" \
  -H "Content-Type: application/json" \
  "http://<设备IP>/theme?name=pac-man"
```

或设置页 → Canvas 主题 → 「上传主题到设备」选文件。**上传完要重启生效。**

> ⚠️ 上传别赶在开机 10 秒内：设备启动时如果本地无主题，会阻塞约 10 秒去连远程，期间 Web 服务不接连接，curl 会超时。

### 7.3 查看状态

```bash
curl http://<IP>/themes            # 列出设备上的主题
curl -D - -o /dev/null http://<IP>/get | grep ^X-   # 全部配置
```

串口日志 115200，关键行：`[FS] SPIFFS 就绪`、`[Canvas] 本地主题已加载`、`[Canvas] PNG 缓冲就绪`。

### 7.5 换 WiFi（不用擦除、不用按 BOOT）

设备的 Improv Serial 一直在监听，可以直接从串口推凭据：

```python
# 帧: "IMPROV" + ver(1) + cmd(1) + len(2,大端) + data + checksum(1字节和)
data = bytes([len(ssid)]) + ssid.encode() + bytes([len(pass)]) + pass.encode()
frame = b"IMPROV" + bytes([0x01, 0x01]) + len(data).to_bytes(2,"big") + data
frame += bytes([sum(frame) & 0xFF])
```

要点：
- 必须用 **platformio 的 python**（系统 python 没装 pyserial）
- 打开串口后立刻 `setDTR(False); setRTS(False)`，否则 DTR/RTS 会把设备复位
- 发完设备会自动切换并打印新 IP

### 7.4 HTTP 接口一览

| 路由 | 方法 | 说明 |
|---|---|---|
| `/` | GET | 中文设置页 |
| `/get` | GET | 204 + 全部配置在 `X-<key>` 响应头 |
| `/set?k=v` | POST | 写单个参数（**服务端不做 URL 解码**，值原样传） |
| `/themes` | GET | 纯文本，每行一个本地主题名 |
| `/theme?name=x` | POST | 上传主题（body 为 JSON） |
| `/theme-delete?name=x` | POST | 删除主题 |
| `/rotate` | POST | 切到下一个主题并重启 |
| `/read?pin=n` | GET | 读 ADC，返回 `X-pin: 值` |
| `/restart` | POST | 重启 |

---

## 8. 已知限制（**改代码前必读**）

| 限制 | 数值 | 含义 |
|---|---|---|
| 主题 JSON 大小 | **≈46KB**（`DynamicJsonDocument doc(49152)`） | 实测最大主题 bugcat-1 需 40.6KB。再大就得调缓冲，但会挤占堆（当前空闲 108KB） |
| 单张图片 | base64 解码后 **≤1024 字节**、宽 ≤64px、必须 PNG | `IMAGE_BUFFER_SIZE 1024`。64×64 全彩图基本压不进，官方主题里的图都是 5×5、64×10 这种小图 |
| 堆 | 启动时 PNG 缓冲已占 48KB，`free≈142KB` | 不要在后加更大的静态/堆分配 |
| 无逻辑能力 | Canvas 不支持 if / 循环 / 计算 | 整点闪烁、多页面轮播、秒针都做不了，要写 C++ 主题 |
| 无帧缓冲 | 元素直接写屏 | 动效可能闪 |
| 主题名 | 只能 `[A-Za-z0-9_-]`，≤40 字符 | 上传接口的校验 |
| 端口约定 | `canvasServer` 以 `raw.` 开头 → 443 且路径被强制改写成 `robegamesios/clock-club/main/shared`；其他 → **4443** | 想用 Gitee/OSS 必须先改 `deserializeDefinition()` |

---

## 9. 待办：图片编辑器（用户已确认要做，形态待定）

**结论：做成 PC 端纯前端 HTML，不占设备存储。**

- 设备只存导出的主题 JSON（pac-man 2.8KB，896KB 约可放 260 个）
- 若做进固件要几百 KB，app 分区只剩 96KB 余量，不可行

建议路径（未开工）：
1. `canvas/designer.html` 单文件，浏览器直接打开，无需服务器
2. 64×64 网格画布，拖拽放置 text / datetime / rect / fillrect / line / image
3. 图片上传 → 自动缩放到 ≤32×32、调色板量化到 ≤8 色、**实时显示压缩后体积**（必须 <1024B）
4. 实时预览 + 校验 JSON 体积（<16KB）
5. 导出 JSON / 一键 POST 到 `/theme?name=xxx`

技术难点是**图片压缩**，不是画布本身：64×64 全彩 PNG 压不进 1KB，必须限制尺寸 + 量化调色板。

---

## 10. 踩坑速查

| 现象 | 原因 | 处置 |
|---|---|---|
| **设备突然 ping 不通 / 进不去设置页，但串口显示 `[WiFi] Connected` 正常** | ESP32 WiFi 省电模式（modem sleep）：设备长时间睡觉不收发包，Windows 热点把它的转发表项丢掉。实测模式：连上后几秒可达 → 失联约 100 秒 → 偶尔通几秒，串口无任何断开事件 | 固件已在 `onConnected()` 里加 `WiFi.setSleep(false)`（烧录 52.2% 版本起生效）。**注意：每次打开串口都会复位设备**（DTR/RTS 接着 EN），复现问题时先想想是不是自己刚开过串口 |
| `Wrong boot mode detected (0x13)` | 没进下载模式 | 按住 BOOT 不放，用默认复位，**别加 `--no-reset`** |
| 烧录 `Could not open port` | 串口被占 | 关掉串口监视器；等 1 秒让 esptool 完全退出 |
| `assert esp_startup_start_app` 重启循环 | 静态 RAM 爆了 | 看 `xtensa-esp32-elf-nm --size-sort` 最大的 `b`/`d` 符号 |
| 屏幕黑但串口正常 | 面板排线没插稳 / 电源 | 重插排线，查 5V |
| 主题显示 `Error! Check logs` | JSON 拉取或解析失败 | 看串口 `deserializeJson() failed:`；确认 JSON <16KB |
| 上传 curl 超时 `http=000` | 设备正在启动时阻塞拉远程 | 等开机 15 秒后再传 |
| **页面加载半天、转圈不出来** | 链路吞吐过低（实测 ~3KB/s）。页面已 gzip 压到 11.9KB | 先看串口 `[WiFi] RSSI=`：>-75 说明信号没问题，是丢包重传；再看 `省电模式` 是否为 0 |
| **改了设置页但浏览器看到旧内容** | 忘了重跑 gzip 脚本 | `python tools/gzip_page.py` 后重新编译烧录 |
| 设备 ping 通 3/8、RTT 上秒 | 连的是 Windows 移动热点 | 用 Improv Serial 推路由器凭据（见第 7.5 节） |
| 设置页样式全丢 | 又引入了外网 CDN | 所有 CSS 必须内联 |
| 中文变 `å¼ å­ç` | 响应头没做 percent 编码 | 见 bug #7 |

---

## 11. 当前未提交的改动

仓库**没有 commit**（按项目规范：改动留在工作区供审阅）。`git status` 会看到：

- 修改：`firmware/platformio.ini`、`firmware/src/main.cpp`、`cw-commons/*`（3 个）、`cw-gfx-engine/Sprite.cpp`
- 新增：`firmware/custom-themes/`、`canvas/`、`dist/`、`tools/`、`hardware/`、本文件

要提交时建议开分支（不要直接进 main），主题 submodule 未改动。

---

## 12. 新会话怎么接上

1. 读本文件（尤其第 6、8、10 节）
2. `cd C:\Users\26541\WorkBuddy\clockwise`，确认 `firmware/lib/` 里当前是哪个 junction（`ls -ld firmware/lib/*`）
3. 设备 IP 会变，从串口日志或路由器后台查
4. **改任何 64×64 布局数值前，先跑 `tools/preview_clockface.py` 出图核对**——这个脚本已经抓出过两次几何错误（不居中、超屏被裁）
5. 改完必须编译验证；涉及设备的改动要用串口日志或 HTTP 接口实测，不能只看"编译通过"

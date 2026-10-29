# 烧录包（基线验证版）

**版本**：Clockwise v1.4.4（本地修正版）
**主题**：Mario（cw-cf-0x01）—— **零外部依赖**，不需要联网拉主题 JSON，配好 WiFi 就能看
**用途**：先把硬件跑起来确认状态，再据此改自定义功能

| 项 | 值 |
|---|---|
| RAM | 52,016 / 327,680（15.9%） |
| Flash | 1,373,064 / 3,145,728（43.6%） |
| 分区表 | `huge_app.csv`（3MB app，NVS 在 0x9000 与官方一致 → **原有 WiFi 配置不会丢**） |
| 日志级别 | `CORE_DEBUG_LEVEL=3`（串口能看到实际生效的引脚） |

---

## 文件说明

| 文件 | 烧录地址 | 说明 |
|---|---|---|
| `clockwise-v1.4.4-mario-merged.bin` | **0x0** | 合并镜像，一次搞定，最省事 |
| `bootloader.bin` | 0x1000 | 分散烧录用 |
| `partitions.bin` | 0x8000 | |
| `boot_app0.bin` | 0xe000 | |
| `firmware.bin` | 0x10000 | 应用本体 |

---

## 方式 A：PlatformIO（推荐，自动找端口）

```bash
cd firmware
~/.platformio/penv/Scripts/pio.exe run -e esp32dev -t upload
```

或在 VS Code 里点底部状态栏的 **→ (Upload)** 按钮。

---

## 方式 B：合并镜像，单文件烧到 0x0

先查串口（`pio device list`），把 `COM5` 换成你的实际端口：

```bash
~/.platformio/packages/tool-esptool/esptool.exe \
  --chip esp32 --port COM5 --baud 921600 \
  write-flash -z 0x0 dist/clockwise-v1.4.4-mario-merged.bin
```

或者直接用 `dist/flash.bat COM5`。

### 想彻底清空（含旧 WiFi 配置）

烧之前先用同一端口擦一次：

```bash
~/.platformio/packages/tool-esptool/esptool.exe --chip esp32 --port COM5 erase-flash
```

> ⚠️ `erase-flash` 会连 NVS 一起擦掉，之后必须重新配网。如果你的成品**已经配过 WiFi**，不建议擦，直接烧 merged 即可沿用旧配置。

---

## 方式 C：ESP Flash Download Tool（图形界面）

乐鑫官方工具，四个文件分别填地址：

```
bootloader.bin  ->  0x1000
partitions.bin  ->  0x8000
boot_app0.bin   ->  0xe000
firmware.bin    ->  0x10000
```

---

## 烧完后应该看到什么

1. 板载 LED（GPIO2）闪 5 次
2. 屏幕亮起，显示 Clockwise 的 Logo（约 1 秒）
3. 出现 WiFi 连接提示
4. 连上后显示 "NTP syncing"，然后进入 Mario 时钟界面

### 如果没连过 WiFi

会进入配网模式，手机会看到一个热点 **`Clockwise-Wifi`**：

- 连上它 → 自动弹出配置页（或手动开 `192.168.4.1`）
- 选你的 2.4GHz WiFi、填密码 → 保存
- 配网门户 5 分钟没操作会自动重启

> ESP32 **不支持 5GHz**，只认 2.4GHz。

### 连上之后

同一局域网打开 `http://clockwise.local`（或设备 IP）就能进设置页：
时区、亮度、旋转、主题、RGB 线序、驱动 IC、E 引脚、LDR 自动亮度都在这里。

---

## 串口日志能帮你确认什么

115200 波特率。因为开了 `CORE_DEBUG_LEVEL=3`，能看到实时生效的引脚：

```
I (xxx) begin(): Using GPIO 25 for R1_PIN
I (xxx) begin(): Using GPIO 26 for G1_PIN
...
I (xxx) begin(): Using GPIO 18 for E_PIN
```

对照 `hardware/WIRING.md` 的引脚表，能立刻判断接线和配置是否一致。

---

## 请重点确认这几件事（决定我下一步怎么改）

| 检查项 | 正常表现 | 异常说明 |
|---|---|---|
| 整屏是否完整点亮 | 64×64 全亮，无半屏/隔行 | 隔行或只亮一半 → **E 引脚**问题（默认 GPIO18） |
| 颜色是否正确 | 红是红、蓝是蓝 | 偏色 → 试设置页 `swapBlueGreen`（一次只开一个） |
| 是否有花屏/闪烁 | 画面稳定 | 换驱动 IC（FM6124/ICN2038S 等）+ 检查电源 5V≥3A 与共地 |
| 亮度是否够 | — | 亮度上限受电源电流限制 |
| 配网是否顺利 | 门户能打开、能保存 | — |
| 时间是否正确 | NTP 同步后走时准 | 时区选 `Asia/Shanghai` |

---

## 这一版的限制（也就是下一步要改的）

Mario 是**编译期固定主题**，除了设置页那几个参数，界面本身改不了——这正是你说的"自定义能力不够"。

下一版的方向取决于你要什么，常见几类：

1. **改现有主题的布局/字体/颜色** → 写自定义 C++ 主题（想要什么就能画什么）
2. **要能随时改、不重烧** → Canvas（JSON 主题），但需要一台常开的机器提供 HTTPS 4443
3. **多页面轮播**（时间 ↔ 天气 ↔ 日期） → 需要加逻辑，Canvas 做不了
4. **接传感器显示**（温湿度/空气质量） → 加驱动 + 数据源
5. **秒针/动效** → C++ 才能流畅

告诉我你具体想显示什么、要什么交互，我按那个方向改。

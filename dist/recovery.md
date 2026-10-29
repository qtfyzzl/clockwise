# 救砖 / 强制烧录指南

## 当前状态

串口实测（115200）：

```
rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)
E (488) esp_image: invalid segment length 0xffffffff
E (488) boot: OTA app partition slot 0 is not bootable
E (488) boot: No bootable app partitions in the partition table
rst:0x3 (SW_RESET),boot:0x13 ...
```

- `0xffffffff` = 擦除态 → **app 分区是空的**，分区表还在但不可引导 → 芯片无限重启
- **硬件没坏**：ROM bootloader 正常、串口正常、Flash 可读写
- 屏幕/指示灯异常都是这个重启循环导致的

## 诊断结论（重要）

| 信号线 | 状态 | 证据 |
|---|---|---|
| CH340 **RTS → EN** | ✅ 已接 | 每次 esptool 尝试都成功复位并读回 boot 值 |
| CH340 **DTR → IO0** | ❌ 未接 | 恒为 `boot:0x13`（正常启动），从未出现 `0x3` |

结论：**自动进入下载模式在硬件上不可能**，必须手动把 IO0 拉低。

---

## 方案 A：找到 IO0 并保持低电平（首选）

### IO0 在哪

1. **看丝印**：`IO0` / `IO0` / `D0` / `BOOT` / `FLASH`
2. **看 BOOT 按键**：BOOT 键的一端就是 IO0，另一端是 GND
   → 用镊子**跨接按键的两个引脚**，等于"永久按住"，比手指可靠
3. **找测试点**：成品板常把 IO0 留成一个裸露焊盘，标注 `TP` 或 `P0`

### 操作

```
1. 镊子跨接 IO0 与 GND（保持不动）
2. 保持跨接的同时，拔插一次 USB 上电
3. 串口应出现：  waiting for download
4. 保持跨接，执行烧录
```

**验证成功**：串口打印 `boot:0x3 (DOWNLOAD_BOOT...)` + `waiting for download`，且屏幕保持黑、不再重启。

---

## 方案 B：USB-TTL 直连（一定能成）

如果你的板子完全找不到 IO0，用任意 CH340 / CP2102 / FT232 模块绕过板载电路：

```
USB-TTL 模块        ESP32
─────────────────────────────
TX      ────────►   RX  (GPIO3)
RX      ────────►   TX  (GPIO1)
GND     ────────►   GND
DTR     ────────►   IO0
RTS     ────────►   EN
3V3     ────────►   不接（ESP32 用自身 USB 供电）
```

接好后 esptool 的自动复位就能正常工作，一次烧通。

> 注意：模块必须是 **3.3V 电平**。5V 的 USB-TTL 会打坏 ESP32。

接好后端口会变成新模块的 COM 号，先 `pio device list` 确认。

---

## 烧录命令（两种都行）

### 方式 1：单文件合并镜像

```bash
~/.platformio/packages/tool-esptool/esptool.exe \
  --chip esp32 --port COM6 --baud 460800 \
  write-flash -z 0x0 dist/clockwise-v1.4.4-mario-merged.bin
```

**不要加 `--before no-reset`** —— 实测加了反而必然失败（芯片不会复位，永远等不到 bootloader）。

### 方式 2：PlatformIO

```bash
cd firmware
~/.platformio/penv/Scripts/pio.exe run -e esp32dev -t upload --upload-port COM6
```

---

## 烧录成功的标志

```
Connecting....
Chip is ESP32-D0WD-V3 (revision v3.1)
MAC: xx:xx:xx:xx:xx:xx
Wrote 1476112 bytes at 0x00000000 ...
Hash of data verified.
Hard resetting via RTS pin...
```

之后屏幕亮起，串口打印：

```
Using GPIO 25 for R1_PIN
...
Using GPIO 18 for E_PIN
```

## 烧完之后

- NVS 在 0x9000，本次只擦了 app 区，**如果之前配过 WiFi 会保留**；没保留就重新配（热点 `Clockwise-Wifi`）
- 设置页：`http://clockwise.local`

---

## 附：为什么之前的尝试都失败

| 尝试的组合 | 结果 | 原因 |
|---|---|---|
| 默认复位 + 按一下 BOOT 松开 | `0x13` | 松手太早，esptool 复位那一刻 IO0 已是高 |
| `--before no-reset` + 按键 | `No serial data` | 不复位，芯片自己在重启，抓不到 bootloader |
| `chip-id` 探测后再烧 | `No serial data` | `chip-id` 结束时会硬复位，把芯片踢出 bootloader |
| **默认复位 + IO0 持续短接** | ✅ 唯一可行 | 复位瞬间 IO0 为低 → 进下载模式 |

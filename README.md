# Clockwise 智能挂钟 · 中文指引

> 本仓库在 [jnthas/clockwise](https://github.com/jnthas/clockwise) 1.4.4 基础上定制：双主题引擎、中文设置页、空中升级、离线兜底。
> 完整使用说明见 [`使用说明.md`](使用说明.md)，下方是**最常用的烧录方法**。

---

## 快速烧录（不用搭编译环境）

固件已经编译好放在 `dist/` 里，直接烧录即可，无需安装 PlatformIO。

### 需要准备

- 一根 **数据线**（不是纯充电线），接 ESP32 的 USB 口
- 开发板上的 **BOOT 键**（烧录全程要按住）

### 方法一：双击 bat（最简单）

1. 进入 `dist/` 目录
2. 双击 `flash.bat`（弹窗确认即可）
3. 窗口提示后**按住 BOOT 键不放**，直到显示「写入成功」再松手

### 方法二：PowerShell（可指定串口）

```powershell
cd dist
.\flash.ps1                # 默认 COM6，波特率 460800
.\flash.ps1 -Port COM8     # 指定串口
.\flash.ps1 -Baud 115200   # 线材差时降速
```

**常用参数**：

| 参数 | 作用 |
|---|---|
| `-Port COM8` | 指定串口（默认 COM6） |
| `-Baud 115200` | 降波特率，解决线材差导致的失败 |
| `-Erase` | 整片擦除后再烧（会清空 WiFi 等设置） |
| `-Merged` | 整片镜像一次烧入（救砖用） |

### 烧完后

设备会自动重启。首次上电会开热点 **`Clockwise-Wifi`**，手机连上后浏览器打开 **192.168.4.1** 配置 WiFi 即可。

### 后续更新固件

不用再拆机、不用按 BOOT —— 直接在设备设置页最下方「固件升级」上传 `dist/firmware.bin`，约 30 秒完成，失败会自动回滚。

---

## 接线参考（64×64 HUB75 面板）

| 面板针脚 | ESP32 GPIO |
|---|---|
| R1 G1 B1 | 25 26 27 |
| R2 G2 B2 | 14 12 13 |
| A B C D | 23 19 5 17 |
| **E** | **18**（必须接，否则只亮一半） |
| CLK / LAT / OE | 16 / 4 / 15 |

> 引脚可在 `firmware/src/main.cpp` 的 `displaySetup()` 里改。

---

<details>
<summary>📖 以下为上游英文原文（README 原内容）</summary>

![News GIF](https://github.com/jnthas/clockwise/raw/gh-pages/static/images/news.gif) **[Latest version 1.4.4 released!](https://github.com/jnthas/clockwise/releases/tag/v1.4.4)** | [See full change log](https://github.com/jnthas/clockwise/blob/main/CHANGELOG.md#144---2026-10-05)

![Clockwise Logo](https://github.com/jnthas/clockwise/blob/gh-pages/static/images/clockwise_logo.png "Clockwise Logo")

---

**Clockwise** is an open-source smart wall clock that you can easily build yourself.  
It only needs:

- 64x64 RGB LED Matrix (HUB75 or HUB75E)
- ESP32 dev board
- 5V 3A power supply
- Jumpers

To simplify assembly, you can also use the [**WiseShield-32 DIY PCB kit**](https://www.elecrow.com/clockwise-diy-kit.html) — created in partnership with Elecrow especially for Clockwise.

---

## Features

- Real-time clock with customizable themes ("Clockfaces")
- Web-based interface for configuration
- Open-source hardware and firmware
- Compatible with various PCBs or just simple wiring
- Community-driven

---

## Quick Start

### 1. Required Hardware

If you want to build it from scratch, you will need at least these components below. Follow the instructions on [Wiki]() to assemble it. 
- 64x64 RGB LED matrix (HUB75 or HUB75E)
- ESP32 Dev Board
- 5V 3A power supply
- Jumpers

Alternatively, we created a custom PCB that simplifies this process a lot. The kit includes not only the PCB but all components including sensors to make your clock smarter. Check the [WiseShield-32 PCB kit](https://www.elecrow.com/clockwise-diy-kit.html) out now!

### 2. Flash Firmware

- Go to: [https://clockwise.page](https://clockwise.page)
- Follow the on-screen steps to flash Clockwise and configure WiFi

For detailed instructions:  
👉 [See Wiki: Getting Started](https://github.com/jnthas/clockwise/wiki/%F0%9F%9A%80-Getting-Started)

---

## Clockfaces Gallery

You can choose from many creative Clockfaces — or make your own:

Mario Bros | Words | World Map | Castlevania | Pacman | Pokedex | Canvas
:--:|:--:|:--:|:--:|:--:|:--:|:--:
[![](https://github.com/jnthas/cw-cf-0x01/blob/main/cf_0x01_thumb.jpg)](https://github.com/jnthas/cw-cf-0x01) | [![](https://github.com/jnthas/cw-cf-0x02/blob/main/cf_0x02_thumb.jpg)](https://github.com/jnthas/cw-cf-0x02) | [![](https://github.com/jnthas/cw-cf-0x03/blob/main/cf_0x03_thumb.jpg)](https://github.com/jnthas/cw-cf-0x03) | [![](https://github.com/jnthas/cw-cf-0x04/blob/main/cf_0x04_thumb.jpg)](https://github.com/jnthas/cw-cf-0x04) | [![](https://github.com/jnthas/cw-cf-0x05/blob/main/cf_0x05_thumb.jpg)](https://github.com/jnthas/cw-cf-0x05) | [![](https://github.com/jnthas/cw-cf-0x06/blob/main/cf_0x06_thumb.jpg)](https://github.com/jnthas/cw-cf-0x06) | [![](https://github.com/jnthas/cw-cf-0x07/raw/main/cf_0x07_thumb.jpg)](https://github.com/jnthas/cw-cf-0x07)

> Canvas is a special type of Clockface that is capable of rendering different themes described in a JSON file. More about **Canvas Clockface**: [Wiki page](https://github.com/jnthas/clockwise/wiki/Canvas-Clockface)

---

## How to Build

You can start developing and customizing Clockwise in two different ways:

1. **PlatformIO** — advanced usage for developers  
2. **ESP-IDF** — for full control  

👉 [Both are described in the Flashing section of the Wiki](https://github.com/jnthas/clockwise/wiki/%F0%9F%92%BE-Flashing-the-Firmware)

---

## Advanced Configuration

Clockwise offers a flexible set of options that you can adjust through its built-in Settings page:

* **WiFi settings** — easily update your network details without reflashing
* **Timezone & NTP server** — sync the clock accurately with automated NVS POSIX caching
* **Display brightness** — manual or smoothed automatic control (with optional LDR sensor)
* **Display rotation** — adjust orientation (0°, 90°, 180°, 270°) to match your setup
* **Clockface selection** — switch between installed Clockfaces or use Canvas themes
* **RGB order correction** — swap Blue/Green or Blue/Red pins to fix color mismatches
* **Hardware settings** — configure matrix shift driver (FM6124, etc.), I2S clock speed, and E-line pin
* **POSIX timezone string** — fine-tune timezone behavior or use offline overrides

👉 See the full guide here: [Advanced Configuration Wiki](https://github.com/jnthas/clockwise/wiki/%E2%9A%99%EF%B8%8F-Configuring-Clockwise)

---

## Community & Contributions

- Join the [Clock Club](https://github.com/jnthas/clock-club) to create your own Clockfaces
- Contributions and pull requests are welcome!  
👉 [Contributing Guide](https://github.com/jnthas/clockwise/wiki/%F0%9F%A4%9D-Contributing)

---

## License

Clockwise is released under the MIT License.

</details>

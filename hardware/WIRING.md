# Clockwise 硬件接线方案

> 结论：**作者给了，而且是三条路**（PCB 套件 / 兼容 PCB / 手工跳线）。
> 但引脚表本身作者没有在 wiki 里列，他让读者「照 HUB75 库的接线来」。
> 本文把散落在 wiki、gh-pages 图片、HUB75 库源码、固件 NVS 默认值里的信息合并成一张可执行的表。

---

## 1. 作者给的三个入口

| 方案 | 说明 | 链接 |
|---|---|---|
| **① WiseShield-32 PCB 套件**（作者推荐） | 与 Elecrow 合作的专用 PCB，插上 ESP32 和点阵屏即可，含传感器。需自行焊接 | [购买](https://www.elecrow.com/clockwise-diy-kit.html) ・ [装配指南](https://github.com/jnthas/clockwise/blob/gh-pages/welcome.md) |
| **② 兼容 PCB** | 第三方板子，都验证过可跑 Clockwise | ESP32 Trinity ・ [Mario-Clock PCB](https://github.com/Alexvanheu/Mario-Clock-PCB-ESP32) ・ [WeMos Matrix Shield DMA](https://github.com/hallard/WeMos-Matrix-Shield-DMA) |
| **③ 手工跳线** | 面包板飞线，成本最低 | [Getting Started › Option 2](https://github.com/jnthas/clockwise/wiki/%F0%9F%9A%80-Getting-Started) |

作者的原话（Getting Started）：

> Wire the ESP32 to the LED Matrix according to the image above or follow the same wiring suggested [here](https://github.com/mrfaptastic/ESP32-HUB75-MatrixPanel-I2S-DMA#2-wiring-esp32-with-the-led-matrix-panel)

即：**接线图 + 指向 HUB75 库的标准接法**。

### 官方接线图（本地副本）

- `hardware/display_esp32_wiring_bb.png` —— Fritzing 面包板图，HUB75 面板 ↔ ESP32-WROOM-32
  原始地址：`https://github.com/jnthas/clockwise/raw/gh-pages/static/images/display_esp32_wiring_bb.png`
- `hardware/ldr.jpg` —— LDR 接线图（来自 wiki「Connecting the LDR」）

> 面包板图线太多不好认脚号，**实际以第 2 节的引脚表为准**——那张表是从固件真正调用的库源码里取的。

---

## 2. 引脚表（固件实际使用的默认值，权威）

Clockwise 的 `displaySetup()` 用的是 `HUB75_I2S_CFG(64, 64, 1)`，不覆盖引脚就走库的默认值：
`components/ESP32-HUB75-MatrixPanel-I2S-DMA/src/platforms/esp32/esp32-default-pins.hpp`

| HUB75 面板丝印 | ESP32 GPIO | 说明 |
|---|---|---|
| R1 | **25** | 上半屏红 |
| G1 | **26** | 上半屏绿 |
| B1 | **27** | 上半屏蓝 |
| R2 | **14** | 下半屏红 |
| G2 | **12** | 下半屏绿 |
| B2 | **13** | 下半屏蓝 |
| A | **23** | 行地址 bit0 |
| B | **19** | 行地址 bit1 |
| C | **5** | 行地址 bit2 |
| D | **17** | 行地址 bit3 |
| **E** | **18** | 行地址 bit4，**64×64 必需** |
| CLK | **16** | 时钟 |
| LAT | **4** | 锁存 |
| OE | **15** | 输出使能（低有效） |
| GND | GND | 共地，**必须接** |

### 关于 E 引脚（最容易翻车的地方）

库里 `E_PIN_DEFAULT` 是 **-1**，注释写着：

```c
#define E_PIN_DEFAULT   -1 // IMPORTANT: Change to a valid pin if using a 64x64px panel.
```

64×64 面板是 **1:32 扫描**，必须用 E 做第 5 位行地址。所以 Clockwise 把 E 引脚做成了设置页里的可配置项（`E_pin`），NVS 默认 **18**：

```c
E_pin = preferences.getUInt(PREF_E_PIN, 18);   // CWPreferences.h:112
```

不接 E 或接错 → 典型症状是**只亮一半、隔行显示、或整屏乱码**。设置页 `Hardware` 里的 "E Address Line Pin" 要和实际接线一致。

### RGB 线序纠正（面板是 BGR 而不是 RGB 时）

部分面板的绿蓝（或蓝红）是反的，颜色会错。Clockwise 提供两个开关，**只开一个**：

| 开关 | 覆盖后的引脚 | 适用 |
|---|---|---|
| `swapBlueGreen` | B1=26, B2=12；G1=27, G2=13（R 不变 25/14） | 面板是 **RBG** |
| `swapBlueRed` | B1=25, B2=14；R1=27, R2=13（G 不变 26/12） | 面板是 **GRB** |

> ⚠️ 两个同时开会把 B1/B2 覆盖两次，结果既不是 RGB 也不是 BGR。只能用其中一个。

对应源码 `firmware/src/main.cpp` 的 `displaySetup()`。

---

## 3. LDR（自动亮度）接线

来源：wiki [Connecting the LDR](https://github.com/jnthas/clockwise/wiki/Connecting-the-LDR)，图见 `hardware/ldr.jpg`。

```
        +3V3
          │
        ┌─┴─┐
        │LDR│  GL9050（示例）
        └─┬─┘
          ├──────────► GPIO 35  (ADC1_CH7)
        ┌─┴─┐
        │10k│
        └─┬─┘
          │
         GND
```

- 光敏电阻在**上臂**（接 3V3），10k 在**下臂**（接 GND），中点进 GPIO35
- 光越强 → LDR 阻值越小 → 中点电压越高 → ADC 读数越大
- `ldrPin` 默认 **35**（`CWPreferences.h:99`），可在设置页改
- ADC 12 位，范围 **0–4095**；作者实测环境用 `Min=0`、`Max=800` 就够

设置页里的两个阈值语义（重要）：

| 设置 | 行为 |
|---|---|
| `Max value = 0` | **功能禁用**，亮度固定 |
| 读数 < `Min value` | **关屏**（全黑），用于夜里自动熄屏 |
| 其余 | 在 10 档之间映射（v1.4.3 起带迟滞，跨 2 档才变，防闪烁） |

调参方法：设置页 "LDR Pin" 卡片里有个可点链接能实时读当前 ADC 值，开灯/关灯各看一次就知道该填多少。

---

## 4. 供电与共地（作者在原厂 note 里强调的）

- 点阵屏 **5V / 至少 3A**，亮度拉满时可能更高。按 64×64 全白估算，实际峰值可到 3~4A
- ESP32 可以由点阵屏的 5V 取电（经开发板 5V 脚/稳压），也可以独立 USB 供电
- **两者必须共地**，否则 HUB75 数据线电平没有参考，表现为花屏、随机闪烁、或干脆不亮
- 亮度闪烁的排查顺序（作者原文）：查电源额定 → 换更粗的线 → 检查接地

---

## 5. 接线自查清单

上电前逐条确认，能省掉 90% 的"花屏"求助：

- [ ] 14 根信号线 + GND 全部按第 2 节表格接好
- [ ] **E 线接了 GPIO18**，且设置页 `E_pin` 也是 18
- [ ] 面板 16P 排线方向正确（丝印 R1/G1 对齐）
- [ ] ESP32 与 5V 电源**共地**
- [ ] 电源 ≥3A，线材够粗
- [ ] 若颜色错：先试 `swapBlueGreen`，再试 `swapBlueRed`（一次只开一个）
- [ ] 若只亮一半 / 隔行：几乎一定是 E 线问题
- [ ] 若花屏闪烁：面板需要特定驱动 IC 时，设置页 `driver` 试 `FM6124` / `FM6126A` / `ICN2038S` / `MBI5124` / `DP3246`

串口启动日志可以打印实际生效的引脚。这些 `ESP_LOGI` 在库的 `begin()` 里无条件调用，但 **Arduino 框架默认 `CORE_DEBUG_LEVEL=0`，不调出来什么都看不到**。在 `firmware/platformio.ini` 的 `build_flags` 里加一行：

```ini
build_flags =
    ...
    -DCORE_DEBUG_LEVEL=3
```

重烧后 115200 串口就能看到：

```
I (xxx) begin(): Using GPIO 25 for R1_PIN
I (xxx) begin(): Using GPIO 26 for G1_PIN
...
I (xxx) begin(): Using GPIO 18 for E_PIN
```

这是**验证接线是否与配置一致**最快的手段——尤其能立刻发现 `swapBlueGreen` 有没有生效。

---

## 6. 一个需要注意的硬件组合

默认引脚表用的是 **GPIO16 / GPIO17** 做 CLK 和 D。这两个脚在 **带 PSRAM 的 WROVER 模组上被 PSRAM 占用**。

wiki 里写支持 "ESP32-WROOM, WROVER or similar"，但按这套默认引脚，WROVER 直连会有冲突风险。建议：

- 用 **ESP32-WROOM-32**（官方接线图就是这块），或
- 用集成好的 **ESP32 Trinity / WiseShield-32**（它们按面板重新布的线），或
- 自己改引脚（要同时改固件的 `displaySetup()`，目前 Clockwise 只暴露了 E 脚可配，其他脚写死在库里）

---

## 7. 参考资料出处

| 内容 | 出处 |
|---|---|
| 三条硬件路线 | wiki `🔩 Hardware Options` |
| 接线图 + 「照库接线」的原话 | wiki `🚀 Getting Started` |
| LDR 电路与调参 | wiki `Connecting the LDR` |
| 默认引脚数值 | `components/ESP32-HUB75-MatrixPanel-I2S-DMA/src/platforms/esp32/esp32-default-pins.hpp` |
| E 脚必须改的警告 | 同上，`E_PIN_DEFAULT -1` 注释 |
| 固件默认值（E=18 / LDR=35 / driver=0 / 8MHz） | `firmware/lib/cw-commons/CWPreferences.h:99-112` |
| 线序纠正逻辑 | `firmware/src/main.cpp` `displaySetup()` |

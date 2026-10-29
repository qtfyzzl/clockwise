# 手动烧录指南

## 为什么需要手动

`esptool` 默认靠 USB 转串口的 **DTR/RTS 两根控制线**自动把 ESP32 拉进下载模式（DTR→IO0，RTS→EN）。  
你这块板回报 `Wrong boot mode detected (0x13)`，意思是**芯片仍在正常启动**，说明这对控制线没接到芯片的 IO0/EN 上（成品 PCB 常这样，为了省两个三极管和两个电容）。

这时候只能手动把 IO0 拉低。

---

## 一、进入下载模式

### 方式 1：按键（板上有 BOOT + EN/RST 时）

顺序不能错：

```
1. 按住 BOOT （丝印可能是 IO0）—— 保持按住
2. 按一下 EN  （丝印可能是 RST / RESET）—— 按下再松开
3. 松开 BOOT
```

**判断成功**：屏幕会**黑掉**（芯片停在 bootloader，不再跑程序）。这是正常的，不是坏了。

很多板子的丝印对照：

| 常见丝印                          | 作用      |
| ----------------------------- | ------- |
| `BOOT` / `IO0` / `S1`         | 拉低进下载模式 |
| `EN` / `RST` / `RESET` / `S2` | 复位      |

### 方式 2：短接 IO0（没有按键时）

```
1. 拔掉 USB
2. 用镊子/杜邦线把 IO0 和 GND 短接（保持）
3. 插上 USB
4. 松开短接
```

同样以「屏幕黑掉」为成功标志。

### 方式 3：按住 BOOT 再插线

```
1. 按住 BOOT 不放
2. 插上 USB
3. 松开 BOOT
```

---

## 二、确认真的进了下载模式

在另一个窗口盯着串口（115200）：

```bash
~/.platformio/penv/Scripts/pio.exe device monitor --port COM6 --baud 115200
```

进下载模式后芯片会打印：

```
rst:0x1 (POWERON_RESET),boot:0x3 (DOWNLOAD_BOOT(UART0/UART1/SDIO_REI_REO_V2))
waiting for download
```

看到 `boot:0x3` 和 `waiting for download` 就对了。  
如果是 `boot:0x13` 则是普通启动，说明没进去。

> 注意：串口监视器会占用端口，烧录前要先 `Ctrl+C` 退出。

---

## 三、烧录

进入下载模式后，芯片会一直停在那里等，**不用抢时间**。

```bash
吃
```

成功的样子：

```
Connecting....
Chip is ESP32-D0WD-V3 (revision v3.1)
MAC: xx:xx:xx:xx:xx:xx
Wrote 1476112 bytes at 0x00000000 ...
Hash of data verified.
Leaving...
Hard resetting via RTS pin...
```

---

## 四、省事方案：让它自己等

`dist/flash-wait.bat` 会**每 2 秒探测一次**，你一按键进下载模式它就自动开始烧，不用赶时间：

```bat
dist\flash-wait.bat COM6
```

流程：

1. 运行脚本，它会打印「Waiting on COM6 ...」
2. 你按 BOOT → 点一下 EN → 松开 BOOT
3. 脚本检测到后自动烧录，烧完芯片自动重启

---

## 五、常见失败

| 报错                                                   | 原因          | 处理                             |
| ---------------------------------------------------- | ----------- | ------------------------------ |
| `Wrong boot mode detected (0x13)`                    | 没进下载模式      | 重按键，注意第 2 步是「按一下 EN」，不是按住      |
| `Failed to connect: No serial data received`         | 线接错 / 板子没供电 | 换根 USB 线（要数据线，不是纯充电线）          |
| `Could not open port`                                | 串口被占用       | 关掉串口监视器 / Arduino IDE / 其它烧录工具 |
| `A fatal error occurred: MD5 of file does not match` | 传输出错        | 降到 `--baud 115200` 重烧          |
| 按了键仍 0x13                                            | IO0 没引到按键   | 用方式 2 短接 IO0-GND               |

---

## 六、烧完之后

芯片会自动重启，串口 115200 应该看到：

```
Using GPIO 25 for R1_PIN
Using GPIO 26 for G1_PIN
...
Using GPIO 18 for E_PIN
```

然后屏幕亮起，走 Logo → WiFi → NTP → Mario 时钟。

如果**屏幕一直黑**，检查：

- 5V 电源有没有接（屏幕背光/供电和 ESP32 供电是两回事）
- 烧的是 `clockwise-v1.4.4-mario-merged.bin`（1.5MB 那个），不是 `firmware.bin`
- 串口有没有正常日志输出

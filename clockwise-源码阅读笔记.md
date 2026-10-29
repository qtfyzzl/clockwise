# Clockwise 源码阅读笔记

仓库：https://github.com/jnthas/clockwise
版本：v1.4.4（2026-10-05，最新提交 2026-10-06）
许可：MIT

> 说明：本次未落地克隆（克隆操作被取消），以下结论全部基于 GitHub 在线读取的 v1.4.4 源码与 `docs/ARCHITECTURE.md`。

---

## 1. 项目定位

DIY 智能挂钟：ESP32 + 64×64 HUB75/HUB75E RGB LED 点阵屏，5V/3A 供电，走 I2S DMA 刷屏。
固件、硬件文档、网页配置全部开源，主题（Clockface）以独立仓库 + git submodule 形式组织。

- 核心 BSP 库：`ESP32-HUB75-MatrixPanel-I2S-DMA` 3.0.12
- 图形库：Adafruit GFX + PNGdec（Canvas 主题解 PNG）
- 时间：`ezTime`（NTP + 时区）
- 配网：Improv Wi-Fi（Web Serial）+ WiFiManager（AP 强制门户）+ mDNS `clockwise.local`
- 配置持久化：NVS（namespace `clockwise`）

---

## 2. 目录结构（59 个受版本控制文件，不含 submodule）

```
clockwise/
├── firmware/
│   ├── platformio.ini          # PlatformIO 构建（env:esp32dev / env:native 单测）
│   ├── src/main.cpp            # 固件入口：setup()/loop()
│   ├── lib/
│   │   ├── cw-commons/         # 系统层：参数、WiFi、时间、Web、状态指示
│   │   │   ├── CWPreferences.h        ClockwiseParams（NVS 单例）
│   │   │   ├── WiFiController.h       非阻塞配网 + WiFiSetupStateMachine
│   │   │   ├── WiFiSetupStateMachine.h 纯 C++ 状态机（可 native 单测）
│   │   │   ├── CWDateTime.{h,cpp}     ezTime 封装
│   │   │   ├── CWWebServer.h          TCP:80 配置服务 + 内嵌 SPA
│   │   │   ├── SettingsWebPage.h      配置页 HTML/CSS/JS（嵌入固件）
│   │   │   ├── StatusController.h     开机动画 / 状态提示 / LED 闪烁
│   │   │   ├── CWHttpClient.h         Canvas 主题下载
│   │   │   ├── IClockface.h           主题接口（2 个纯虚函数）
│   │   │   ├── Icons.h / picopixel.h  字体与图标
│   │   └── cw-gfx-engine/      # 2D 图形引擎
│   │       ├── Locator.{h,cpp}        服务定位器（全局拿 GFX / EventBus）
│   │       ├── EventBus.{h,cpp}       发布订阅
│   │       ├── Sprite / Tile / Object 精灵、地图块、碰撞
│   │       ├── Game.h                 Game Loop 骨架
│   │       ├── ImageUtils.h / ColorUtil.h / EventTask.h / Macros.h
│   ├── clockfaces/             # 7 个主题，全部是 submodule（cw-cf-0x01 ~ 0x07）
│   └── test/
│       ├── test_native/        # 主机侧单测（状态机、纯逻辑）
│       └── test_embedded/      # 板端单测
├── main/                       # ESP-IDF 入口（CMakeLists.txt + Kconfig.projbuild + main.cpp）
├── components/                 # ESP-IDF 依赖，全部 submodule（arduino、ezTime、WiFiManager…）
├── docs/ARCHITECTURE.md        # 架构文档（质量较高，含 mermaid）
├── AGENTS.md / RELEASE.md / CHECKLIST.md / CHANGELOG.md
└── CMakeLists.txt / sdkconfig.defaults / get-platformio.py
```

---

## 3. 分层架构

```
Clockface 层      cw-cf-0x01(Mario) … cw-cf-0x07(Canvas JSON)
──────────────────────────────────────────────────────
系统层 cw-commons          |   图形层 cw-gfx-engine
Params/WiFi/DateTime       |   Locator / EventBus / Sprite
WebServer/Status           |   Tile / Object / Color
──────────────────────────────────────────────────────
驱动层  HUB75 I2S DMA · Adafruit GFX · PNGdec · Arduino-ESP32 · FreeRTOS
```

依赖方向单向向下：主题只通过 `IClockface` + `Locator` 与引擎交互，不认识 WiFi/NVS。

---

## 4. 启动与主循环（firmware/src/main.cpp，实测代码）

### setup()
1. `Serial.begin(115200)`，板载 LED(GPIO2) 闪 5 次
2. `ClockwiseParams::load()` —— 从 NVS 读全部配置
3. `displaySetup(...)` —— 构造 `HUB75_I2S_CFG(64,64,1)`，按配置处理：
   - RGB/BGR 线序纠正（`swapBlueGreen` 改 b1/b2/g1/g2；`swapBlueRed` 改 r/b）
   - `E` 引脚（HUB75E 1:32 扫描必需）、`driver`（FM6124 等，0~5）、`i2sspeed`（仅 8/16/20 MHz 合法）
   - `new MatrixPanel_I2S_DMA` → `begin()` → `setBrightness8()` → `clearScreen()` → `setRotation()`
4. `new Clockface(dma_display)`
5. 开机 Logo（`StatusController::clockwiseLogo()`）→ 延时 1s
6. `wifi.begin()` —— **立即返回**，配网在 loop 里推进

### loop()（每轮 5 件事）
```cpp
if (wifi.update())      onNetworkReady();   // 网络首次就绪：NTP 初始化 + clockface->setup()
if (wifi.isConnected()) { handleHttpRequest(); ezt::events(); }
if (wifi.connectionSucessfulOnce) clockface->update();
automaticBrightControl();                    // 每 3s
```

`onNetworkReady()` 只跑一次：`cwDateTime.begin(timeZone, use24hFormat, ntpServer, manualPosix)` → `clockface->setup(&cwDateTime)`。

**关键设计**：网络未就绪时不调 `clockface->update()`，屏幕停在 Logo / 状态页；但 HTTP 服务与 ezTime 只在联网分支里跑，所以离线设备是纯时钟（靠 RTC 与已缓存 POSIX 时区）。

---

## 5. 各子系统要点

### 5.1 ClockwiseParams（CWPreferences.h）
- 单例 + `Preferences`（NVS，namespace `clockwise`），构造时 `begin(NVS_READWRITE)`
- 20 个键：WiFi SSID/PWD、ntpServer、timeZone、manualPosix、cachedPosix/cachedTz、use24hFormat、displayBright、autoBrightMin/Max、ldrPin、displayRotation、driver、i2cSpeed、E_pin、swapBlueGreen/Red、canvasServer/canvasFile
- 新增参数的固定套路：常量 → 结构体字段 → `load()` 默认值 → `save()` 序列化 → `CWWebServer` 的 `getCurrentSettings()/processRequest()` → `SettingsWebPage.h` 的 UI 卡片（5 处联动，漏一处就不生效）

### 5.2 WiFiController（v1.4.4 重点重构）
- `begin()` 非阻塞；`update()` 每轮调用，返回 true 表示"网络刚就绪"
- 三级配网：Improv over Serial（ESPTool 网页刷机同通道）→ NVS 里已存凭据 → `WiFiManager` 开 AP `Clockwise-Wifi`（5 分钟超时）
- 时序决策全在 `cw::WiFiSetupStateMachine`（纯 C++，`test_native` 里覆盖了状态迁移与超时），`WiFiController` 只做副作用，可测试性优先
- 每轮最多解析 `IMPROV_MAX_BYTES_PER_PASS = 256` 字节，防止配网时卡住刷屏
- mDNS `clockwise.local:80`；离线且无主题显示超 5 分钟 → `forceRestart()` 看门狗
- 注意：`wifiManager()` / `networkReady()` 用函数内 static，保证生命周期跨 `begin()`（门户在非阻塞模式下要活到后面）

### 5.3 CWDateTime
- 薄封装 `ezTime`；支持 Olson 名（"Asia/Shanghai"）与手写 POSIX 串（"CST-8" 或 "EST5EDT,M3.2.0/2,M11.1.0/2"）
- POSIX 结果缓存进 NVS（`cachedPosix/cachedTz`），断网重启也能正确走时——这是它比多数 DIY 时钟靠谱的地方

### 5.4 ClockwiseWebServer
- 手写 `WiFiServer` 监听 80，不引 Web 框架
- `GET /` 返回 `SettingsWebPage.h` 里的单页应用（编译进 flash）
- `GET /get` 用自定义响应头 `X-<Setting>: <Value>` 回配置（HTTP 204，无 body，省内存）
- `POST /set?k=v` 写 NVS；`GET /read?pin=` 采样 ADC 给 LDR 校准；`POST /restart`

### 5.5 cw-gfx-engine
- `Locator`：服务定位器，主题里 `Locator::getDisplay()` / `getEventBus()` 取依赖，避免构造函数层层传参
- `EventBus`：主题内部解耦（如碰撞事件、动画切换）
- `Sprite/Tile/Object`：坐标 + 包围盒 `collidedWith()` + 图块渲染，够写简单 2D 游戏式动画
- `Game.h`：帧循环骨架，主题继承后只写自己的画面逻辑

### 5.6 Clockface 契约（IClockface.h）
```cpp
class IClockface {
    virtual void setup(CWDateTime *dateTime) = 0;
    virtual void update() = 0;
};
```
实际主题的 `Clockface.h` 还多一个 `Clockface(Adafruit_GFX* display)` 构造和 `externalEvent(int type)`（供 EventBus 用），接口本身很薄——**没有 `setup` 之外的资源释放约定，也没有帧率约定**，全由主题自己控节奏。

---

## 6. 构建系统（双轨）

| | PlatformIO | ESP-IDF |
|---|---|---|
| 配置 | `firmware/platformio.ini` | `CMakeLists.txt` + `main/Kconfig.projbuild` + `sdkconfig.defaults` |
| 板型 | `esp32doit-devkit-v1`, framework=arduino | `idf.py menuconfig` → "Clockwise Configuration" |
| 选主题 | `cd firmware/lib && ln -s ../clockfaces/cw-cf-0x01 mario` 再 `pio run` | Kconfig 选中 `CLOCKFACE_MARIO` 等 |
| 版本宏 | `-D CW_FW_VERSION="1.4.4"`、`-D CW_FW_NAME` | `target_compile_options` 同宏 |

主题选择机制值得注意：
- PlatformIO 用 `build_src_filter` 排除 `clockfaces/`，靠软链把选中的主题塞进 `lib/`，`#include <Clockface.h>` 自然命中
- ESP-IDF 里 `main/CMakeLists.txt` 把 7 个 `cw-cf-0x0X` 全列进 `PRIV_REQUIRES`，但每个主题自己的 `CMakeLists.txt` 用 `if(CONFIG_CLOCKFACE_XXX)` 决定 `INCLUDE_DIRS/SRC_DIRS` 是否为空——只有被选中的那个会提供 `Clockface.h`

CI：`.github/workflows/clockwise-ci.yml`，push `releases/**` 或手动触发，矩阵编译 7 个主题，产物 + `manifest.json` 推到 `gh-pages`，供 clockwise.page 网页刷机。

---

## 7. 自定义一个 Clockface

1. Fork 模板 `https://github.com/jnthas/cw-cf-0x00`
2. 实现 `Clockface(Adafruit_GFX*)` + `setup()` + `update()`
3. 加 submodule 到 `.gitmodules` 与 `firmware/clockfaces/`
4. 在 `main/CMakeLists.txt`（`CLOCKFACES` 变量）、`main/Kconfig.projbuild`（choice 项）、CI workflow 三处注册
5. 主题内可用的资源：`cw-gfx-engine`（精灵/碰撞/事件总线）、`picopixel.h` 小字体、`Icons.h`、`CWDateTime` 的 `getHour()/getMinute()/getFormattedTime()`

Canvas 主题（cw-cf-0x07）是另一条路：不写 C++，HTTP 拉一个 JSON，解释执行 `datetime/line/rect/fillrect/text/image(base64 PNG)` + 帧动画，适合改样式不改固件。

---

## 8. 阅读后的判断（工程视角）

**做得好的地方**
- 双构建系统都维护，且 CI 覆盖 7 个主题的真实编译，不会出现"某个主题悄悄坏了"
- 把配网时序抽成可 native 单测的纯 C++ 状态机（v1.4.4 的主要改动），这是嵌入式里少见的纪律性
- 配置项走"响应头回传 + 无 body"的极简 HTTP，省 RAM；POSIX 时区缓存解决离线走时
- 层次清晰，主题不碰系统层；`Locator`/`EventBus` 给主题留了扩展空间

**需要注意的坑**
1. **显存/内存紧**：520KB SRAM 里 `HUB75` DMA 缓冲占大头，主题里再 new 大数组很容易 heap 耗尽 —— Mario 主题的 `gfx/` 底图都是 `PROGMEM` 常量数组，自己的主题要照做
2. **时钟与刷屏争 CPU**：`loop()` 是单线程轮询，所有子系统必须非阻塞。任何 `delay()` / 阻塞 `while` 都会直接表现为屏幕撕裂或闪烁
3. **面板兼容性**：BGR 线序、FM6124 驱动、E 引脚（HUB75E vs HUB75）三处配置错了就是花屏/半屏/颜色错，先把这三项在配置页调对再谈代码
4. **NVS 写寿命**：`/set` 每次改配置都 commit，前端别做连续拖动式实时下发
5. **主题即编译期选择**：不是运行时加载的插件，换主题要重新编译（Canvas 除外）
6. `IClockface` 没有析构/`teardown`，主题里的动态资源没有统一释放点——换主题靠重启，不要指望热切换

---

## 9. 如果要本地开工

```bash
git clone --recurse-submodules https://github.com/jnthas/clockwise.git
cd clockwise/firmware/lib
ln -s ../clockfaces/cw-cf-0x01 mario   # Windows 用 mklink /D 或直接 copy
pio run -e esp32dev
pio run -e esp32dev -t upload
```

注意 submodule 共 16 个（7 个主题 + 9 个 ESP-IDF 组件），`--recurse-submodules` 不能漏，否则 `firmware/clockfaces/` 与 `components/` 是空目录，直接编译失败。

---

## 附录：贡献者 MonsterYuan（@yuan910715）

### 身份对应
- GitHub login：`yuan910715`，显示名 **MonsterYuan**，地区 Beijing, China
- 直接用 `?author=MonsterYuan` 筛选是查不到提交的，**必须用 login `yuan910715`**
- 提交署名：`MonsterYuan <2486550**@qq.com>`（QQ 邮箱已脱敏）
- CHANGELOG 署名：`Thanks @yuan910715!`

### 在 clockwise 主仓的提交（3 个，2024-04-25 ~ 04-26，直接落在 main）

| SHA | 日期 | 标题 |
|---|---|---|
| `483d0a4` | 2024-04-25 | optimization auto bright control and set ntp failed timeout to 10s |
| `da969ec` | 2024-04-25 | delete debug output |
| `c40bbd3` | 2024-04-26 | add currentValue > ldrMax? logic to ensure that result slot is between 1 and 10 |

改动面很小：`firmware/src/main.cpp`（ABC 主体）+ `firmware/lib/cw-commons/CWDateTime.cpp`（1 行）。

### 具体做了什么（这是当前 v1.4.4 线上代码的来源）

1. **自动亮度从 5 档升到 10 档**
   ```diff
   - uint8_t mapLDR = map(currentValue, ldrMin, ldrMax, 1, 5);   //5 slots
   - uint8_t mapBright = map(mapLDR, 1, 5, minBright, maxBright);
   - dma_display->setBrightness8(mapBright);
   + uint8_t slots = 10;
   + uint8_t mapLDR = map(currentValue, ldrMin, ldrMax, 1, slots);
   + uint8_t mapBright = map(mapLDR, 1, slots, minBright, maxBright);
   ```

2. **加迟滞（hysteresis），解决亮度频繁抖动**
   ```cpp
   uint8_t currentBrightSlot = -1;          // 新状态变量，初值 255，保证首轮必刷
   if (abs(currentBrightSlot - mapLDR) >= 2 || mapBright == 0) {
       dma_display->setBrightness8(mapBright);
       currentBrightSlot = mapLDR;
   }
   ```
   只有跨过 2 个档位才真正改亮度；`mapBright == 0`（全暗）走立即生效，避免夜里该灭屏却因迟滞卡住。这就是 CHANGELOG 1.4.3 里"10 slots with hysteresis to prevent flickering"的原始实现。

3. **`map()` 输入钳位**
   ```cpp
   uint8_t mapLDR = map(currentValue > ldrMax ? ldrMax : currentValue, ldrMin, ldrMax, 1, slots);
   ```
   Arduino 的 `map()` 不做边界约束，ADC 读数超过 `ldrMax` 时会算出 slot 11，进而让 `map(11,1,10,...)` 溢出到 `maxBright` 之外。他这一行是补这个坑。

4. **NTP 同步超时收紧到 10 秒**
   ```diff
   - waitForSync();
   + waitForSync(10);
   ```
   默认 `waitForSync()` 最长会阻塞很久，弱网下等于开机卡住；改成 10s 上限让 `setup()` 尽快交出控制权。

### 代码评价
- 方向完全正确：把"每 3s 无条件 setBrightness8"改成"带迟滞的边沿触发"，是这类 LDR 自动亮度最标准的做法，同时省了 I2S 重配的开销
- `uint8_t currentBrightSlot = -1;` 依赖隐式截断成 255 来当"未初始化"哨兵 —— 能跑，但语义上不干净（可读性差，静态检查会告警），更严谨的写法是 `int16_t currentBrightSlot = -1` 或加 `bool slotValid`
- 三个提交拆成了「功能 → 清理调试输出 → 边界修复」，提交粒度很规矩，看得出有代码 review 习惯
- 时间线值得注意：提交于 2024-04-26，但直到 **v1.4.3（2026-10-04）** 才随版本发布被署名致谢，中间在 main 上放了两年半

### 他本人的公开仓库（19 个，其中自建 9 个）

**自建（非 fork）**
| 仓库 | 说明 | 语言 | 最近更新 |
|---|---|---|---|
| clock_press | clockwise 升级版说明书 | — | 2026-09-17 |
| 3keys | CH552 三键小键盘（CV 工程师键盘） | Vue | 2025-04-03 |
| Esp8266_Wifi_Matrix_Clock | ESP8266 WiFi 点阵时钟 | C++ | 2025-01-04 |
| Esp8266_NTP_Clock_Weather | ESP8266 NTP 时钟 + 和风天气 | C | 2021-03-26 |
| Xiaomi_Scooter_HUD | 小米滑板车 ESP32 仪表盘（转存 Dani.M 的工程） | C | 2020-06-08 |
| AuthenticatorTest | Google Authenticator TOTP 的 Java 实现测试 | Java | 2023-09-22 |
| MouseMove | 自动移动鼠标（防休眠） | Java | 2023-07-28 |
| yuan910715.github.io | 个人主页 | JavaScript | 2024-11-02 |
| yuan910715 | Profile README | — | 2026-10-27 |

**Fork**
| 仓库 | 上游 | 语言 | 最近更新 |
|---|---|---|---|
| HachimoDock | 跟随 Claude Code 会话反应的桌面宠物 | C | 2026-10-27 |
| moink | 墨印：ESP32-C3 + 华为拆机四色墨水屏的电子拍立得 | C | 2026-10-08 |
| clockwise | 本项目 fork | C++ | 2024-06-25 |
| DeepSeek-R1 / ezTime / snk / WebMonitor / RF-Master / Dc1Server / Dc1Control | — | — | 2020 ~ 2025 |

### 从这个人的仓库能看出的画像
- **嵌入式 DIY 玩家**，路线清晰：ESP8266 时钟/气象站 → ESP32 滑板车 HUD → ESP32 点阵钟 → ESP32-C3 墨水屏，全是"单片机 + 显示 + 联网"这一类
- `clock_press`（"clockwise 升级版说明书"）说明他不只是提了个 PR，还在做这个项目的**二次开发/复刻说明书**，2026-09 还在动
- `moink` 和 `HachimoDock` 是 2026-10 新 fork 的，兴趣正从点阵屏转向电子墨水屏与桌面端小工具
- 他的自建仓库 star 都不高，属于纯自用/记录型开发者，代码风格朴素务实，不追求工程化包装（没有 CI、没有单测），但会注意边界条件 —— 这跟他那三个提交的风格完全一致

---

## 附：本地编译记录（2026-10-27，Windows + PlatformIO）

### 环境
- 仓库：`C:/Users/26541/WorkBuddy/clockwise`（浅克隆 main `dadca14`）
- 工具：PlatformIO Core 6.2.0（VS Code 插件自带 `~/.platformio/penv`）
- 平台：espressif32 **8.0.0**，framework-arduinoespressif32 **3.3.12**（IDF 5.x，gcc 14.2.0）
- 编译命令：`cd firmware && FW_NAME=Clockwise pio run -e esp32dev`

### 主题选择（Windows 注意）
`firmware/lib/` 下需要存在名为 `mario` 的主题目录。官方文档写的是 `ln -s`，但 **Windows 下 Git Bash 的 `ln -s` 会失败并留下一个空目录**（没有开发者模式/管理员权限建不了符号链接）。改用目录联接，无需权限：

```bash
cd firmware/lib
cmd //c "mklink /J mario ..\\clockfaces\\cw-cf-0x01"
```

换主题就把 `mario` 这个联接重新指到别的 `cw-cf-0x0X`。

### 三个必须修的坑（否则编不过）

**1. PNGdec 依赖版本浮动（上游 bug）**
`bitbank2/PNGdec@^1.0.1` 会解到 1.1.6，而 1.1.6 新增的 `src/s3_simd_rgb565.S` 守卫写的是 `#ifdef ARDUINO_ARCH_ESP32` —— 这个宏对**普通 ESP32 同样成立**，于是 S3 专用汇编被拉进编译，紧接着去找只存在于 ESP32-S3 的 `dsps_fft2r_platform.h`：

```
s3_simd_rgb565.S:9:10: fatal error: dsps_fft2r_platform.h: No such file or directory
```

→ 锁定版本：`bitbank2/PNGdec@1.0.1`

**2. `Sprite::name()` 只有声明没有定义（上游 bug，更隐蔽）**
`cw-gfx-engine/Sprite.h` 声明了 `virtual const char* name();`，但 `Sprite.cpp` 里没有实现。它是这个类的 **key function**（第一个非内联、非纯虚的虚函数），按 C++ 规则 vtable 只在定义 key function 的编译单元里生成；因为没有任何 TU 定义它，`Sprite` 的虚表压根不存在，所有实例化子类（`Block`、`Mario`、`Pacman`、`CustomSprite`）的文件全部链接失败：

```
libmario.a(block.cpp.o): undefined reference to `vtable for Sprite'
```

子类都覆写了 `name()`，说明它是基类接口，补一个默认实现即可：

```cpp
const char* Sprite::name() {
  return "Sprite";
}
```

**3. Flash 容量超限**
core 3.x 编出的镜像比项目当年的 core 2.0.17 大，默认 1.25MB 应用分区放不下：

```
Flash: 104.8% (used 1373064 bytes from 1310720 bytes)
Error: The program size (1373064 bytes) is greater than maximum allowed
```

项目不用 SPIFFS（配置页是编译进固件的），换 3MB 应用分区：

```ini
board_build.partitions = huge_app.csv
```

### 编译结果

| 项 | 值 |
|---|---|
| 状态 | **SUCCESS**（60.9 s）|
| RAM | 52,016 / 327,680 字节（15.9%）|
| Flash | 1,373,064 / 3,145,728 字节（43.6%）|
| 产物 | `firmware/.pio/build/esp32dev/firmware.bin`（1.4 MB）|

### 改动清单（相对上游）
```
 M firmware/platformio.ini              # PNGdec 锁 1.0.1 + huge_app 分区
 M firmware/lib/cw-gfx-engine/Sprite.cpp # 补 Sprite::name() 默认实现
 M components/arduino                    # 子模块为空，git 视为有差异（仅 ESP-IDF 需要）
```

前两个是**上游真 bug**，不是本地环境问题，值得给 jnthas 提 PR。

### 提醒
- `components/arduino` 仍是空目录（arduino-esp32 约 300MB，两次拉取都被网络中断）。**PlatformIO 构建完全不需要它**，只有走 `idf.py build`（ESP-IDF 路线）才要补 `git submodule update --init components/arduino`。
- 用 core 3.3.12 编译通过只是第一步，**运行期行为未验证**（尤其 HUB75 的 I2S 并行驱动在 IDF5 下是否稳定、ADC 读数范围是否与 NVS 里存的阈值匹配）。如果实机出现花屏或亮度异常，最稳的做法是把平台降到项目当年的 `platform = espressif32@6.8.1`（Arduino core 2.0.17）重新编译。


#include <Arduino.h>
#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>
#include <SPIFFS.h>

// Clockface
#include <Clockface.h>
// Commons
#include <WiFiController.h>
#include <CWDateTime.h>
#include <CWPreferences.h>
#include <CWWebServer.h>
#include <StatusController.h>
#include <picopixel.h>
#include <time.h>
#include <sys/time.h>
#include <stdlib.h>

// 只有部分主题（如 Canvas 的 cw-cf-0x07）在自己的 Clockface.h 里定义了
// CLOCKFACE_NAME，Mario 等主题没有。设置页靠这个值决定是否显示 Canvas 配置组，
// 所以这里给一个与 firmware/lib 下联接的目录一致的兜底值。
// 换主题时如果该主题未定义此宏，需要同步改这里。
#ifndef CLOCKFACE_NAME
#define CLOCKFACE_NAME "cw-cf-0x01"
#endif

#define MIN_BRIGHT_DISPLAY_ON 4
#define MIN_BRIGHT_DISPLAY_OFF 0

// 自动亮度分档数：10 档在 4..255 的亮度范围内步进足够细，又不会频繁触发重配
#define AUTO_BRIGHT_SLOT_MAX 10

#define ESP32_LED_BUILTIN 2

MatrixPanel_I2S_DMA *dma_display = nullptr;

Clockface *clockface;

// 主题若自行管理亮度（例如自适应主题要按环境光切换布局+亮度），
// 会在 setup() 里把它置 true，主循环的自动亮度就不再插手，避免两处抢写亮度寄存器。
bool g_themeControlsBrightness = false;

WiFiController wifi;
CWDateTime cwDateTime;

bool autoBrightEnabled;
long autoBrightMillis = 0;
uint8_t currentBrightSlot = -1;

bool isValidI2SSpeed(uint32_t speed) {
  return speed == 8000000 || speed == 16000000 || speed == 20000000;
}

bool isValidDriver(uint32_t drv) {
  return drv >= 0 && drv <= 5;
}



void displaySetup(bool swapBlueGreen, bool swapBlueRed, uint8_t displayBright, uint8_t displayRotation, uint8_t driver, uint32_t i2cSpeed, uint8_t E_pin)
{
  HUB75_I2S_CFG mxconfig(64, 64, 1);

  if (swapBlueGreen)
  {
    // Swap Blue and Green pins because the panel is RBG instead of RGB.
    mxconfig.gpio.b1 = 26;
    mxconfig.gpio.b2 = 12;
    mxconfig.gpio.g1 = 27;
    mxconfig.gpio.g2 = 13;
  }

  if (swapBlueRed)
  {
    // Swap Blue and Red pins. 
    mxconfig.gpio.b1 = 25;
    mxconfig.gpio.b2 = 14;
    mxconfig.gpio.r1 = 27;
    mxconfig.gpio.r2 = 13;
  }

  mxconfig.gpio.e = E_pin;
  mxconfig.clkphase = false;

  if (isValidDriver(driver)) {
    mxconfig.driver = static_cast<HUB75_I2S_CFG::shift_driver>(driver);
  } else {
    Serial.printf("[ERROR] Invalid driver from config:%d\n", driver);
  }
  if (isValidI2SSpeed(i2cSpeed)) {
    mxconfig.i2sspeed = static_cast<HUB75_I2S_CFG::clk_speed>(i2cSpeed);
  } else {
    Serial.printf("[ERROR] Invalid I2S speed from config:%d\n", i2cSpeed);
  }

  // Display Setup
  dma_display = new MatrixPanel_I2S_DMA(mxconfig);
  dma_display->begin();
  dma_display->setBrightness8(displayBright);
  dma_display->clearScreen();
  dma_display->setRotation(displayRotation);
}

// 自动亮度：房间越暗 → 屏幕越暗，房间越亮 → 屏幕越亮。
//
// 电路是  3V3 — LDR — GPIO(ADC) — 10k — GND，
// 光越强则 LDR 阻值越小、分压点电压越高、ADC 读数越大，
// 所以「读数 ↑ = 环境亮 ↑ = 亮度 ↑」，方向与读数正相关。
//
// 相对上游修正了三处：
//   1. 双端钳位。Arduino 的 map() 不做边界检查，读数低于 ldrMin 时会算出 0 或负数，
//      强转 uint8_t 后回绕成很大的值，导致亮度乱跳。
//   2. ldrMax <= ldrMin 时（含用户把最大值留成 0 的边界）直接按最亮处理，避免除零。
//   3. 迟滞比较统一转 int 再取绝对值，避免 uint8_t 相减回绕。
void automaticBrightControl()
{
  // 主题接管亮度时直接退出
  if (g_themeControlsBrightness)
    return;

  if (!autoBrightEnabled)
    return;

  if (millis() - autoBrightMillis <= 3000)
    return;

  autoBrightMillis = millis();

  ClockwiseParams *params = ClockwiseParams::getInstance();
  const int16_t raw = (int16_t)analogRead(params->ldrPin);

  const uint16_t ldrMin = params->autoBrightMin;
  const uint16_t ldrMax = params->autoBrightMax;

  // 阈值无效：直接给到用户设定的亮度上限
  if (ldrMax <= ldrMin)
  {
    if ((int)currentBrightSlot != AUTO_BRIGHT_SLOT_MAX)
    {
      dma_display->setBrightness8(params->displayBright);
      currentBrightSlot = AUTO_BRIGHT_SLOT_MAX;
    }
    return;
  }

  // 底部钳位；顶部已在 map 前钳位
  int32_t clamped = raw;
  if (clamped < (int32_t)ldrMin) clamped = (int32_t)ldrMin;
  if (clamped > (int32_t)ldrMax) clamped = (int32_t)ldrMax;

  // 环境光低于设定下限时熄屏，否则保证一个可见的最低亮度（避免刚熄灯就全黑）
  const uint8_t minBright = (raw < (int16_t)ldrMin) ? MIN_BRIGHT_DISPLAY_OFF : MIN_BRIGHT_DISPLAY_ON;

  const uint8_t slot = (uint8_t)map(clamped, ldrMin, ldrMax, 1, AUTO_BRIGHT_SLOT_MAX); // 1..10
  const uint8_t bright = (uint8_t)map(slot, 1, AUTO_BRIGHT_SLOT_MAX, minBright, params->displayBright);

  // 迟滞：跨 2 档才真正写寄存器，避免灯光微抖导致屏幕持续闪烁
  if (abs((int)currentBrightSlot - (int)slot) >= 2 || bright == 0)
  {
    dma_display->setBrightness8(bright);
    currentBrightSlot = slot;
  }
}

// ---------------- 离线兜底显示 ----------------
// WiFi 一直连不上时，clockface->setup() 永远不会被调用，屏幕会一直停在
// "正在连接 WiFi" 的静态提示上。这里在主循环里兜一层：超时后自己画一个
// 可辨识的界面（时间若已同步就显示时间，否则显示占位与提示）。
#define OFFLINE_AFTER_MS 20000UL

static bool offlineActive = false;
static unsigned long offlineLastDraw = 0;

static const uint8_t OFFLINE_SEGS[10] = {0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F};

static void offlineDigit(int x, int y, int w, int h, int t, int8_t d)
{
  const int half = (h - t) / 2;
  const int vert = (h - t) / 2 - t;
  const uint8_t m = (d < 0) ? 0x40 : OFFLINE_SEGS[d % 10]; // d<0 表示显示一条横杠

  if (m & 0x01) dma_display->fillRect(x + t, y, w - 2 * t, t, 0xFFFF);
  if (m & 0x40) dma_display->fillRect(x + t, y + half, w - 2 * t, t, 0xFFFF);
  if (m & 0x08) dma_display->fillRect(x + t, y + h - t, w - 2 * t, t, 0xFFFF);
  if (m & 0x20) dma_display->fillRect(x, y + t, t, vert, 0xFFFF);
  if (m & 0x02) dma_display->fillRect(x + w - t, y + t, t, vert, 0xFFFF);
  if (m & 0x10) dma_display->fillRect(x, y + (h + t) / 2, t, vert, 0xFFFF);
  if (m & 0x04) dma_display->fillRect(x + w - t, y + (h + t) / 2, t, vert, 0xFFFF);
}

// ---------------- 时间持久化 ----------------
// ESP32 没有电池 RTC，断电后系统时间是 1970。把最后一次 NTP 时间存进 NVS，
// 没网启动时用它恢复，离线页面就能显示一个「大致正确」的时间。
// 误差 = 关机时长，所以每 30 分钟刷新存档。
static unsigned long lastTimeSave = 0;

static void applyTimeZoneEnv()
{
  const String posix = ClockwiseParams::getInstance()->manualPosix;
  if (posix.length() > 0)
  {
    setenv("TZ", posix.c_str(), 1);
    tzset();
  }
}

static void restoreTimeFromNvs()
{
  applyTimeZoneEnv();

  const uint32_t saved = ClockwiseParams::getInstance()->lastEpoch;
  if (saved < 1700000000UL)
    return;                       // 从来没同步成功过
  if (time(nullptr) > 1700000000L)
    return;                       // 系统时间已经是对的

  struct timeval tv;
  tv.tv_sec = (time_t)saved;
  tv.tv_usec = 0;
  settimeofday(&tv, nullptr);
  Serial.printf("[Time] 无网络，用存档时间恢复: %lu\n", (unsigned long)saved);
}

static void saveTimeToNvs()
{
  const time_t now = time(nullptr);
  if (now < 1700000000L)
    return;
  if (lastTimeSave != 0 && millis() - lastTimeSave < 30UL * 60UL * 1000UL)
    return;
  lastTimeSave = millis();
  ClockwiseParams::getInstance()->lastEpoch = (uint32_t)now;
  ClockwiseParams::getInstance()->save();
}

// ---------------- 离线重连 ----------------
// 连不上就每分钟重试一次。注意必须保留配网 AP（手机还要连它），
// 所以切成 AP+STA 共存，而不是把 AP 关掉。
static unsigned long lastWifiRetry = 0;
static uint16_t wifiRetryCount = 0;

static void retryWiFiIfOffline()
{
  if (WiFi.status() == WL_CONNECTED)
    return;

  const String ssid = ClockwiseParams::getInstance()->wifiSsid;
  if (ssid.length() == 0)
    return;

  if (lastWifiRetry != 0 && millis() - lastWifiRetry < 60000UL)
    return;
  lastWifiRetry = millis();

  const wifi_mode_t m = WiFi.getMode();
  if (m != WIFI_AP_STA && m != WIFI_STA)
    WiFi.mode(WIFI_AP_STA);

  wifiRetryCount++;
  Serial.printf("[WiFi] 第 %u 次重连（每 60 秒一次）: %s\n", wifiRetryCount, ssid.c_str());
  WiFi.begin(ssid.c_str(), ClockwiseParams::getInstance()->wifiPwd.c_str());
}

void drawOfflineScreen()
{
  dma_display->fillRect(0, 0, 64, 64, 0);

  // 时间是否可信：NTP 同步过才会有 2023 年以后的时间
  const bool timeValid = (time(nullptr) > 1700000000L);

  int8_t h1, h2, m1, m2;
  if (timeValid)
  {
    // 用 localtime_r 而不是 cwDateTime：离线时 cwDateTime.begin() 可能还没跑过
    time_t now = time(nullptr);
    struct tm lt;
    localtime_r(&now, &lt);
    h1 = lt.tm_hour / 10; h2 = lt.tm_hour % 10;
    m1 = lt.tm_min / 10;  m2 = lt.tm_min % 10;
  }
  else
  {
    h1 = h2 = m1 = m2 = -1; // 显示 --:--
  }

  // 与 adaptive 主题一致的几何：4*12 + 4*2 + 4 = 60，居中 x=2
  const int w = 12, h = 32, t = 3, gap = 2, colon = 4, y = 14;
  offlineDigit(2, y, w, h, t, h1);
  offlineDigit(2 + w + gap, y, w, h, t, h2);
  const int cx = 2 + 2 * (w + gap);
  dma_display->fillRect(cx + 1, y + h / 3, 2, 2, 0xFFFF);
  dma_display->fillRect(cx + 1, y + 2 * h / 3 - 2, 2, 2, 0xFFFF);
  offlineDigit(cx + colon + gap, y, w, h, t, m1);
  offlineDigit(cx + colon + gap + w + gap, y, w, h, t, m2);

  // 底部小字提示
  dma_display->setFont(&Picopixel);
  dma_display->setTextColor(0xF800); // 红
  const char *msg = timeValid ? "no wifi" : "no wifi / no time";
  int16_t x1, y1;
  uint16_t tw, th;
  dma_display->getTextBounds(msg, 0, 0, &x1, &y1, &tw, &th);
  dma_display->setCursor((64 - tw) / 2 - x1, 52);
  dma_display->print(msg);
  dma_display->setFont();
}

// ---------------- 自动换盘 ----------------
// 每天 00:00 切到下一个本地主题（按名字字母序循环），切换后重启一次。
// 具体查找/切换逻辑在 CWWebServer 里，和「立即切换」按钮共用同一套实现。
static String lastRotateDay = "";

static void checkAutoRotate()
{
  if (!ClockwiseParams::getInstance()->autoRotate)
    return;

  // 只在 00:00 这一分钟内触发
  if (cwDateTime.getHour() != 0 || cwDateTime.getMinute() != 0)
    return;

  // 用 "YYYYMMDD" 字符串去重。
  // 注意：不能用 "z"——ezTime 里 z 是「时区缩写」（如 CST），取 toInt() 恒为 0，
  // 会导致 lastRotateDay 永远等于 0，自动换盘只在第一次生效、之后再也不切。
  const String today = cwDateTime.getFormattedTime("Ymd");
  if (today == lastRotateDay)
    return;
  lastRotateDay = today;

  if (!ClockwiseWebServer::getInstance()->rotateToNextTheme())
  {
    Serial.println("[App] 自动换盘：闪存里没有其它本地主题");
    return;
  }

  Serial.println("[App] 自动换盘完成，重启生效");
  delay(300);
  ESP.restart();
}

void setup()
{
  Serial.begin(115200);
  pinMode(ESP32_LED_BUILTIN, OUTPUT);

  StatusController::getInstance()->blink_led(5, 100);

  // 挂载 SPIFFS：给 Canvas 主题存本地 JSON 用（分区表 huge_app.csv 里预留 896KB）
  if (!SPIFFS.begin(true))
  {
    Serial.println("[FS] SPIFFS 挂载失败，Canvas 只能用远程主题");
  }
  else
  {
    Serial.printf("[FS] SPIFFS 就绪 总 %u 字节, 已用 %u 字节\n",
                  (unsigned)SPIFFS.totalBytes(), (unsigned)SPIFFS.usedBytes());
  }

  // 把当前编译的主题名交给 Web 服务（cw-commons 独立编译，看不到主题宏）
  ClockwiseWebServer::getInstance()->clockfaceName = CLOCKFACE_NAME;

  ClockwiseParams::getInstance()->load();

  // 尽早恢复时间：没有网络时系统时间是 1970，离线页面就只能显示 --:--
  restoreTimeFromNvs();

  pinMode(ClockwiseParams::getInstance()->ldrPin, INPUT);

  uint8_t driver = ClockwiseParams::getInstance()->driver;
  uint32_t i2cSpeed = ClockwiseParams::getInstance()->i2cSpeed;
  uint8_t E_pin = ClockwiseParams::getInstance()->E_pin;
  
  displaySetup(ClockwiseParams::getInstance()->swapBlueGreen, ClockwiseParams::getInstance()->swapBlueRed, ClockwiseParams::getInstance()->displayBright, ClockwiseParams::getInstance()->displayRotation, driver, i2cSpeed, E_pin);
  clockface = new Clockface(dma_display);

  autoBrightEnabled = (ClockwiseParams::getInstance()->autoBrightMax > 0);

  StatusController::getInstance()->clockwiseLogo();
  delay(1000);

  StatusController::getInstance()->wifiConnecting();
  wifi.begin(); // non-blocking; provisioning continues in loop()
}

// Runs once, as soon as Wi-Fi is up (stored credentials, Improv or AP portal).
// 开机把 IP 显示 5 秒：DHCP 分配的 IP 会变（这次会话里就从 .99 变到 .10），
// 屏幕上直接看一眼，就不用去路由器后台翻了。
void showIpSplash()
{
  const String ipStr = WiFi.localIP().toString();

  dma_display->fillRect(0, 0, 64, 64, 0);

  // 顶部小字标签（Picopixel，红色）
  dma_display->setFont(&Picopixel);
  dma_display->setTextColor(0xF800);
  dma_display->setCursor(25, 6);
  dma_display->print("WiFi");
  dma_display->setFont();

  // IP 按“一个点”拆成两行，用默认 5x7 字体（每字符宽 6px，最多放 10 个字符/行）。
  // 分割点选能让“较长的一行最短”的那个，否则 192.168.137.10 这种
  // 按最后一个点拆会得到 11 个字符（66px），超出 64px 屏幕。
  const int ipLen = (int)ipStr.length();
  int cut = -1, best = 999;
  for (int i = 0; i < ipLen; i++)
  {
    if (ipStr.charAt(i) != '.')
      continue;
    const int m = (i + 1 > ipLen - i - 1) ? (i + 1) : (ipLen - i - 1);
    if (m < best)
    {
      best = m;
      cut = i;
    }
  }
  if (cut < 0)
  { // 不是正常 IP 格式，退化为整行
    cut = ipLen;
  }
  const String l1 = ipStr.substring(0, cut + 1);
  const String l2 = ipStr.substring(cut + 1);

  dma_display->setTextColor(0xFFFF);
  dma_display->setTextSize(1);
  dma_display->setCursor((64 - (int)l1.length() * 6) / 2, 18);
  dma_display->print(l1);
  dma_display->setCursor((64 - (int)l2.length() * 6) / 2, 28);
  dma_display->print(l2);

  // 底部提示：这个地址就是设置页
  dma_display->setFont(&Picopixel);
  dma_display->setTextColor(0x0659);
  const char *hint = "settings";
  dma_display->setCursor((64 - (int)strlen(hint) * 4) / 2, 48);
  dma_display->print(hint);
  dma_display->setFont();
}

void onNetworkReady()
{
  StatusController::getInstance()->ntpConnecting();
  cwDateTime.begin(ClockwiseParams::getInstance()->timeZone.c_str(),
      ClockwiseParams::getInstance()->use24hFormat,
      ClockwiseParams::getInstance()->ntpServer.c_str(),
      ClockwiseParams::getInstance()->manualPosix.c_str());

  showIpSplash();
  delay(5000);   // 停 5 秒让人看清，然后主题接管

  // 关键诊断：maxAlloc 是「堆里最大的连续块」，网络能不能工作看的正是它，
  // 而不是 free。48KB JSON 缓冲那次就是 free 还有 108KB、但 maxAlloc 不够了。
  Serial.printf("[HEAP] 主题接管前 free=%u maxAlloc=%u\n",
                (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getMaxAllocHeap());

  clockface->setup(&cwDateTime);

  // 链路质量诊断：RSSI 太差（>-75dBm 说明信号很弱）时，网页再怎么优化都慢
  Serial.printf("[WiFi] RSSI=%d dBm  信道=%d  省电模式=%d\n",
                WiFi.RSSI(), WiFi.channel(), (int)WiFi.getSleep());

  Serial.printf("[HEAP] 主题加载后 free=%u maxAlloc=%u\n",
                (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getMaxAllocHeap());
}

void loop()
{
  if (wifi.update()) // also services Improv Serial on every pass
  {
    onNetworkReady();
  }

  if (wifi.isConnected())
  {
    ClockwiseWebServer::getInstance()->handleHttpRequest();
    ezt::events();
  }

  if (wifi.connectionSucessfulOnce)
  {
    clockface->update();
    checkAutoRotate();
  }
  else
  {
    retryWiFiIfOffline();

    // 网络迟迟不就绪：自己画兜底界面，别让屏幕一直干等
    if (!offlineActive && millis() > OFFLINE_AFTER_MS)
    {
      offlineActive = true;
      Serial.println("[App] 网络 30 秒未就绪，进入离线显示");
    }
    if (offlineActive && (millis() - offlineLastDraw > 1000))
    {
      offlineLastDraw = millis();
      drawOfflineScreen();
    }
  }

  automaticBrightControl();
  saveTimeToNvs();
}

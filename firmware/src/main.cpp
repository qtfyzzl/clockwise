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

// 本工程内聚模块
#include "OfflineClock.h"
#include "TimeStore.h"

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

// ---------------- 离线兜底 ----------------
// WiFi 一直连不上时 clockface->setup() 永远不会被调用，屏幕会停在静态提示上。
// 这里在主循环里兜一层：超时后自己画一个可辨识的界面。
// 具体绘制在 OfflineClock.cpp，时间恢复在 TimeStore.cpp。
#define OFFLINE_AFTER_MS 20000UL

static bool offlineActive = false;
static unsigned long offlineLastDraw = 0;

// ---------------- 离线重连 ----------------
// 连不上就每分钟重试一次。注意必须保留配网 AP（手机还要连它），
// 所以切成 AP+STA 共存，而不是把 AP 关掉。
static const unsigned long WIFI_RETRY_INTERVAL_MS = 60000UL;

static unsigned long lastWifiRetry = 0;
static uint16_t wifiRetryCount = 0;

static void retryWiFiIfOffline()
{
  if (WiFi.status() == WL_CONNECTED)
    return;

  const String ssid = ClockwiseParams::getInstance()->wifiSsid;
  if (ssid.length() == 0)
    return;

  if (lastWifiRetry != 0 && millis() - lastWifiRetry < WIFI_RETRY_INTERVAL_MS)
    return;
  lastWifiRetry = millis();

  const wifi_mode_t m = WiFi.getMode();
  if (m != WIFI_AP_STA && m != WIFI_STA)
    WiFi.mode(WIFI_AP_STA);

  wifiRetryCount++;
  Serial.printf("[WiFi] 第 %u 次重连（每 60 秒一次）: %s\n", wifiRetryCount, ssid.c_str());
  WiFi.begin(ssid.c_str(), ClockwiseParams::getInstance()->wifiPwd.c_str());
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

  // 挂载 SPIFFS：给 Canvas 主题存本地 JSON 用（分区表 huge_app.csv 里预留 896KB）。
  //
  // 第二个参数原来是 true（挂载失败就格式化）。踩过坑：换 USB 口时电源闪断，
  // 正好卡在写主题，分区损坏 → 下次启动自动格式化 → 用户 25 个主题全没了，
  // 而且没有任何提示。
  // 现在改成 false：失败了只报错，由用户在设置页显式点「格式化存储」才清空。
  if (!SPIFFS.begin(false))
  {
    Serial.println("[FS] SPIFFS 挂载失败（未自动格式化，避免清空已有主题）");
    Serial.println("[FS] 如需重建，请在设置页点「格式化存储」，或调 POST /fs-format");
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
  time_store::restore();

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

// 校验 canvasFile 对应的本地文件是否存在；不存在就换成随便一个存在的主题。
// 只改 NVS，不重启——setup() 紧接着就会读这个值。
static void ensureCanvasFileExists()
{
  ClockwiseParams *p = ClockwiseParams::getInstance();
  const String path = "/" + p->canvasFile + ".json";

  if (p->canvasFile.length() > 0 && SPIFFS.exists(path))
    return;

  const String fallback = ClockwiseWebServer::firstLocalTheme();
  Serial.printf("[Canvas] 主题 '%s' 的本地文件不存在，回退到 '%s'\n",
                p->canvasFile.c_str(),
                fallback.length() ? fallback.c_str() : "(无)");

  if (fallback.length() == 0)
    return;   // 一个本地主题都没有，交给 Canvas 去远程拉

  p->canvasFile = fallback;
  p->save();
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

  // 启动前确认 canvasFile 指向的文件真的存在。
  // 换 USB 口/断电损坏分区后，NVS 里可能还留着一个已被清掉的主题名，
  // 那样 Canvas 会去远程拉、超时后停在报错页。这里直接回退到任意一个本地主题。
  ensureCanvasFileExists();

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
      offline_clock::draw(dma_display);
    }
  }

  automaticBrightControl();
  time_store::saveIfDue();
}

#include "WiFiController.h"

#include <CWPreferences.h>

// Improv Serial 实例（头文件里只有 extern 声明）
ImprovWiFi improvSerial(&Serial);

WiFiManager &WiFiController::wifiManager()
{
  // 必须比 begin() 活得久：AP 配网页是非阻塞模式，随时可能被 process()
  static WiFiManager wm;
  return wm;
}

bool &WiFiController::networkReady()
{
  static bool ready = false;
  return ready;
}

void WiFiController::persistCredentials(const char *ssid, const char *password)
{
  ClockwiseParams *params = ClockwiseParams::getInstance();
  params->load();
  if (params->wifiSsid == ssid && params->wifiPwd == password)
    return; // avoid needless NVS writes
  params->wifiSsid = String(ssid);
  params->wifiPwd = String(password);
  params->save();
}

void WiFiController::onImprovWiFiErrorCb(ImprovTypes::Error err)
{
  ClockwiseWebServer::getInstance()->stopWebServer();
  StatusController::getInstance()->blink_led(2000, 3);
}

void WiFiController::onImprovWiFiConnectedCb(const char *ssid, const char *password)
{
  persistCredentials(ssid, password);

  if (networkReady() && !wifiManager().getConfigPortalActive())
    ClockwiseWebServer::getInstance()->startWebServer();
}

bool WiFiController::isConnected()
{
  if (improvSerial.isConnected()) {
    elapsedTimeOffline = 0;
    return true;
  } else {
    // While provisioning, the state machine owns the timeouts (portal -> restart).
    if (setupFsm.isSettingUp())
      return false;

    if (elapsedTimeOffline == 0 && !connectionSucessfulOnce)
      elapsedTimeOffline = millis();
    
    // 上游是 5 分钟就重启。但我们支持「离线简约时钟 + 每分钟重连」，
    // 频繁重启会把离线时钟打断，所以放宽到 60 分钟只当作兜底。
    if ((millis() - elapsedTimeOffline) > 1000UL * 60UL * 60UL)
      StatusController::getInstance()->forceRestart();

    return false;
  }
}

bool WiFiController::handleImprovWiFi()
{
  bool activity = false;
  for (uint16_t i = 0; i < IMPROV_MAX_BYTES_PER_PASS && Serial.available() > 0; i++)
  {
    improvSerial.handleSerial();
    activity = true;
  }
  return activity;
}

void WiFiController::startApPortal()
{
  StatusController::getInstance()->wifiConnectionFailed("Setup WiFi via AP");

  WiFiManager &wm = wifiManager();
  // 关键：启动配网页前先断开 STA 并只保留 AP。
  //
  // 现象是「开机时能搜到 WiFi，运行一段时间后扫不到」：
  //   WiFiManager 默认 _disableSTAConn=true 只在「STA 未连接」时关 STA。
  //   开机时 STA 还没连上 → 会关 → 扫描正常。
  //   但运行一段时间后（STA 已关联、或处于半关联悬挂状态）再进配网，
  //   WiFi.isConnected() 仍返回真，于是不关 STA；而 ESP32 在 STA 已关联时
  //   无法正常做 AP 模式的信道扫描，结果就是配网页扫不到任何网络。
  //
  // 这里显式切到纯 AP + 断开 STA，让扫描恢复。配网结束后 onConnected() 会
  // 重新连 STA，不影响正常使用。
  WiFi.disconnect(true);   // 断开并清除自动重连，避免 STA 抢占信道
  WiFi.mode(WIFI_AP);

  wm.setConfigPortalBlocking(false);
  wm.setConfigPortalTimeout(0); // timeout is owned by WiFiSetupStateMachine
  wm.startConfigPortal("Clockwise-Wifi");

  Serial.println("[WiFi] AP 'Clockwise-Wifi' started; Improv Serial still available");
}

void WiFiController::onConnected()
{
  // Persist first: covers the portal path (Improv already saved its own).
  persistCredentials(WiFi.SSID().c_str(), WiFi.psk().c_str());

  // 关掉 WiFi 省电（modem sleep）。开省电时实测局域网 ping 抖动到 200~700ms，
  // TCP 吞吐被 RTT 限制在 10KB/s 量级，31KB 的设置页根本加载不完。
  // 挂钟走 USB 供电，不差这点电。
  // 连 set 两次：WiFiManager 在配网流程结束后有可能把 PS 状态改回去。
  WiFi.setSleep(WIFI_PS_NONE);
  delay(30);
  WiFi.setSleep(WIFI_PS_NONE);

  WiFiManager &wm = wifiManager();
  if (wm.getConfigPortalActive())
    wm.stopConfigPortal(); // frees the AP and port 80

  connectionSucessfulOnce = true;
  networkReady() = true;

  ClockwiseWebServer::getInstance()->startWebServer();
  if (MDNS.begin("clockwise"))
  {
    MDNS.addService("http", "tcp", 80);
  }

  Serial.printf("[WiFi] Connected to %s, IP address %s\n", WiFi.SSID().c_str(), WiFi.localIP().toString().c_str());
}

void WiFiController::begin()
{
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();

  improvSerial.setDeviceInfo(ImprovTypes::ChipFamily::CF_ESP32, CW_FW_NAME, CW_FW_VERSION, "Clockwise");
  improvSerial.onImprovError(onImprovWiFiErrorCb);
  improvSerial.onImprovConnected(onImprovWiFiConnectedCb);

  ClockwiseParams *params = ClockwiseParams::getInstance();
  params->load();

  if (setupFsm.begin(!params->wifiSsid.isEmpty(), millis()) == cw::WiFiSetupAction::StartStationConnect)
  {
    Serial.printf("[WiFi] Connecting to %s\n", params->wifiSsid.c_str());
    WiFi.begin(params->wifiSsid.c_str(), params->wifiPwd.c_str());
  }
  else
  {
    Serial.println("[WiFi] No stored credentials, waiting for Improv Serial");
  }
}

bool WiFiController::update()
{
  const bool improvActivity = handleImprovWiFi();

  WiFiManager &wm = wifiManager();
  if (wm.getConfigPortalActive())
    wm.process();

  switch (setupFsm.update(millis(), improvSerial.isConnected(), improvActivity))
  {
  case cw::WiFiSetupAction::EnterImprovWait:
    Serial.println("[WiFi] Stored credentials failed, waiting for Improv Serial");
    WiFi.disconnect(); // stop retrying stale credentials in the background
    break;

  case cw::WiFiSetupAction::StartApPortal:
    startApPortal();
    break;

  case cw::WiFiSetupAction::Connected:
    onConnected();
    return true;

  case cw::WiFiSetupAction::Restart:
    StatusController::getInstance()->wifiConnectionFailed("WiFi Failed");
    StatusController::getInstance()->forceRestart();
    break;

  default:
    break;
  }
  return false;
}

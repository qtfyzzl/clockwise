#pragma once

// 非阻塞的 Wi-Fi 配网。
//
// begin() 立即返回，update() 必须在每次 loop() 里调用。
// Improv Serial 在所有状态下都会被服务，所以 ESP-Web-Tools 随时能连上设备
// （包括 WiFiManager 的 AP 配网页运行期间）。
//
// 计时与状态迁移都在 cw::WiFiSetupStateMachine（纯逻辑、有原生单测），
// 这个类只负责执行副作用（WiFi、WiFiManager、屏幕、NVS）。

#include "ImprovWiFiLibrary.h"
#include <WiFi.h>
#include <ESPmDNS.h>
#include "CWWebServer.h"
#include "StatusController.h"
#include <WiFiManager.h>
#include "WiFiSetupStateMachine.h"

// Improv Serial 实例，定义在 WiFiController.cpp。
// 原来直接写在头文件里，只要有第二个编译单元包含它就会重复定义。
extern ImprovWiFi improvSerial;

struct WiFiController
{
  long elapsedTimeOffline = 0;
  bool connectionSucessfulOnce = false;

  // 每次 loop() 最多解析多少字节，避免拖慢画面刷新
  static const uint16_t IMPROV_MAX_BYTES_PER_PASS = 256;

  cw::WiFiSetupStateMachine setupFsm;

  static WiFiManager &wifiManager();
  static bool &networkReady();
  static void persistCredentials(const char *ssid, const char *password);
  static void onImprovWiFiErrorCb(ImprovTypes::Error err);
  static void onImprovWiFiConnectedCb(const char *ssid, const char *password);

  bool isConnected();
  static bool handleImprovWiFi();
  void startApPortal();
  void onConnected();
  void begin();
  bool update();
};

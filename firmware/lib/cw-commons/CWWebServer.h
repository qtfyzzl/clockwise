#pragma once

// Clockwise 的 HTTP 服务。
//
// 设计约束（踩过坑，别改回去）：
//   1. ESP32 的 WiFiServer 是**单连接**的：同一时刻只能服务一个客户端。
//      所以每个连接的读、写都必须有超时，否则一个"连上不发数据"的客户端
//      （浏览器预连接 / curl 超时中断 / 端口扫描）就能把整个 loop() 卡死，
//      表现为「ping 能通但 HTTP 永不响应、屏幕冻结」。
//   2. 响应体必须分块写。一次性 client.print(32KB) 实测只有 255 B/s，
//      而且缓冲满时 write 会阻塞到超时才返回，主循环被长期占住。
//   3. 设置页以 gzip 形式发送（32KB → 11.9KB），解压由浏览器完成。

#include <WiFi.h>
#include <SPIFFS.h>
#include <vector>
#include <algorithm>
#include <CWPreferences.h>

#ifndef CLOCKFACE_NAME
#define CLOCKFACE_NAME "UNKNOWN"
#endif

struct ClockwiseWebServer
{
  // ---- 超时与分块大小（集中在这里，避免散落成魔法数字）----
  static constexpr unsigned long REQUEST_TIMEOUT_MS = 2000;  // 读请求行的上限
  static constexpr unsigned long WRITE_TIMEOUT_MS = 8000;    // 写响应的总上限
  static constexpr unsigned long SOCKET_TIMEOUT_MS = 150;    // 单次 write 的阻塞上限
  static constexpr size_t WRITE_CHUNK = 2048;                // 每次 write 的字节数
  static constexpr size_t MAX_THEME_NAME = 40;
  static constexpr long MAX_UPLOAD_BYTES = 60000;
  static constexpr unsigned long UPLOAD_IDLE_TIMEOUT_MS = 8000;

  // 当前编译进来的主题名。不能用 CLOCKFACE_NAME 宏：该宏定义在主题库的
  // Clockface.h 里，而 cw-commons 是独立编译的库，预处理时看不到它，
  // 永远落到 "UNKNOWN"。由 main.cpp 在 setup() 里把真实值赋进来。
  const char *clockfaceName = "UNKNOWN";

  // 置 true 后下一次 handleHttpRequest() 会重启设备（响应已经先发出去）
  bool force_restart = false;

  static ClockwiseWebServer *getInstance();

  void startWebServer();
  void stopWebServer();
  void handleHttpRequest();

  // 切到下一个本地主题（只写 NVS，调用方负责重启）。没有可切的主题时返回 false。
  static bool rotateToNextTheme();

  // 任意一个本地主题名；一个都没有时返回空串。
  // 启动时若 canvasFile 指向的文件已不存在，用它兜底，避免屏幕停在报错页。
  static String firstLocalTheme();

  // SPIFFS 是否挂载成功。挂载失败时不自动格式化（那会清空用户所有主题），
  // 由用户在设置页显式触发 formatFilesystem()。
  static bool filesystemReady();
  static bool formatFilesystem();

  static std::vector<String> listLocalThemes();

private:
  String httpBuffer;

  // ---- 请求分发 ----
  void processRequest(WiFiClient &client, const String &method, const String &path,
                      const String &key, const String &value);
  void applySetting(const String &key, const String &value);

  // ---- 各个端点 ----
  void sendSettingsPage(WiFiClient &client);
  void getCurrentSettings(WiFiClient &client);
  void listThemes(WiFiClient &client);
  void sendThemeFile(WiFiClient &client, const String &name);
  void handleThemeUpload(WiFiClient &client, const String &name);
  void handleThemeDelete(WiFiClient &client, const String &name);
  void readPin(WiFiClient &client, const String &key, uint16_t pin);

  // ---- 工具 ----
  // 分块写 + 超时。客户端不收就放弃，绝不让主循环被拖住。
  static void writeChunked(WiFiClient &client, const uint8_t *data, size_t len,
                           unsigned long timeoutMs,
                           unsigned long socketTimeoutMs = SOCKET_TIMEOUT_MS);
  static void sendStatus(WiFiClient &client, const char *statusLine);
  // HTTP 头只能放 latin1，中文必须 percent 编码，前端 decodeURIComponent 还原
  static String urlEncode(const char *s);

  // ---- 主题文件 ----
  static bool isValidThemeName(const String &name);
  static String themePath(const String &name);
};

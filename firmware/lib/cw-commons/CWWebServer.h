#pragma once

#include <WiFi.h>
#include <SPIFFS.h>
#include <vector>
#include <algorithm>
#include <CWPreferences.h>
#include "StatusController.h"
#include "SettingsWebPage.h"
#include "SettingsWebPage_gz.h"   // 由 tools/gzip_page.py 生成

#ifndef CLOCKFACE_NAME
  #define CLOCKFACE_NAME "UNKNOWN"
#endif

WiFiServer server(80);

struct ClockwiseWebServer
{
  String httpBuffer;
  bool force_restart;
  // 当前编译进来的主题名。
  // 不能用 CLOCKFACE_NAME 宏：该宏定义在主题库的 Clockface.h 里，
  // 而 cw-commons 是独立编译的库，预处理时看不到它，永远落到 "UNKNOWN"。
  // 由 main.cpp 在 setup() 里把真实的 CLOCKFACE_NAME 赋进来。
  const char* clockfaceName = "UNKNOWN";
  const char* HEADER_TEMPLATE_D = "X-%s: %d\r\n";
  const char* HEADER_TEMPLATE_S = "X-%s: %s\r\n";

  // HTTP 头部按规范只允许 latin1 字节，把 UTF-8 中文直接塞进去，
  // 浏览器会按单字节解码 → 设置页里 WiFi 名变成乱码。
  // 这里把值做 percent 编码成纯 ASCII，前端 decodeURIComponent 还原。
  static String urlEncode(const char *s)
  {
    static const char *hex = "0123456789ABCDEF";
    String out;
    if (!s)
      return out;
    out.reserve(strlen(s) * 3);
    for (; *s; ++s)
    {
      uint8_t c = (uint8_t)*s;
      if ((c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') ||
          (c >= 'a' && c <= 'z') || c == '-' || c == '_' || c == '.' || c == '~')
      {
        out += (char)c;
      }
      else
      {
        out += '%';
        out += hex[c >> 4];
        out += hex[c & 0x0F];
      }
    }
    return out;
  }
 
  static ClockwiseWebServer *getInstance()
  {
    static ClockwiseWebServer base;
    return &base;
  }

  void startWebServer()
  {
    server.begin();
    StatusController::getInstance()->blink_led(100, 3);
  }

  void stopWebServer()
  {
    server.stop();
  }

  void handleHttpRequest()
  {
    if (force_restart)
      StatusController::getInstance()->forceRestart();


    WiFiClient client = server.available();
    if (client)
    {
      StatusController::getInstance()->blink_led(100, 1);

      // 关掉 Nagle：默认开启时，小包会被攒着等确认，和对方的延迟 ACK
      // 撞在一起会退化成「每约 1 秒发一个小包」。设置页有 31KB，
      // 实测只有 255 B/s，40 秒都发不完，浏览器里就表现为"页面加载不出来/预览不出来"。
      client.setNoDelay(true);
      client.setTimeout(1000);

      // 必须给这个读循环加超时：浏览器会「预连接」、curl 超时会中断、
      // 扫描器连上就关——这些都会让 client.connected() 一直为 true 而
      // available() 一直是 0，于是死循环卡住整个 loop()，表现为
      // 「ping 能通但 HTTP 永远不响应、屏幕冻结」，只能复位恢复。
      const unsigned long requestDeadline = millis() + 2000;

      while (client.connected() && millis() < requestDeadline)
      {
        if (client.available())
        {
          char c = client.read();
          httpBuffer.concat(c);

          if (c == '\n')
          {
            // 用 int 而不是 uint8_t：URL 带长查询串时索引会超过 255，截断后解析全错
            const int method_pos = httpBuffer.indexOf(' ');
            const int path_pos = httpBuffer.indexOf(' ', method_pos + 1);
            if (method_pos <= 0 || path_pos <= 0)
            {
              httpBuffer = "";
              break; // 不是合法请求行，丢弃
            }

            String method = httpBuffer.substring(0, method_pos);
            String path = httpBuffer.substring(method_pos + 1, path_pos);
            String key = "";
            String value = "";

            if (path.indexOf('?') > 0)
            {
              key = path.substring(path.indexOf('?') + 1, path.indexOf('='));
              value = path.substring(path.indexOf('=') + 1);
              path = path.substring(0, path.indexOf('?'));
            }

            processRequest(client, method, path, key, value);
            httpBuffer = "";
            break;
          }
        }
        else
        {
          delay(1); // 让出 CPU，避免空转把看门狗和 Web 服务都拖死
        }
      }

      httpBuffer = ""; // 半截请求直接丢弃，不要带到下一次连接
      delay(1);
      client.stop();
    }
  }

  void processRequest(WiFiClient client, String method, String path, String key, String value)
  {
    if (method == "GET" && path == "/") {
      client.println("HTTP/1.0 200 OK");
      // 必须带 charset，否则浏览器按本地默认编码（中文 Windows 是 GBK）解析，
      // 页面里的中文和中文 SSID 会变成乱码。
      client.println("Content-Type: text/html; charset=utf-8");
      // 发送的是预压缩过的页面（32KB -> 11.9KB）。解压由浏览器完成，
      // 设备只负责把字节发出去，弱链路下省掉近 2/3 的传输时间。
      client.println("Content-Encoding: gzip");
      client.println("Cache-Control: no-store, must-revalidate");
      client.printf("Content-Length: %u\r\n", (unsigned)SETTINGS_PAGE_GZ_LEN);
      client.println();

      // 分块写 + 超时：客户端连上却不读数据时会阻塞，绝不能让 loop() 卡死。
      const uint8_t *p = SETTINGS_PAGE_GZ;
      size_t remaining = SETTINGS_PAGE_GZ_LEN;
      const unsigned long writeDeadline = millis() + 8000;
      client.setTimeout(150);
      while (remaining > 0 && millis() < writeDeadline)
      {
        size_t n = remaining > 2048 ? 2048 : remaining;
        size_t written = client.write(p, n);
        if (written == 0)
        {
          if (!client.connected())
            break;
          delay(1);
          continue;
        }
        p += written;
        remaining -= written;
        delay(0);
      }
    } else if (method == "GET" && path == "/get") {
      getCurrentSettings(client);
    } else if (method == "GET" && path == "/themes") {
      listThemes(client);
    } else if (method == "GET" && path == "/theme") {
      // 回读某个主题的 JSON 原文（设置页做预览用）
      sendThemeFile(client, value);
    } else if (method == "GET" && path == "/read") {
      if (key == "pin") {
        readPin(client, key, value.toInt());
      }
    } else if (method == "POST" && path == "/restart") {
      client.println("HTTP/1.0 204 No Content");
      force_restart = true;
    } else if (method == "POST" && path == "/theme") {
      // 上传 Canvas 主题 JSON 到 SPIFFS。文件名通过 ?name=xxx 传。
      handleThemeUpload(client, value);
    } else if (method == "POST" && path == "/theme-delete") {
      handleThemeDelete(client, value);
    } else if (method == "POST" && path == "/rotate") {
      bool ok = rotateToNextTheme();
      Serial.printf("[FS] 手动切换主题: %s\n", ok ? "成功，重启中" : "没有可切换的主题");
      client.println("HTTP/1.0 204 No Content");
      client.println();
      if (ok)
      {
        delay(300);
        ESP.restart();
      }
    } else if (method == "POST" && path == "/set") {
      ClockwiseParams::getInstance()->load();
      //a baby seal has died due this ifs
      if (key == ClockwiseParams::getInstance()->PREF_DISPLAY_BRIGHT) {
        ClockwiseParams::getInstance()->displayBright = value.toInt();
      } else if (key == ClockwiseParams::getInstance()->PREF_WIFI_SSID) {
        ClockwiseParams::getInstance()->wifiSsid = value;
      } else if (key == ClockwiseParams::getInstance()->PREF_WIFI_PASSWORD) {
        ClockwiseParams::getInstance()->wifiPwd = value;
      } else if (key == "autoBright") {   //autoBright=0010,0800
        ClockwiseParams::getInstance()->autoBrightMin = value.substring(0,4).toInt();
        ClockwiseParams::getInstance()->autoBrightMax = value.substring(5,9).toInt();
      } else if (key == ClockwiseParams::getInstance()->PREF_SWAP_BLUE_GREEN) {
        ClockwiseParams::getInstance()->swapBlueGreen = (value == "1");
      } else if (key == ClockwiseParams::getInstance()->PREF_SWAP_BLUE_RED) {
        ClockwiseParams::getInstance()->swapBlueRed = (value == "1");
      } else if (key == ClockwiseParams::getInstance()->PREF_USE_24H_FORMAT) {
        ClockwiseParams::getInstance()->use24hFormat = (value == "1");
      } else if (key == ClockwiseParams::getInstance()->PREF_LDR_PIN) {
        ClockwiseParams::getInstance()->ldrPin = value.toInt();
      } else if (key == ClockwiseParams::getInstance()->PREF_TIME_ZONE) {
        ClockwiseParams::getInstance()->timeZone = value;
      } else if (key == ClockwiseParams::getInstance()->PREF_NTP_SERVER) {
        ClockwiseParams::getInstance()->ntpServer = value;
      } else if (key == ClockwiseParams::getInstance()->PREF_CANVAS_FILE) {
        ClockwiseParams::getInstance()->canvasFile = value;
      } else if (key == ClockwiseParams::getInstance()->PREF_CANVAS_SERVER) {
        ClockwiseParams::getInstance()->canvasServer = value;
      } else if (key == ClockwiseParams::getInstance()->PREF_MANUAL_POSIX) {
        ClockwiseParams::getInstance()->manualPosix = value;
      } else if (key == ClockwiseParams::getInstance()->PREF_DISPLAY_ROTATION) {
        ClockwiseParams::getInstance()->displayRotation = value.toInt();
      } else if (key == ClockwiseParams::getInstance()->PREF_DRIVER) {
        ClockwiseParams::getInstance()->driver = value.toInt();
      }  else if (key == ClockwiseParams::getInstance()->PREF_I2CSPEED) {
        ClockwiseParams::getInstance()->i2cSpeed = value.toInt();
      }  else if (key == ClockwiseParams::getInstance()->PREF_E_PIN) {
        ClockwiseParams::getInstance()->E_pin = value.toInt();
      } else if (key == ClockwiseParams::getInstance()->PREF_AUTO_ROTATE) {
        ClockwiseParams::getInstance()->autoRotate = (value == "1");
      }
      ClockwiseParams::getInstance()->save();
      client.println("HTTP/1.0 204 No Content");
    }
  }



  // 把主题 JSON 原文发给浏览器（设置页预览用）。分块写，避免一次性拼大 String。
  void sendThemeFile(WiFiClient &client, String name)
  {
    if (name.length() == 0 || name.indexOf("..") >= 0 || name.indexOf('/') >= 0)
    {
      client.println("HTTP/1.0 400 Bad Request");
      client.println();
      return;
    }

    String path = "/" + name + ".json";
    if (!SPIFFS.exists(path))
    {
      client.println("HTTP/1.0 404 Not Found");
      client.println();
      return;
    }

    File f = SPIFFS.open(path, FILE_READ);
    if (!f)
    {
      client.println("HTTP/1.0 500 Internal Server Error");
      client.println();
      return;
    }

    client.println("HTTP/1.0 200 OK");
    client.println("Content-Type: application/json; charset=utf-8");
    client.println("Cache-Control: no-store");
    client.printf("Content-Length: %u\r\n", (unsigned)f.size());
    client.println();

    uint8_t buf[2048];
    const unsigned long writeDeadline = millis() + 5000;
    client.setTimeout(150);
    while (f.available() && millis() < writeDeadline)
    {
      size_t n = f.read(buf, sizeof(buf));
      if (n == 0)
        break;
      size_t written = client.write(buf, n);
      if (written == 0)
      {
        if (!client.connected())
          break;
        delay(1);
        continue;
      }
      delay(0);
    }
    f.close();
    // 注意：这里不能再 println()，否则响应体会比 Content-Length 多出 2 字节
  }

  // 上传 Canvas 主题 JSON 到 SPIFFS。
  // 外层 handleHttpRequest 是逐字节读到 '\n' 就 break 的，所以这里还需要
  // 自己把剩余请求头和 body 读完（Content-Length 指定长度）。
  void handleThemeUpload(WiFiClient &client, String name)
  {
    client.setTimeout(1000); // 单位是毫秒；原来设 5 太短，慢客户端读请求头会失败

    long contentLength = -1;
    while (client.connected())
    {
      String line = client.readStringUntil('\n');
      line.trim();
      if (line.length() == 0)
        break; // 空行 = 头部结束
      if (line.startsWith("Content-Length:"))
        contentLength = line.substring(15).toInt();
      else if (line.startsWith("content-length:"))
        contentLength = line.substring(15).toInt();
    }

    if (name.length() == 0 || name.length() > 40 || contentLength <= 0 || contentLength > 60000)
    {
      Serial.printf("[FS] 上传参数非法 name='%s' len=%ld\n", name.c_str(), contentLength);
      client.println("HTTP/1.0 400 Bad Request");
      client.println();
      return;
    }

    String path = "/" + name + ".json";
    File f = SPIFFS.open(path, FILE_WRITE);
    if (!f)
    {
      Serial.printf("[FS] 无法创建 %s\n", path.c_str());
      client.println("HTTP/1.0 500 Internal Server Error");
      client.println();
      return;
    }

    uint8_t buf[512];
    long remaining = contentLength;
    unsigned long lastData = millis();

    while (remaining > 0 && (millis() - lastData) < 8000)
    {
      size_t want = remaining < (long)sizeof(buf) ? (size_t)remaining : sizeof(buf);
      int n = client.read(buf, want);
      if (n > 0)
      {
        f.write(buf, n);
        remaining -= n;
        lastData = millis();
      }
      else
      {
        delay(1);
      }
    }
    f.close();

    if (remaining > 0)
    {
      Serial.printf("[FS] 上传中断，还差 %ld 字节\n", remaining);
      SPIFFS.remove(path);
      client.println("HTTP/1.0 500 Internal Server Error");
      client.println();
      return;
    }

    // 顺手把 canvasFile 指向刚上传的文件，前端就不用再单独设置一次
    ClockwiseParams::getInstance()->load();
    ClockwiseParams::getInstance()->canvasFile = name;
    ClockwiseParams::getInstance()->save();

    Serial.printf("[FS] 主题已保存 %s (%ld 字节), SPIFFS 已用 %u/%u\n",
                  path.c_str(), contentLength,
                  (unsigned)SPIFFS.usedBytes(), (unsigned)SPIFFS.totalBytes());

    client.println("HTTP/1.0 204 No Content");
    client.println();
  }

  void handleThemeDelete(WiFiClient &client, String name)
  {
    if (name.length() == 0 || name.indexOf("..") >= 0 || name.indexOf('/') >= 0)
    {
      client.println("HTTP/1.0 400 Bad Request");
      client.println();
      return;
    }
    String path = "/" + name + ".json";
    bool ok = SPIFFS.remove(path);
    Serial.printf("[FS] 删除 %s -> %s\n", path.c_str(), ok ? "成功" : "文件不存在");

    // 如果删掉的正是当前主题，自动切到剩下的任意一个，
    // 否则重启后既没有本地文件、远程也可能拉不到，屏幕会停在报错页。
    ClockwiseParams::getInstance()->load();
    if (ok && ClockwiseParams::getInstance()->canvasFile == name)
    {
      String next = firstLocalTheme();
      ClockwiseParams::getInstance()->canvasFile = next; // 没有其它主题就清空
      ClockwiseParams::getInstance()->save();
      Serial.printf("[FS] 当前主题被删除，切换到 '%s'\n", next.c_str());
    }

    client.println("HTTP/1.0 204 No Content");
    client.println();
  }

  // 返回任意一个本地主题名（用于删除当前主题后的兜底）
  static String firstLocalTheme()
  {
    File root = SPIFFS.open("/");
    if (!root)
      return "";
    String found = "";
    File f = root.openNextFile();
    while (f)
    {
      String n = f.name();
      if (n.endsWith(".json"))
      {
        int s = n.lastIndexOf('/');
        if (s >= 0)
          n = n.substring(s + 1);
        found = n.substring(0, n.length() - 5);
        break;
      }
      f = root.openNextFile();
    }
    root.close();
    return found;
  }

  // 找出按名字字母序排在 current 之后的下一个本地主题；没有则返回空。
  static String nextLocalTheme(const String &current)
  {
    std::vector<String> names;

    File root = SPIFFS.open("/");
    if (!root)
      return "";

    File f = root.openNextFile();
    while (f)
    {
      String n = f.name();
      if (n.endsWith(".json"))
      {
        int s = n.lastIndexOf('/');
        if (s >= 0)
          n = n.substring(s + 1);
        names.push_back(n.substring(0, n.length() - 5));
      }
      f = root.openNextFile();
    }
    root.close();

    if (names.empty())
      return "";

    std::sort(names.begin(), names.end());
    for (size_t i = 0; i < names.size(); i++)
    {
      if (names[i] == current)
        return names[(i + 1) % names.size()];
    }
    return names[0];
  }

  // 切到下一个本地主题并重启（立即生效）。
  static bool rotateToNextTheme()
  {
    ClockwiseParams::getInstance()->load();
    String next = nextLocalTheme(ClockwiseParams::getInstance()->canvasFile);
    if (next.length() == 0)
      return false;

    Serial.printf("[FS] 切换主题 %s -> %s\n",
                  ClockwiseParams::getInstance()->canvasFile.c_str(), next.c_str());
    ClockwiseParams::getInstance()->canvasFile = next;
    ClockwiseParams::getInstance()->save();
    return true;
  }

  // 列出 SPIFFS 里所有主题，每行一个名字（不含 .json），纯文本返回。
  void listThemes(WiFiClient &client)
  {
    client.println("HTTP/1.0 200 OK");
    client.println("Content-Type: text/plain; charset=utf-8");
    client.println("Cache-Control: no-store");
    client.println();

    File root = SPIFFS.open("/");
    if (!root)
    {
      client.println();
      return;
    }

    File f = root.openNextFile();
    while (f)
    {
      String n = f.name();
      if (n.endsWith(".json"))
      {
        int slash = n.lastIndexOf('/');
        if (slash >= 0)
          n = n.substring(slash + 1);
        n = n.substring(0, n.length() - 5);
        client.println(n);
      }
      f = root.openNextFile();
    }
    root.close();
    client.println();
  }


  void readPin(WiFiClient client, String key, uint16_t pin) {
    ClockwiseParams::getInstance()->load();

    client.println("HTTP/1.0 204 No Content");
    client.printf(HEADER_TEMPLATE_D, key, analogRead(pin));

    client.println();
  }


  void getCurrentSettings(WiFiClient client) {
    ClockwiseParams::getInstance()->load();

    client.println("HTTP/1.0 204 No Content");

    client.printf(HEADER_TEMPLATE_D, ClockwiseParams::getInstance()->PREF_DISPLAY_BRIGHT, ClockwiseParams::getInstance()->displayBright);
    client.printf(HEADER_TEMPLATE_D, ClockwiseParams::getInstance()->PREF_DISPLAY_ABC_MIN, ClockwiseParams::getInstance()->autoBrightMin);
    client.printf(HEADER_TEMPLATE_D, ClockwiseParams::getInstance()->PREF_DISPLAY_ABC_MAX, ClockwiseParams::getInstance()->autoBrightMax);
    client.printf(HEADER_TEMPLATE_D, ClockwiseParams::getInstance()->PREF_SWAP_BLUE_GREEN, ClockwiseParams::getInstance()->swapBlueGreen);
    client.printf(HEADER_TEMPLATE_D, ClockwiseParams::getInstance()->PREF_SWAP_BLUE_RED, ClockwiseParams::getInstance()->swapBlueRed);
    client.printf(HEADER_TEMPLATE_D, ClockwiseParams::getInstance()->PREF_USE_24H_FORMAT, ClockwiseParams::getInstance()->use24hFormat);
    client.printf(HEADER_TEMPLATE_D, ClockwiseParams::getInstance()->PREF_LDR_PIN, ClockwiseParams::getInstance()->ldrPin);    

    // ---- 字符串类参数：必须 percent 编码，否则中文（SSID 等）在响应头里会乱码 ----
    String enc;

    enc = urlEncode(ClockwiseParams::getInstance()->timeZone.c_str());
    client.printf(HEADER_TEMPLATE_S, ClockwiseParams::getInstance()->PREF_TIME_ZONE, enc.c_str());

    enc = urlEncode(ClockwiseParams::getInstance()->wifiSsid.c_str());
    client.printf(HEADER_TEMPLATE_S, ClockwiseParams::getInstance()->PREF_WIFI_SSID, enc.c_str());

    enc = urlEncode(ClockwiseParams::getInstance()->ntpServer.c_str());
    client.printf(HEADER_TEMPLATE_S, ClockwiseParams::getInstance()->PREF_NTP_SERVER, enc.c_str());

    enc = urlEncode(ClockwiseParams::getInstance()->canvasFile.c_str());
    client.printf(HEADER_TEMPLATE_S, ClockwiseParams::getInstance()->PREF_CANVAS_FILE, enc.c_str());

    enc = urlEncode(ClockwiseParams::getInstance()->canvasServer.c_str());
    client.printf(HEADER_TEMPLATE_S, ClockwiseParams::getInstance()->PREF_CANVAS_SERVER, enc.c_str());

    enc = urlEncode(ClockwiseParams::getInstance()->manualPosix.c_str());
    client.printf(HEADER_TEMPLATE_S, ClockwiseParams::getInstance()->PREF_MANUAL_POSIX, enc.c_str());

    client.printf(HEADER_TEMPLATE_D, ClockwiseParams::getInstance()->PREF_DISPLAY_ROTATION, ClockwiseParams::getInstance()->displayRotation);
    client.printf(HEADER_TEMPLATE_D, ClockwiseParams::getInstance()->PREF_DRIVER, ClockwiseParams::getInstance()->driver);
    client.printf(HEADER_TEMPLATE_D, ClockwiseParams::getInstance()->PREF_I2CSPEED, ClockwiseParams::getInstance()->i2cSpeed);
    client.printf(HEADER_TEMPLATE_D, ClockwiseParams::getInstance()->PREF_E_PIN, ClockwiseParams::getInstance()->E_pin);
    client.printf(HEADER_TEMPLATE_D, ClockwiseParams::getInstance()->PREF_AUTO_ROTATE, ClockwiseParams::getInstance()->autoRotate);

    // 闪存占用：设置页里显示本地主题用了多少
    client.printf(HEADER_TEMPLATE_D, "fsUsed", (int)SPIFFS.usedBytes());
    client.printf(HEADER_TEMPLATE_D, "fsTotal", (int)SPIFFS.totalBytes());

    client.printf(HEADER_TEMPLATE_S, "CW_FW_VERSION", CW_FW_VERSION);
    client.printf(HEADER_TEMPLATE_S, "CW_FW_NAME", CW_FW_NAME);

    enc = urlEncode(clockfaceName);
    client.printf(HEADER_TEMPLATE_S, "CLOCKFACE_NAME", enc.c_str());
    client.println();
  }
  
};

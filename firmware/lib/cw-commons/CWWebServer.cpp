#include "CWWebServer.h"

#include <Arduino.h>
#include "StatusController.h"
#include "SettingsWebPage.h"
#include "SettingsWebPage_gz.h"   // 由 tools/gzip_page.py 生成

namespace
{
  WiFiServer server(80);

  // 响应头模板：Content-Length 之外的配置都用 X-<key>: <value> 传
  const char *HEADER_INT = "X-%s: %d\r\n";
  const char *HEADER_STR = "X-%s: %s\r\n";

  // 请求行里最多解析这么多字节，防止畸形请求把 httpBuffer 撑爆
  const size_t MAX_REQUEST_LINE = 2048;
}

ClockwiseWebServer *ClockwiseWebServer::getInstance()
{
  static ClockwiseWebServer base;
  return &base;
}

// ---------------------------------------------------------------- 生命周期

void ClockwiseWebServer::startWebServer()
{
  server.begin();
  StatusController::getInstance()->blink_led(100, 3);
}

void ClockwiseWebServer::stopWebServer()
{
  server.stop();
}

// ---------------------------------------------------------------- 工具函数

String ClockwiseWebServer::urlEncode(const char *s)
{
  static const char *hex = "0123456789ABCDEF";
  String out;
  if (!s)
    return out;
  out.reserve(strlen(s) * 3);
  for (; *s; ++s)
  {
    const uint8_t c = (uint8_t)*s;
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

void ClockwiseWebServer::sendStatus(WiFiClient &client, const char *statusLine)
{
  client.println(statusLine);
  client.println();
}

void ClockwiseWebServer::writeChunked(WiFiClient &client, const uint8_t *data, size_t len,
                                      unsigned long timeoutMs, unsigned long socketTimeoutMs)
{
  const unsigned long deadline = millis() + timeoutMs;
  const uint8_t *p = data;
  size_t remaining = len;

  client.setTimeout(socketTimeoutMs);

  while (remaining > 0 && millis() < deadline)
  {
    const size_t n = remaining > WRITE_CHUNK ? WRITE_CHUNK : remaining;
    const size_t written = client.write(p, n);
    if (written == 0)
    {
      if (!client.connected())
        return;         // 对端真的断了
      delay(1);         // 发送缓冲满，等一下再来
      continue;
    }
    p += written;
    remaining -= written;
    delay(0);           // 让 WiFi 任务把缓冲区发出去
  }
}

bool ClockwiseWebServer::isValidThemeName(const String &name)
{
  return name.length() > 0 && name.length() <= MAX_THEME_NAME &&
         name.indexOf("..") < 0 && name.indexOf('/') < 0;
}

String ClockwiseWebServer::themePath(const String &name)
{
  return "/" + name + ".json";
}

std::vector<String> ClockwiseWebServer::listLocalThemes()
{
  std::vector<String> names;

  File root = SPIFFS.open("/");
  if (!root)
    return names;

  File f = root.openNextFile();
  while (f)
  {
    String n = f.name();
    if (n.endsWith(".json"))
    {
      const int slash = n.lastIndexOf('/');
      if (slash >= 0)
        n = n.substring(slash + 1);
      names.push_back(n.substring(0, n.length() - 5));
    }
    f = root.openNextFile();
  }
  root.close();

  std::sort(names.begin(), names.end());
  return names;
}

bool ClockwiseWebServer::filesystemReady()
{
  // 没挂载时 totalBytes() 返回 0（挂载成功至少有几百 KB）
  return SPIFFS.totalBytes() > 0;
}

bool ClockwiseWebServer::formatFilesystem()
{
  Serial.println("[FS] 用户请求格式化 SPIFFS —— 所有本地主题将被删除");
  const bool ok = SPIFFS.format();
  Serial.printf("[FS] 格式化 %s\n", ok ? "成功" : "失败");
  return ok;
}

String ClockwiseWebServer::firstLocalTheme()
{
  const std::vector<String> names = listLocalThemes();
  return names.empty() ? String("") : names[0];
}

// ---------------------------------------------------------------- 请求入口

void ClockwiseWebServer::handleHttpRequest()
{
  if (force_restart)
    StatusController::getInstance()->forceRestart();

  WiFiClient client = server.available();
  if (!client)
    return;

  StatusController::getInstance()->blink_led(100, 1);

  // 关掉 Nagle：默认开启时小包会被攒着等确认，和对方的延迟 ACK 撞在一起
  // 会退化成「每约 1 秒发一个小包」，实测只有 255 B/s。
  client.setNoDelay(true);
  client.setTimeout(1000);

  const unsigned long deadline = millis() + REQUEST_TIMEOUT_MS;

  while (client.connected() && millis() < deadline)
  {
    if (!client.available())
    {
      delay(1);   // 让出 CPU，避免空转把看门狗和 Web 服务一起拖死
      continue;
    }

    const char c = client.read();
    httpBuffer.concat(c);
    if (c != '\n')
    {
      if (httpBuffer.length() > MAX_REQUEST_LINE)
      {
        httpBuffer = "";
        break;    // 畸形请求，丢弃
      }
      continue;
    }

    // 请求行形如：GET /theme?name=pac-man HTTP/1.1
    const int methodPos = httpBuffer.indexOf(' ');
    const int pathPos = httpBuffer.indexOf(' ', methodPos + 1);
    if (methodPos <= 0 || pathPos <= 0)
    {
      httpBuffer = "";
      break;      // 不是合法请求行
    }

    String method = httpBuffer.substring(0, methodPos);
    String path = httpBuffer.substring(methodPos + 1, pathPos);
    String key;
    String value;

    const int queryPos = path.indexOf('?');
    if (queryPos > 0)
    {
      const String query = path.substring(queryPos + 1);
      path = path.substring(0, queryPos);
      const int eq = query.indexOf('=');
      if (eq > 0)
      {
        key = query.substring(0, eq);
        value = query.substring(eq + 1);
      }
      else
      {
        key = query;
      }
    }

    processRequest(client, method, path, key, value);
    httpBuffer = "";
    break;
  }

  httpBuffer = "";   // 半截请求不要带到下一次连接
  delay(1);
  client.stop();
}

void ClockwiseWebServer::processRequest(WiFiClient &client, const String &method,
                                        const String &path, const String &key,
                                        const String &value)
{
  const bool isGet = (method == "GET");
  const bool isPost = (method == "POST");

  if (isGet)
  {
    if (path == "/")
      return sendSettingsPage(client);
    if (path == "/get")
      return getCurrentSettings(client);
    if (path == "/themes")
      return listThemes(client);
    if (path == "/theme")
      return sendThemeFile(client, value);       // 回读原文，设置页做预览用
    if (path == "/read" && key == "pin")
      return readPin(client, key, (uint16_t)value.toInt());
  }
  else if (isPost)
  {
    if (path == "/set")
    {
      applySetting(key, value);
      return sendStatus(client, "HTTP/1.0 204 No Content");
    }
    if (path == "/theme")
      return handleThemeUpload(client, value);
    if (path == "/theme-delete")
      return handleThemeDelete(client, value);
    if (path == "/restart")
    {
      sendStatus(client, "HTTP/1.0 204 No Content");
      force_restart = true;                      // 响应发完后再重启
      return;
    }
    if (path == "/fs-format")
    {
      const bool ok = formatFilesystem();
      sendStatus(client, "HTTP/1.0 204 No Content");
      if (ok)
      {
        delay(300);
        ESP.restart();          // 格式化后主题全没了，重启回到干净状态
      }
      return;
    }
    if (path == "/rotate")
    {
      const bool ok = rotateToNextTheme();
      Serial.printf("[FS] 手动切换主题: %s\n", ok ? "成功，重启中" : "没有可切换的主题");
      sendStatus(client, "HTTP/1.0 204 No Content");
      if (ok)
      {
        delay(300);
        ESP.restart();
      }
      return;
    }
  }

  sendStatus(client, "HTTP/1.0 404 Not Found");
}

// ---------------------------------------------------------------- 参数写入

// 把查询串里的 k=v 落到 ClockwiseParams 上。
// 服务端不做 URL 解码，值原样传入（前端用 encodeURIComponent 只处理了少量字段）。
void ClockwiseWebServer::applySetting(const String &key, const String &value)
{
  ClockwiseParams *p = ClockwiseParams::getInstance();
  p->load();

  if (key == p->PREF_DISPLAY_BRIGHT)
    p->displayBright = value.toInt();
  else if (key == p->PREF_WIFI_SSID)
    p->wifiSsid = value;
  else if (key == p->PREF_WIFI_PASSWORD)
    p->wifiPwd = value;
  else if (key == p->PREF_DISPLAY_ABC_MIN)
    p->autoBrightMin = value.toInt();
  else if (key == p->PREF_DISPLAY_ABC_MAX)
    p->autoBrightMax = value.toInt();
  else if (key == p->PREF_SWAP_BLUE_GREEN)
    p->swapBlueGreen = (value == "1");
  else if (key == p->PREF_SWAP_BLUE_RED)
    p->swapBlueRed = (value == "1");
  else if (key == p->PREF_USE_24H_FORMAT)
    p->use24hFormat = (value == "1");
  else if (key == p->PREF_LDR_PIN)
    p->ldrPin = value.toInt();
  else if (key == p->PREF_TIME_ZONE)
    p->timeZone = value;
  else if (key == p->PREF_NTP_SERVER)
    p->ntpServer = value;
  else if (key == p->PREF_CANVAS_FILE)
    p->canvasFile = value;
  else if (key == p->PREF_CANVAS_SERVER)
    p->canvasServer = value;
  else if (key == p->PREF_MANUAL_POSIX)
    p->manualPosix = value;
  else if (key == p->PREF_DISPLAY_ROTATION)
    p->displayRotation = value.toInt();
  else if (key == p->PREF_DRIVER)
    p->driver = value.toInt();
  else if (key == p->PREF_I2CSPEED)
    p->i2cSpeed = value.toInt();
  else if (key == p->PREF_E_PIN)
    p->E_pin = value.toInt();
  else if (key == p->PREF_AUTO_ROTATE)
    p->autoRotate = (value == "1");
  else if (key == "autoBright")                 // 形如 autoBright=0010,0800
  {
    p->autoBrightMin = value.substring(0, 4).toInt();
    p->autoBrightMax = value.substring(5, 9).toInt();
  }

  p->save();

  // 改完立即生效的两项：亮度直接写寄存器，主题留到下个 /restart
  if (key == p->PREF_DISPLAY_BRIGHT)
    Serial.printf("[Cfg] 亮度 -> %u\n", (unsigned)p->displayBright);
}

// ---------------------------------------------------------------- 端点实现

void ClockwiseWebServer::sendSettingsPage(WiFiClient &client)
{
  client.println("HTTP/1.0 200 OK");
  // 必须带 charset，否则浏览器按本地默认编码（中文 Windows 是 GBK）解析，
  // 页面里的中文和中文 SSID 会变成乱码。
  client.println("Content-Type: text/html; charset=utf-8");
  // 发的是预压缩页面（32KB -> 11.9KB），解压由浏览器完成，
  // 弱链路下省掉 2/3 的传输时间。
  client.println("Content-Encoding: gzip");
  client.println("Cache-Control: no-store, must-revalidate");
  client.printf("Content-Length: %u\r\n", (unsigned)SETTINGS_PAGE_GZ_LEN);
  client.println();

  writeChunked(client, SETTINGS_PAGE_GZ, SETTINGS_PAGE_GZ_LEN, WRITE_TIMEOUT_MS);
}

void ClockwiseWebServer::listThemes(WiFiClient &client)
{
  client.println("HTTP/1.0 200 OK");
  client.println("Content-Type: text/plain; charset=utf-8");
  client.println("Cache-Control: no-store");
  client.println();

  for (const String &name : listLocalThemes())
    client.println(name);

  client.println();
}

void ClockwiseWebServer::sendThemeFile(WiFiClient &client, const String &name)
{
  if (!isValidThemeName(name))
    return sendStatus(client, "HTTP/1.0 400 Bad Request");

  const String path = themePath(name);
  if (!SPIFFS.exists(path))
    return sendStatus(client, "HTTP/1.0 404 Not Found");

  File f = SPIFFS.open(path, FILE_READ);
  if (!f)
    return sendStatus(client, "HTTP/1.0 500 Internal Server Error");

  client.println("HTTP/1.0 200 OK");
  client.println("Content-Type: application/json; charset=utf-8");
  client.println("Cache-Control: no-store");
  client.printf("Content-Length: %u\r\n", (unsigned)f.size());
  client.println();

  // 分块从文件读出来写出去：不能读成一个大 String（堆不够，还会碎片化）
  static uint8_t buf[WRITE_CHUNK];

  const unsigned long deadline = millis() + WRITE_TIMEOUT_MS;
  client.setTimeout(SOCKET_TIMEOUT_MS);
  while (f.available() && millis() < deadline)
  {
    const size_t n = f.read(buf, sizeof(buf));
    if (n == 0)
      break;
    if (client.write(buf, n) == 0)
    {
      if (!client.connected())
        break;
      delay(1);
    }
    else
    {
      delay(0);
    }
  }

  f.close();
  // 注意：这里不能再 println()，否则响应体会比 Content-Length 多出 2 字节
}

void ClockwiseWebServer::handleThemeUpload(WiFiClient &client, const String &name)
{
  // 外层只读到第一行就 break 了，这里要把剩余请求头和 body 读完
  client.setTimeout(1000);

  long contentLength = -1;
  while (client.connected())
  {
    String line = client.readStringUntil('\n');
    line.trim();
    if (line.length() == 0)
      break;                              // 空行 = 头部结束
    if (line.startsWith("Content-Length:") || line.startsWith("content-length:"))
      contentLength = line.substring(15).toInt();
  }

  if (!isValidThemeName(name) || contentLength <= 0 || contentLength > MAX_UPLOAD_BYTES)
  {
    Serial.printf("[FS] 上传参数非法 name='%s' len=%ld\n", name.c_str(), contentLength);
    return sendStatus(client, "HTTP/1.0 400 Bad Request");
  }

  const String path = themePath(name);
  File f = SPIFFS.open(path, FILE_WRITE);
  if (!f)
  {
    Serial.printf("[FS] 无法创建 %s（SPIFFS 是否已满？已用 %u/%u）\n",
                  path.c_str(), (unsigned)SPIFFS.usedBytes(), (unsigned)SPIFFS.totalBytes());
    return sendStatus(client, "HTTP/1.0 500 Internal Server Error");
  }

  uint8_t buf[512];
  long remaining = contentLength;
  unsigned long lastData = millis();

  while (remaining > 0 && (millis() - lastData) < UPLOAD_IDLE_TIMEOUT_MS)
  {
    const size_t want = remaining < (long)sizeof(buf) ? (size_t)remaining : sizeof(buf);
    const int n = client.read(buf, want);
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
    // 半截文件留着会污染主题列表，直接删掉
    Serial.printf("[FS] 上传中断，还差 %ld 字节，已删除 %s\n", remaining, path.c_str());
    SPIFFS.remove(path);
    return sendStatus(client, "HTTP/1.0 500 Internal Server Error");
  }

  // 上传成功后顺手把当前主题指向它，前端就不用再单独设一次
  ClockwiseParams *p = ClockwiseParams::getInstance();
  p->load();
  p->canvasFile = name;
  p->save();

  Serial.printf("[FS] 主题已保存 %s (%ld 字节), SPIFFS 已用 %u/%u\n",
                path.c_str(), contentLength,
                (unsigned)SPIFFS.usedBytes(), (unsigned)SPIFFS.totalBytes());

  sendStatus(client, "HTTP/1.0 204 No Content");
}

void ClockwiseWebServer::handleThemeDelete(WiFiClient &client, const String &name)
{
  if (!isValidThemeName(name))
    return sendStatus(client, "HTTP/1.0 400 Bad Request");

  const String path = themePath(name);
  const bool removed = SPIFFS.remove(path);
  Serial.printf("[FS] 删除 %s -> %s\n", path.c_str(), removed ? "成功" : "文件不存在");

  // 删掉的正好是当前主题时自动切到别的，否则重启后既没本地文件、
  // 远程也可能拉不到，屏幕会停在报错页。
  ClockwiseParams *p = ClockwiseParams::getInstance();
  p->load();
  if (removed && p->canvasFile == name)
  {
    const std::vector<String> rest = listLocalThemes();
    p->canvasFile = rest.empty() ? "" : rest[0];
    p->save();
    Serial.printf("[FS] 当前主题被删除，切换到 '%s'\n", p->canvasFile.c_str());
  }

  sendStatus(client, "HTTP/1.0 204 No Content");
}

void ClockwiseWebServer::readPin(WiFiClient &client, const String &key, uint16_t pin)
{
  ClockwiseParams::getInstance()->load();
  client.println("HTTP/1.0 204 No Content");
  client.printf(HEADER_INT, key.c_str(), analogRead(pin));
  client.println();
}

void ClockwiseWebServer::getCurrentSettings(WiFiClient &client)
{
  ClockwiseParams *p = ClockwiseParams::getInstance();
  p->load();

  client.println("HTTP/1.0 204 No Content");

  client.printf(HEADER_INT, p->PREF_DISPLAY_BRIGHT, p->displayBright);
  client.printf(HEADER_INT, p->PREF_DISPLAY_ABC_MIN, p->autoBrightMin);
  client.printf(HEADER_INT, p->PREF_DISPLAY_ABC_MAX, p->autoBrightMax);
  client.printf(HEADER_INT, p->PREF_SWAP_BLUE_GREEN, p->swapBlueGreen);
  client.printf(HEADER_INT, p->PREF_SWAP_BLUE_RED, p->swapBlueRed);
  client.printf(HEADER_INT, p->PREF_USE_24H_FORMAT, p->use24hFormat);
  client.printf(HEADER_INT, p->PREF_LDR_PIN, p->ldrPin);
  client.printf(HEADER_INT, p->PREF_DISPLAY_ROTATION, p->displayRotation);
  client.printf(HEADER_INT, p->PREF_DRIVER, p->driver);
  client.printf(HEADER_INT, p->PREF_I2CSPEED, p->i2cSpeed);
  client.printf(HEADER_INT, p->PREF_E_PIN, p->E_pin);
  client.printf(HEADER_INT, p->PREF_AUTO_ROTATE, p->autoRotate);

  // 字符串类参数必须 percent 编码，否则中文（SSID 等）在响应头里会乱码
  client.printf(HEADER_STR, p->PREF_TIME_ZONE, urlEncode(p->timeZone.c_str()).c_str());
  client.printf(HEADER_STR, p->PREF_WIFI_SSID, urlEncode(p->wifiSsid.c_str()).c_str());
  client.printf(HEADER_STR, p->PREF_NTP_SERVER, urlEncode(p->ntpServer.c_str()).c_str());
  client.printf(HEADER_STR, p->PREF_CANVAS_FILE, urlEncode(p->canvasFile.c_str()).c_str());
  client.printf(HEADER_STR, p->PREF_CLOCKFACE_ENGINE, urlEncode(p->clockfaceEngine.c_str()).c_str());
  client.printf(HEADER_STR, p->PREF_CANVAS_SERVER, urlEncode(p->canvasServer.c_str()).c_str());
  client.printf(HEADER_STR, p->PREF_MANUAL_POSIX, urlEncode(p->manualPosix.c_str()).c_str());

  // 闪存占用与挂载状态：设置页据此提示"存储未就绪"
  client.printf(HEADER_INT, "fsReady", filesystemReady() ? 1 : 0);
  client.printf(HEADER_INT, "fsUsed", (int)SPIFFS.usedBytes());
  client.printf(HEADER_INT, "fsTotal", (int)SPIFFS.totalBytes());

  client.printf(HEADER_STR, "CW_FW_VERSION", CW_FW_VERSION);
  client.printf(HEADER_STR, "CW_FW_NAME", CW_FW_NAME);
  client.printf(HEADER_STR, "CLOCKFACE_NAME", urlEncode(clockfaceName).c_str());

  client.println();
}

// ---------------------------------------------------------------- 主题轮播

bool ClockwiseWebServer::rotateToNextTheme()
{
  ClockwiseParams *p = ClockwiseParams::getInstance();
  p->load();

  const std::vector<String> names = listLocalThemes();
  if (names.empty())
    return false;

  // 按字母序找下一个，末尾回到第一个；当前主题不在列表里时从第一个开始
  size_t next = 0;
  for (size_t i = 0; i < names.size(); i++)
  {
    if (names[i] == p->canvasFile)
    {
      next = (i + 1) % names.size();
      break;
    }
  }

  Serial.printf("[FS] 切换主题 %s -> %s\n", p->canvasFile.c_str(), names[next].c_str());
  p->canvasFile = names[next];
  p->save();
  return true;
}

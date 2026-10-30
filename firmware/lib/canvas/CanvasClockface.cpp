
#include "CanvasClockface.h"
#include "PNGRender.h"
#include <SPIFFS.h>

// static：两个主题同时编译时，同名的文件级全局会在链接期冲突
static unsigned long lastMillis = 0;

// 缓冲大小直接影响网络：本机实测
//   doc=16KB -> 空闲堆 142KB -> 网络正常（连续跑了几小时）
//   doc=48KB -> 空闲堆 108KB -> 能连上热点(DHCP)，但 TCP 握手都完不成
// 原因是 48KB(JSON) + 48KB(PNG) 两个大块把堆切碎，lwIP 拿不到连续缓冲。
// 所以先回到 16KB 保网络；大主题（mario 34KB 等）要靠压缩图片解决，不能靠加大缓冲。
static DynamicJsonDocument doc(16384);

CanvasClockface::CanvasClockface(Adafruit_GFX *display)
{
  _display = display;
  Locator::provide(display);

  // 关键：在 WiFi 启动之前先把 48KB 的 PNG 缓冲抢下来。
  // setup() 里才分配的话，WiFi 栈已经把堆切碎，new PNG() 会失败（图片/精灵全废）。
  reservePngBuffers();
}

void CanvasClockface::setup(CWDateTime *dateTime)
{
  this->_dateTime = dateTime;
  drawSplashScreen(0xFFE0, "Downloading");

  if (deserializeDefinition()) {
    clockfaceSetup();
  }
}

void CanvasClockface::drawSplashScreen(uint16_t color, const char *msg) {
  
  Locator::getDisplay()->fillRect(0, 0, 64, 64, 0);
  Locator::getDisplay()->drawBitmap(19, 18, CW_ICON_CANVAS, 27, 32, color);
  
  StatusController::getInstance()->printCenter("- Canvas -", 7);
  StatusController::getInstance()->printCenter(msg, 61);
}

void CanvasClockface::update()
{
  // Render animation
  clockfaceLoop();

  // Update Date/Time - Using a fixed interval (1000 milliseconds)
  if (millis() - lastMillis >= 1000)
  {
    refreshDateTime();
    lastMillis = millis();
  }
}

void CanvasClockface::setFont(const char *fontName)
{

  if (strcmp(fontName, "picopixel") == 0)
  {
    Locator::getDisplay()->setFont(&Picopixel);
  }
  else if (strcmp(fontName, "square") == 0)
  {
    Locator::getDisplay()->setFont(&atariFont);
  }
  else if (strcmp(fontName, "big") == 0)
  {
    Locator::getDisplay()->setFont(&hour8pt7b);
  }
  else if (strcmp(fontName, "medium") == 0)
  {
    Locator::getDisplay()->setFont(&minute7pt7b);
  }
  else
  {
    Locator::getDisplay()->setFont();
  }
}

void CanvasClockface::renderText(String text, JsonVariantConst value)
{
  int16_t x1, y1;
  uint16_t w, h;

  setFont(value["font"].as<const char *>());

  Locator::getDisplay()->getTextBounds(text, 0, 0, &x1, &y1, &w, &h);

  // BG Color
  Locator::getDisplay()->fillRect(
      value["x"].as<const uint16_t>() + x1,
      value["y"].as<const uint16_t>() + y1,
      w,
      h,
      value["bgColor"].as<const uint16_t>());

  Locator::getDisplay()->setTextColor(value["fgColor"].as<const uint16_t>());
  Locator::getDisplay()->setCursor(value["x"].as<const uint16_t>(), value["y"].as<const uint16_t>());
  Locator::getDisplay()->print(text);
}

void CanvasClockface::refreshDateTime()
{

  JsonArrayConst elements = doc["setup"].as<JsonArrayConst>();
  for (JsonVariantConst value : elements)
  {
    const char *type = value["type"].as<const char *>();
    if (type == nullptr)
      continue;

    if (strcmp(type, "datetime") == 0)
    {
      renderText(_dateTime->getFormattedTime(value["content"].as<const char *>()), value);
    }
  }
}

void CanvasClockface::clockfaceSetup()
{

  // Clear screen
  Locator::getDisplay()->fillRect(0, 0, 64, 64, doc["bgColor"].as<const uint16_t>());

  delay = doc["delay"].as<const uint16_t>();

  // Draw static elements
  renderElements(doc["setup"].as<JsonArrayConst>());

  // Draw Date/Time
  refreshDateTime();

  // Create sprites
  createSprites();
}

void CanvasClockface::createSprites()
{
  JsonArrayConst elements = doc["loop"].as<JsonArrayConst>();
  uint8_t width = 0;
  uint8_t height = 0;

  for (JsonVariantConst value : elements)
  {
    const char *type = value["type"].as<const char *>();

    if (strcmp(type, "sprite") == 0)
    {
      uint8_t ref = value["sprite"].as<const uint8_t>();

      std::shared_ptr<CustomSprite> s = std::make_shared<CustomSprite>(value["x"].as<const int8_t>(), value["y"].as<const int8_t>());

      getImageDimensions(doc["sprites"][ref][0]["image"].as<const char *>(), width, height);

      s.get()->_spriteReference = value["sprite"].as<const uint8_t>();
      s.get()->_totalFrames = doc["sprites"][ref].size();
      s.get()->setDimensions(width, height);
      sprites.push_back(s);
    }
  }
}

void CanvasClockface::handleSpriteAnimation(std::shared_ptr<CustomSprite>& sprite) {
    // 一次性诊断：把精灵的实际参数打出来，出问题时不用再靠猜
    static bool spriteInfoLogged = false;
    if (!spriteInfoLogged) {
        spriteInfoLogged = true;
        JsonArrayConst frames = doc["sprites"][sprite->_spriteReference].as<JsonArrayConst>();
        Serial.printf("[Canvas] 精灵 ref=%u 帧数=%u 尺寸=%ux%u 位置=(%d,%d) frameDelay=%u loopDelay=%u\n",
                      (unsigned)sprite->_spriteReference,
                      frames.isNull() ? 0 : (unsigned)frames.size(),
                      sprite->getWidth(), sprite->getHeight(),
                      sprite->getX(), sprite->getY(),
                      (unsigned)(doc["loop"][sprite->_spriteReference]["frameDelay"].as<uint16_t>() ?: delay),
                      (unsigned)(doc["loop"][sprite->_spriteReference]["loopDelay"].as<uint32_t>() ?: delay));
    }

    JsonArrayConst frames = doc["sprites"][sprite->_spriteReference].as<JsonArrayConst>();
    if (frames.isNull() || frames.size() == 0)
        return;   // sprite 引用越界或空帧组

    const uint16_t totalFrames = frames.size();
    sprite->_totalFrames = totalFrames > 255 ? 255 : totalFrames;

    // loopDelay 未设置或为 0 时退回用 delay：保证「播完一定会重播」。
    // （曾经试过让 0 表示"立即重播"，但那样 _currentFrameCount 永不归零，
    //   动画播一遍就永久停住 —— 比停顿更糟，所以退回这个行为。）
    uint32_t loopDelay = doc["loop"][sprite->_spriteReference]["loopDelay"].as<uint32_t>() ?: delay;
    uint16_t frameDelay = doc["loop"][sprite->_spriteReference]["frameDelay"].as<uint16_t>() ?: delay;
    if (frameDelay == 0) frameDelay = 50;   // 0 会让动画每次循环都触发，白烧 CPU

    if (millis() - sprite->_lastMillisSpriteFrames >= frameDelay && sprite->_currentFrameCount < totalFrames) {
        sprite->incFrame();

        // 帧索引必须夹在有效范围内，否则 frames[idx] 返回 null，下面 strlen 会崩
        if (sprite->_currentFrame >= totalFrames)
            sprite->_currentFrame = 0;

        // handle sprite movement
        handleSpriteMovement(sprite);

        // Render the frame of the sprite
        const char *img = frames[sprite->_currentFrame]["image"].as<const char *>();
        if (img != nullptr)
            renderImage(img, sprite->getX(), sprite->getY());

        sprite->_currentFrameCount += 1;
        sprite->_lastMillisSpriteFrames = millis();
    }

    // 播完一轮后停顿 loopDelay 毫秒再重播。
    //
    // 原实现还多一层 `(currentSecond * 1000) % loopDelay == 0`，
    // 只有当 loopDelay 能整除 1000 时才成立 —— 官方主题多用 1000/2000 因此没暴露，
    // 一旦设成 90 就变成「每 9 秒才重播一次」，表现为动画播 1 秒停 8 秒的卡顿。
    // 已删除：停顿就是纯时长，跟当前是第几秒无关。
    if (millis() - sprite->_lastResetTime >= loopDelay) {
        sprite->_currentFrameCount = 0;
        sprite->_lastResetTime = millis();
    }
}

void CanvasClockface::handleSpriteMovement(std::shared_ptr<CustomSprite>& sprite) {
    unsigned long moveStartTime = doc["loop"][sprite->_spriteReference]["moveStartTime"].as<unsigned long>() ?: 1;
    unsigned long moveDuration = doc["loop"][sprite->_spriteReference]["moveDuration"].as<unsigned long>() ?: 0;
    int8_t moveInitialX = doc["loop"][sprite->_spriteReference]["x"].as<int8_t>() ?:0;
    int8_t moveInitialY = doc["loop"][sprite->_spriteReference]["y"].as<int8_t>() ?: 0;
    int8_t moveTargetX = doc["loop"][sprite->_spriteReference]["moveTargetX"].as<int8_t>() ?: -1;
    int8_t moveTargetY = doc["loop"][sprite->_spriteReference]["moveTargetY"].as<int8_t>() ?: -1;
    bool shouldReturnToOrigin = doc["loop"][sprite->_spriteReference]["shouldReturnToOrigin"].as<bool>() ?: false;

    // Check if the sprite is moving
    if (sprite->isMoving()) {
        unsigned long currentTime = millis();
        unsigned long elapsedTime = currentTime - sprite->_moveStartTime;
        float progress = (static_cast<float>(elapsedTime) / sprite->_moveDuration);

        int8_t oldX = sprite->getX();
        int8_t oldY = sprite->getY();
        int8_t newX = sprite->lerp(sprite->_moveInitialX, sprite->_moveTargetX, progress);
        int8_t newY = sprite->lerp(sprite->_moveInitialY, sprite->_moveTargetY, progress);
        int8_t originX = min(oldX, newX);
        int8_t originY = min(oldY, newY);
        int8_t drawWidth = sprite->getWidth() + max(oldX, newX) - originX;
        int8_t drawHeight = sprite->getHeight() + max(oldY, newY) - originY;

        // Erase the previous position
        Locator::getDisplay()->fillRect(
            originX,
            originY,
            drawWidth,
            drawHeight,
            doc["bgColor"].as<const uint16_t>());

        if (progress <= 1) {
            // Update the sprite's position
            sprite->setX(newX);
            sprite->setY(newY);

        } else if (sprite->shouldReturnToOrigin()) {
            // Movement is complete
            sprite->setX(sprite->_moveTargetX);
            sprite->setY(sprite->_moveTargetY);

            if (!sprite->_isReversing) {
                sprite->reverseMoving(moveInitialX, moveInitialY);
            }
        } else {
            sprite->stopMoving();
        }
    }

    if ((moveDuration > 0 && (moveTargetX > -1 || moveTargetY > -1)) && (millis() - sprite->_lastResetMoveTime >= moveStartTime)) {
        unsigned long currentMillis = millis();
        unsigned long currentSecond = _dateTime->getSecond();

        if ((currentSecond * 1000) % moveStartTime == 0) {
            sprite->_lastResetMoveTime = currentMillis;
            sprite->startMoving(moveTargetX, moveTargetY, moveDuration, shouldReturnToOrigin);
        }
    }
}

void CanvasClockface::clockfaceLoop() {
    if (sprites.empty()) {
        return;
    }

    for (auto& sprite : sprites) {
        handleSpriteAnimation(sprite);
    }
}

void CanvasClockface::renderElements(JsonArrayConst elements)
{
  for (JsonVariantConst value : elements)
  {
    const char *type = value["type"].as<const char *>();
    if (type == nullptr)   // 主题里缺 type 字段时 strcmp(nullptr) 会崩
      continue;

    if (strcmp(type, "text") == 0)
    {
      renderText(value["content"].as<const char *>(), value);
    }
    else if (strcmp(type, "fillrect") == 0)
    {
      Locator::getDisplay()->fillRect(
          value["x"].as<const uint16_t>(),
          value["y"].as<const uint16_t>(),
          value["width"].as<const uint16_t>(),
          value["height"].as<const uint16_t>(),
          value["color"].as<const uint16_t>());
    }
    else if (strcmp(type, "rect") == 0)
    {
      Locator::getDisplay()->drawRect(
          value["x"].as<const uint16_t>(),
          value["y"].as<const uint16_t>(),
          value["width"].as<const uint16_t>(),
          value["height"].as<const uint16_t>(),
          value["color"].as<const uint16_t>());
    }
    else if (strcmp(type, "line") == 0)
    {
      Locator::getDisplay()->drawLine(
          value["x"].as<const uint16_t>(),
          value["y"].as<const uint16_t>(),
          value["x1"].as<const uint16_t>(),
          value["y1"].as<const uint16_t>(),
          value["color"].as<const uint16_t>());
    }
    else if (strcmp(type, "image") == 0)
    {
      renderImage(value["image"].as<const char *>(), value["x"].as<const uint8_t>(), value["y"].as<const uint8_t>());
    }
  }
}

bool CanvasClockface::deserializeDefinition()
{
  ClockwiseParams *params = ClockwiseParams::getInstance();

  if (params->canvasFile.isEmpty())
  {
    drawSplashScreen(0xC904, "Params werent set");
    return false;
  }

  // ---- 1) 优先用 SPIFFS 里的本地主题：断网也能用，开机秒出画面 ----
  String localPath = "/" + params->canvasFile + ".json";
  if (SPIFFS.exists(localPath))
  {
    File f = SPIFFS.open(localPath, FILE_READ);
    if (f)
    {
      // 先按文件大小拦一道：doc 只有 16KB，超过必然解析失败。
      // 必须在解析前判断 —— 否则 deserializeJson 吃满缓冲后失败，
      // 老代码会「回落到远程」，去 raw.githubusercontent.com 拉同名主题，
      // 那个 TLS 握手不受 setTimeout 控制，会把主循环整个堵死
      // （现象：设备无响应、串口一行不打印，几分钟后才超时）。
      const size_t fsize = f.size();
      if (fsize == 0 || fsize > doc.capacity())
      {
        f.close();
        Serial.printf("[Canvas] 主题 %s 有 %u 字节，超出缓冲 %u，拒绝加载\n",
                      localPath.c_str(), (unsigned)fsize, (unsigned)doc.capacity());
        Serial.println("[Canvas] 已跳过远程回落（本地有文件却解析不了时，远程只会卡死主循环）");
        drawSplashScreen(0xC904, "Theme too big");
        return false;
      }

      DeserializationError localError = deserializeJson(doc, f);
      f.close();
      if (!localError)
      {
        Serial.printf("[Canvas] 本地主题已加载 %s（无需联网）\n", localPath.c_str());
        Serial.printf("[Canvas] Building clockface '%s' by %s, version %d\n",
                      doc["name"].as<const char *>(), doc["author"].as<const char *>(),
                      doc["version"].as<const uint16_t>());
        return true;
      }

      // 本地文件存在但解析失败：直接报错，不回落远程。
      // 回落远程在这里永远是错的 —— 本地都有文件了，远程同名主题要么不存在，
      // 要么就是同一个坏文件，而请求本身会把主循环堵死。
      Serial.printf("[Canvas] 本地主题解析失败(%s)，%u 字节\n",
                    localError.c_str(), (unsigned)fsize);
      drawSplashScreen(0xC904, "Theme broken");
      return false;
    }
  }

  // ---- 2) 本地没有，走远程 ----
  if (params->canvasServer.isEmpty())
  {
    drawSplashScreen(0xC904, "No local theme");
    return false;
  }

  WiFiClientSecure client;

  String server = params->canvasServer;
  String file = String("/" + params->canvasFile + ".json");
  uint16_t port = 4443;

  if (server.startsWith("raw.")) {
    port = 443;
    file = String("/robegamesios/clock-club/main/shared" + file);
  }

  ClockwiseHttpClient::getInstance()->httpGet(&client, server.c_str(), file.c_str(), port);

  DeserializationError error = deserializeJson(doc, client);
  if (error)
  {
    drawSplashScreen(0xC904, "Error! Check logs");

    Serial.print("deserializeJson() failed: ");
    Serial.println(error.c_str());
    client.stop();
    return false;
  }

  Serial.printf("[Canvas] Building clockface '%s' by %s, version %d\n", doc["name"].as<const char *>(), doc["author"].as<const char *>(), doc["version"].as<const uint16_t>());
  client.stop();
  return true;
}

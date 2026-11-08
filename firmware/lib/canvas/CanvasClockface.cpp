
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

  // 坐标用 as<int>() 再相加：x1/y1 是字形相对基线的偏移，可能为负。
  // 旧写法 as<const uint16_t>() + x1 会把负数带进无符号运算，最后截断成 int16_t，
  // 表面上没错但边界情况会算飞。
  const int16_t px = (int16_t)(value["x"].as<int>() + x1);
  const int16_t py = (int16_t)(value["y"].as<int>() + y1);

  // 元素没写 bgColor 时退回主题背景色。
  // 旧写法 as<const uint16_t>() 对缺失的键返回 0，在非黑底主题上会擦出一块黑。
  uint16_t bg = doc["bgColor"].as<uint16_t>();
  if (!value["bgColor"].isNull())
    bg = value["bgColor"].as<uint16_t>();

  uint16_t fg = 0xFFFF;
  if (!value["fgColor"].isNull())
    fg = value["fgColor"].as<uint16_t>();

  Locator::getDisplay()->fillRect(px, py, w, h, bg);
  Locator::getDisplay()->setTextColor(fg);
  Locator::getDisplay()->setCursor(value["x"].as<int>(), value["y"].as<int>());
  Locator::getDisplay()->print(text);
}

void CanvasClockface::refreshDateTime()
{

  JsonArrayConst elements = doc["setup"].as<JsonArrayConst>();
  uint8_t slot = 0;

  for (JsonVariantConst value : elements)
  {
    const char *type = value["type"].as<const char *>();
    if (type == nullptr)
      continue;

    if (strcmp(type, "datetime") == 0)
    {
      const String text = _dateTime->getFormattedTime(value["content"].as<const char *>());

      // 先把这次「要画在哪、多大」算出来（和 renderText 用同一套算法），
      // 才能判断是不是真的需要重绘。
      setFont(value["font"].as<const char *>());
      int16_t x1, y1;
      uint16_t w, h;
      Locator::getDisplay()->getTextBounds(text, 0, 0, &x1, &y1, &w, &h);
      const int16_t px = (int16_t)(value["x"].as<int>() + x1);
      const int16_t py = (int16_t)(value["y"].as<int>() + y1);

      DateTimeSlot &c = _dtSlots[slot < DT_SLOT_MAX ? slot : DT_SLOT_MAX - 1];
      slot++;

      // 内容、位置、包围盒全都没变 → 一个像素都不写。
      //
      // 这就是「时间区域每秒闪一下」的解药：update() 每秒都会进来，
      // 旧代码在这里无条件 renderText()，等于每秒把时间区擦掉重画一次。
      // H:i 一分钟才变一次，99% 的刷新都是纯白干，还给单缓冲面板制造了撕裂。
      if (c.drawn && text == c.text && px == c.x && py == c.y &&
          w == c.w && h == c.h)
        continue;

      // 文本变短时（"10:05" → "9:05"），新包围盒盖不住旧包围盒，
      // 旧字右侧会残留。先按旧矩形擦一遍再画新的。
      uint16_t bg = doc["bgColor"].as<uint16_t>();
      if (!value["bgColor"].isNull())
        bg = value["bgColor"].as<uint16_t>();

      const bool covers =
          (px <= c.x) && (py <= c.y) &&
          ((int32_t)px + w >= (int32_t)c.x + c.w) &&
          ((int32_t)py + h >= (int32_t)c.y + c.h);
      if (c.drawn && !covers)
        Locator::getDisplay()->fillRect(c.x, c.y, c.w, c.h, bg);

      renderText(text, value);

      c.text = text;
      c.x = px;
      c.y = py;
      c.w = w;
      c.h = h;
      c.drawn = true;
    }
  }
}

void CanvasClockface::clockfaceSetup()
{

  // Clear screen
  Locator::getDisplay()->fillRect(0, 0, 64, 64, doc["bgColor"].as<const uint16_t>());

  delay = doc["delay"].as<const uint16_t>();

  // 刚刚清过屏，之前的绘制已经不存在了，缓存必须一起清。
  // 不清的话，如果上电时内容恰好等于缓存里的值，会被判定"已画过"而跳过，
  // 屏幕上就是一块空白。
  for (uint8_t i = 0; i < DT_SLOT_MAX; i++)
    _dtSlots[i].reset();

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

bool CanvasClockface::handleSpriteAnimation(std::shared_ptr<CustomSprite>& sprite) {
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
        return false;   // sprite 引用越界或空帧组

    const uint16_t totalFrames = frames.size();
    sprite->_totalFrames = totalFrames > 255 ? 255 : totalFrames;

    // loopDelay 未设置或为 0 时退回用 delay：保证「播完一定会重播」。
    // （曾经试过让 0 表示"立即重播"，但那样 _currentFrameCount 永不归零，
    //   动画播一遍就永久停住 —— 比停顿更糟，所以退回这个行为。）
    uint32_t loopDelay = doc["loop"][sprite->_spriteReference]["loopDelay"].as<uint32_t>() ?: delay;
    uint16_t frameDelay = doc["loop"][sprite->_spriteReference]["frameDelay"].as<uint16_t>() ?: delay;
    if (frameDelay == 0) frameDelay = 50;   // 0 会让动画每次循环都触发，白烧 CPU

    bool frameChanged = false;

    if (millis() - sprite->_lastMillisSpriteFrames >= frameDelay && sprite->_currentFrameCount < totalFrames) {
        sprite->incFrame();

        // 帧索引必须夹在有效范围内，否则 frames[idx] 返回 null，下面 strlen 会崩
        if (sprite->_currentFrame >= totalFrames)
            sprite->_currentFrame = 0;

        sprite->_currentFrameCount += 1;
        sprite->_lastMillisSpriteFrames = millis();
        frameChanged = true;
    }

    // loopDelay 是「帧计数重置周期」，不是「播完后再停多久」——这个区别很重要：
    //   loopDelay == frameDelay × 帧数  → 最后一帧播完正好到点，无缝循环
    //   loopDelay >  该值             → 播完后停顿 (loopDelay - 播放时长)
    //   loopDelay <  该值             → 动画播到一半被重置，帧序列被截断
    //
    // 原实现还多一层 `(currentSecond * 1000) % loopDelay == 0`，
    // 只有当 loopDelay 能整除 1000 时才成立 —— 官方主题多用 1000/2000 因此没暴露，
    // 一旦设成 90 就变成「每 9 秒才重置一次」，表现为动画播 1 秒停 8 秒。
    // 已删除：重置只看纯时长，跟当前是第几秒无关。
    if (millis() - sprite->_lastResetTime >= loopDelay) {
        sprite->_currentFrameCount = 0;
        sprite->_lastResetTime = millis();
    }

    return frameChanged;
}

bool CanvasClockface::handleSpriteMovement(std::shared_ptr<CustomSprite>& sprite) {
    unsigned long moveStartTime = doc["loop"][sprite->_spriteReference]["moveStartTime"].as<unsigned long>() ?: 1;
    unsigned long moveDuration = doc["loop"][sprite->_spriteReference]["moveDuration"].as<unsigned long>() ?: 0;
    int8_t moveInitialX = doc["loop"][sprite->_spriteReference]["x"].as<int8_t>() ?:0;
    int8_t moveInitialY = doc["loop"][sprite->_spriteReference]["y"].as<int8_t>() ?: 0;
    int8_t moveTargetX = doc["loop"][sprite->_spriteReference]["moveTargetX"].as<int8_t>() ?: -1;
    int8_t moveTargetY = doc["loop"][sprite->_spriteReference]["moveTargetY"].as<int8_t>() ?: -1;
    bool shouldReturnToOrigin = doc["loop"][sprite->_spriteReference]["shouldReturnToOrigin"].as<bool>() ?: false;

    bool moved = false;

    // Check if the sprite is moving
    if (sprite->isMoving()) {
        unsigned long currentTime = millis();
        unsigned long elapsedTime = currentTime - sprite->_moveStartTime;
        float progress = (static_cast<float>(elapsedTime) / sprite->_moveDuration);

        int8_t oldX = sprite->getX();
        int8_t oldY = sprite->getY();
        int8_t newX = sprite->lerp(sprite->_moveInitialX, sprite->_moveTargetX, progress);
        int8_t newY = sprite->lerp(sprite->_moveInitialY, sprite->_moveTargetY, progress);

        if (progress > 1.0f) {           // 到点：钉在目标位
            newX = sprite->_moveTargetX;
            newY = sprite->_moveTargetY;
        }

        if (newX != oldX || newY != oldY) {
            // 擦掉旧位置与新位置的并集（int16_t 防止 64+63=127 卡在 int8_t 上界）
            int16_t originX = min(oldX, newX);
            int16_t originY = min(oldY, newY);
            int16_t drawWidth = sprite->getWidth() + max(oldX, newX) - originX;
            int16_t drawHeight = sprite->getHeight() + max(oldY, newY) - originY;

            // Erase the previous position
            Locator::getDisplay()->fillRect(
                originX,
                originY,
                drawWidth,
                drawHeight,
                doc["bgColor"].as<const uint16_t>());

            sprite->setX(newX);
            sprite->setY(newY);
            moved = true;
        }

        // 到点后的状态切换。
        // 注意：这里必须读 sprite->shouldReturnToOrigin()（即 _shouldReturnToOrigin），
        // 不能读 JSON 里的 shouldReturnToOrigin —— reverseMoving() 会把
        // _shouldReturnToOrigin 置 false，回程走完时靠它走到 stopMoving()，
        // 否则会无限往返。
        if (progress > 1.0f) {
            if (sprite->shouldReturnToOrigin()) {
                if (!sprite->_isReversing) {
                    sprite->reverseMoving(moveInitialX, moveInitialY);  // 回程目标 = JSON 起点
                }
            } else {
                sprite->stopMoving();
            }
        }
    }

    // 触发下一次位移：只在上一次彻底结束后才计时（加 !isMoving()），
    // 否则往返动画的回程会被下一个周期打断、拽回终点。
    //
    // 原实现还有一层 `(currentSecond * 1000) % moveStartTime == 0`，
    // 它把触发时机绑在整秒上，moveStartTime=3500 会变成 7 秒才触发一次，
    // 与之前修掉的 loopDelay 取模 bug 同源。已删除：只看纯时长。
    if (!sprite->isMoving()
        && moveDuration > 0 && (moveTargetX > -1 || moveTargetY > -1)
        && (millis() - sprite->_lastResetMoveTime >= moveStartTime)) {
        sprite->_lastResetMoveTime = millis();
        sprite->startMoving(moveTargetX, moveTargetY, moveDuration, shouldReturnToOrigin);
    }

    return moved;
}

void CanvasClockface::renderSpriteFrame(std::shared_ptr<CustomSprite>& sprite) {
    JsonArrayConst frames = doc["sprites"][sprite->_spriteReference].as<JsonArrayConst>();
    if (frames.isNull() || sprite->_currentFrame >= frames.size())
        return;
    const char *img = frames[sprite->_currentFrame]["image"].as<const char *>();
    if (img != nullptr)
        renderImage(img, sprite->getX(), sprite->getY());
}

void CanvasClockface::clockfaceLoop() {
    if (sprites.empty()) {
        return;
    }

    for (auto& sprite : sprites) {
        bool frameChanged = handleSpriteAnimation(sprite);
        bool moved        = handleSpriteMovement(sprite);

        // 位移时位置变了要重画；只换帧时也要覆盖一次。
        // handleSpriteMovement 已负责擦旧位置，这里只画新位置，不会残影。
        if (moved || frameChanged) {
            renderSpriteFrame(sprite);
        }
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

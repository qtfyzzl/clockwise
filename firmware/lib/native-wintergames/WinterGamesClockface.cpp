#include "WinterGamesClockface.h"

// 颜色（RGB565，脚本精确计算）
#define C_SKY      0x0947   // 深蓝夜空 RGB(8,40,60)
#define C_SKYDEEP  0x00C5   // 更深蓝 RGB(4,24,40)
#define C_SNOWGRD  0xE75F   // 雪地浅蓝白 RGB(225,235,255)
#define C_WHITE    0xFFFF   // 纯白
#define C_PALE     0xB65C   // 淡蓝小雪花 RGB(180,200,230)
#define C_STAR     0xFF99   // 星星暖白 RGB(255,240,200)
#define C_BLUE     0x2BDB   // 蓝 RGB(40,120,220)
#define C_CYAN     0x2F1D   // 青蓝 RGB(40,225,230)
#define C_RED      0xE145   // 红 RGB(230,40,40)
#define C_SKIN     0xF6F6   // 肤色 RGB(240,220,180)

static const int8_t GROUND_Y = 61;   // 雪地只留 3 行（61~63）

WinterGamesClockface::WinterGamesClockface(Adafruit_GFX *display)
{
  _display = display;
  Locator::provide(display);
}

void WinterGamesClockface::resetSnowflake(Snowflake &s)
{
  s.x = random(0, W);
  s.y = -random(0, H / 2);
  s.fx = (float)s.x;
  s.speed = random(8, 20);              // 较快，营造密集飘落感
  s.phase = (float)random(0, 628) / 100.0f;
}

void WinterGamesClockface::setup(CWDateTime *dateTime)
{
  _dateTime = dateTime;

  for (uint8_t i = 0; i < SNOW_COUNT; i++)
    resetSnowflake(_snow[i]);

  // 4 个 8×8 大雪花，分布在滑冰人物周边，上下漂浮
  _bigsnow[0].x = 12; _bigsnow[0].baseY = 20; _bigsnow[0].amp = 6; _bigsnow[0].speed = 1.0f; _bigsnow[0].phase = 0;
  _bigsnow[1].x = 50; _bigsnow[1].baseY = 16; _bigsnow[1].amp = 7; _bigsnow[1].speed = 0.8f; _bigsnow[1].phase = 1.5f;
  _bigsnow[2].x = 8;  _bigsnow[2].baseY = 42; _bigsnow[2].amp = 5; _bigsnow[2].speed = 1.2f; _bigsnow[2].phase = 3.0f;
  _bigsnow[3].x = 54; _bigsnow[3].baseY = 40; _bigsnow[3].amp = 6; _bigsnow[3].speed = 0.9f; _bigsnow[3].phase = 4.5f;
  for (uint8_t i = 0; i < BIGSNOW_COUNT; i++)
    _bigsnow[i].y = (int8_t)_bigsnow[i].baseY;

  _lastAnimMs = millis();

  drawStatic();
}

void WinterGamesClockface::putPx(int8_t x, int8_t y, uint16_t c)
{
  if (x < 0 || x >= W || y < 0 || y >= H) return;
  _bg[y * W + x] = c;
  Locator::getDisplay()->drawPixel(x, y, c);
}

void WinterGamesClockface::erasePx(int8_t x, int8_t y)
{
  if (x < 0 || x >= W || y < 0 || y >= H) return;
  Locator::getDisplay()->drawPixel(x, y, _bg[y * W + x]);
}

void WinterGamesClockface::drawSky()
{
  for (int8_t y = 0; y < H; y++)
    for (int8_t x = 0; x < W; x++)
      putPx(x, y, (y < 10) ? C_SKYDEEP : C_SKY);
}

void WinterGamesClockface::drawStars()
{
  static const int8_t star_xy[][2] = {
    {6,10},{20,6},{34,12},{50,8},{60,12},{14,22},{44,18},{56,24},{28,4},{58,28}
  };
  for (uint8_t i = 0; i < 10; i++)
    putPx(star_xy[i][0], star_xy[i][1], C_STAR);
}

// 中央滑冰运动人物：清晰的轮廓（头+身体+伸展臂+滑行腿）
// 'b'=蓝衣 's'=肤色头/手 'r'=红冰鞋 'w'=白 '.'=透明
void WinterGamesClockface::drawSkater()
{
  // 侧身滑行：身体前倾，一臂前伸一臂后摆，一腿蹬冰一腿滑行
  static const char* SKATER[24] = {
    "..........ssss.......",
    "..........ssss.......",
    "..........ssss.......",
    ".........bbbbbb......",
    "........bbbbbbbb.....",
    "........bbbbbbbbb....",
    "......bbbbbbbbbbb....",
    ".....bbbbbbbbbbbb....",
    ".....bbbbbbbbbbbb....",
    "......bbbbbbbbb......",
    "......bbbbbbbbb......",
    ".....bbbbbbbbbbbb....",
    "....bbbbbbbbbbbbb....",
    "...bbbbbbbbbbbbbbb...",
    "...bbbbbbbbbbbbbbb...",
    "....bbbbbbbbbbbb.....",
    "....bbbbbbbbbbbb.....",
    ".....bbbbbbbbbb......",
    ".....bbbb..bbbb......",
    ".....bbbb..bbbb......",
    ".....rrrr..rrrr......",
    "......rr....rr.......",
    "......rr....rr.......",
    "......rr....rr.......",
  };

  int8_t ox = (W - 40) / 2;
  int8_t oy = (GROUND_Y - 48) / 2;

  for (int8_t r = 0; r < 24; r++)
  {
    for (int8_t c = 0; c < 20; c++)
    {
      char ch = SKATER[r][c];
      uint16_t color;
      switch (ch)
      {
        case 'b': color = C_BLUE; break;
        case 's': color = C_SKIN; break;
        case 'r': color = C_RED; break;
        case 'w': color = C_WHITE; break;
        default: continue;
      }
      for (int8_t dy = 0; dy < 2; dy++)
        for (int8_t dx = 0; dx < 2; dx++)
          putPx(ox + c*2 + dx, oy + r*2 + dy, color);
    }
  }
}

void WinterGamesClockface::drawGround()
{
  // 雪地只留 3 行
  for (int8_t y = GROUND_Y; y < H; y++)
    for (int8_t x = 0; x < W; x++)
      putPx(x, y, C_SNOWGRD);
  for (int8_t x = 0; x < W; x++)
    putPx(x, GROUND_Y, C_WHITE);
}

void WinterGamesClockface::drawStatic()
{
  drawSky();
  drawStars();
  drawSkater();
  drawGround();
}

void WinterGamesClockface::drawSnow()
{
  unsigned long now = millis();
  float dt = (float)(now - _lastAnimMs) / 1000.0f;
  if (dt > 0.1f) dt = 0.1f;

  for (uint8_t i = 0; i < SNOW_COUNT; i++)
  {
    Snowflake &s = _snow[i];

    erasePx(s.x, s.y);

    s.fx += sinf(s.phase) * 4.0f * dt;
    s.y  += (int8_t)(s.speed * dt);
    s.phase += 1.8f * dt;

    s.x = (int8_t)s.fx;
    if (s.x < 0) { s.x = 0; s.fx = 0; }
    if (s.x > W - 1) { s.x = W - 1; s.fx = s.x; }
    if (s.y >= GROUND_Y) resetSnowflake(s);

    Locator::getDisplay()->drawPixel(s.x, s.y, C_PALE);
  }
}

void WinterGamesClockface::drawBigSnow()
{
  unsigned long now = millis();
  float t = (float)now / 1000.0f;

  for (uint8_t i = 0; i < BIGSNOW_COUNT; i++)
  {
    BigSnow &b = _bigsnow[i];

    // 擦旧（8×8 六瓣雪花：中心 + 三主轴 + 尖端）
    // 用简单十字 + 斜线造型，覆盖约 7×7 区域
    for (int8_t dy = -3; dy <= 3; dy++)
      for (int8_t dx = -3; dx <= 3; dx++)
        if (abs(dx) + abs(dy) <= 3 || dx == 0 || dy == 0)
          erasePx(b.x + dx, b.y + dy);

    // 上下漂浮
    b.y = (int8_t)(b.baseY + sinf(t * b.speed + b.phase) * b.amp);

    // 画新：六瓣雪花（横竖 + 两斜线主轴）
    for (int8_t d = -3; d <= 3; d++)
    {
      Locator::getDisplay()->drawPixel(b.x + d, b.y, C_WHITE);          // 横
      Locator::getDisplay()->drawPixel(b.x, b.y + d, C_WHITE);          // 竖
      Locator::getDisplay()->drawPixel(b.x + d, b.y + d, C_CYAN);       // 斜1
      Locator::getDisplay()->drawPixel(b.x + d, b.y - d, C_CYAN);       // 斜2
    }
    Locator::getDisplay()->drawPixel(b.x, b.y, C_WHITE);   // 中心
  }
}

void WinterGamesClockface::update()
{
  unsigned long now = millis();

  drawSnow();
  drawBigSnow();

  _lastAnimMs = now;
}

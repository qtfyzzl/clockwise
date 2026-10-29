#include "Clockface.h"

// ---------------- 7 段编码 ----------------
// bit0=A(上) bit1=B(右上) bit2=C(右下) bit3=D(下) bit4=E(左下) bit5=F(左上) bit6=G(中)
static const uint8_t SEG_A = 0x01, SEG_B = 0x02, SEG_C = 0x04, SEG_D = 0x08,
                     SEG_E = 0x10, SEG_F = 0x20, SEG_G = 0x40;

static const uint8_t DIGIT_SEG[10] = {
    0x3F, // 0  A B C D E F
    0x06, // 1  B C
    0x5B, // 2  A B D E G
    0x4F, // 3  A B C D G
    0x66, // 4  B C F G
    0x6D, // 5  A C D F G
    0x7D, // 6  A C D E F G
    0x07, // 7  A B C
    0x7F, // 8  全亮
    0x6F, // 9  A B C D F G
};

// 配色（RGB565）
static const uint16_t COLOR_TIME = 0xFFFF; // 纯白
static const uint16_t COLOR_DATE = 0x0659; // 青色 #00C8C8

Clockface::Clockface(Adafruit_GFX *display)
{
  _display = display;
  // main.cpp 传进来的就是 MatrixPanel_I2S_DMA*，这里强转以调用 setBrightness8
  _panel = (MatrixPanel_I2S_DMA *)display;
  Locator::provide(display);
}

void Clockface::setup(CWDateTime *dateTime)
{
  _dateTime = dateTime;

  // 告诉主循环：亮度由本主题自己管
  g_themeControlsBrightness = true;

  applyLightPolicy();
  _lastMinute = -1; // 强制首次绘制
  render();
}

void Clockface::update()
{
  // 每 2 秒评估一次环境光
  if (millis() - _lastLightCheck > 2000)
  {
    _lastLightCheck = millis();
    applyLightPolicy();
  }

  // 分钟变化（或模式切换时 _lastMinute 被置 -1）才重绘，避免无谓刷屏
  const int minute = _dateTime->getMinute();
  if (minute != _lastMinute)
  {
    _lastMinute = minute;
    render();
  }
}

// ---------------- 光照策略 ----------------
// 三档，阈值直接复用设置页里已有的「自动亮度 最小值/最大值」：
//   ADC >= 最大值   -> 亮度 100%，正常界面
//   最小值..最大值  -> 亮度 50%，  正常界面
//   ADC <= 最小值   -> 亮度 25%，  大数字模式
// 最大值 <= 最小值 视为未配置，不做自适应，固定为设定亮度。
void Clockface::applyLightPolicy()
{
  ClockwiseParams *params = ClockwiseParams::getInstance();

  const int16_t adc = (int16_t)analogRead(params->ldrPin);
  const int16_t lo = (int16_t)params->autoBrightMin;
  const int16_t hi = (int16_t)params->autoBrightMax;
  const uint8_t peak = params->displayBright;

  bool big;
  uint8_t bright;

  if (hi <= lo) // 未启用自适应
  {
    bright = peak;
    big = false;
  }
  else if (adc >= hi)
  {
    bright = peak;
    big = false;
  }
  else if (adc > lo)
  {
    bright = (uint8_t)(peak / 2); // 房间变暗 -> 原来的一半
    big = false;
  }
  else
  {
    bright = (uint8_t)(peak / 4); // 更暗 -> 大数字模式
    big = true;
  }

  // 保底亮度：低于 4 基本看不见，等于坏了
  const uint8_t floorBright = big ? 8 : 4;
  if (bright < floorBright)
    bright = floorBright;

  if (bright != _lastBright)
  {
    _panel->setBrightness8(bright);
    _lastBright = bright;
  }

  if (big != _bigMode)
  {
    _bigMode = big;
    _lastMinute = -1; // 布局变了，强制重绘
  }
}

// ---------------- 绘制 ----------------
void Clockface::drawDigit(int x, int y, int w, int h, int t, uint8_t digit, uint16_t color)
{
  const uint8_t mask = DIGIT_SEG[digit % 10];
  const int halfGap = (h - t) / 2; // 中间横段的位置
  const int vertLen = (h - t) / 2 - t;

  if (mask & SEG_A)
    _display->fillRect(x + t, y, w - 2 * t, t, color);
  if (mask & SEG_G)
    _display->fillRect(x + t, y + halfGap, w - 2 * t, t, color);
  if (mask & SEG_D)
    _display->fillRect(x + t, y + h - t, w - 2 * t, t, color);

  if (mask & SEG_F)
    _display->fillRect(x, y + t, t, vertLen, color);
  if (mask & SEG_B)
    _display->fillRect(x + w - t, y + t, t, vertLen, color);
  if (mask & SEG_E)
    _display->fillRect(x, y + (h + t) / 2, t, vertLen, color);
  if (mask & SEG_C)
    _display->fillRect(x + w - t, y + (h + t) / 2, t, vertLen, color);
}

void Clockface::drawTime(int x, int y, int w, int h, int t, int gap, int colonW, uint16_t color)
{
  int hour = _dateTime->getHour();
  int minute = _dateTime->getMinute();

  drawDigit(x, y, w, h, t, hour / 10, color);
  drawDigit(x + w + gap, y, w, h, t, hour % 10, color);

  // 冒号
  const int cx = x + 2 * (w + gap);
  const int dotW = 2;
  _display->fillRect(cx + (colonW - dotW) / 2, y + h / 3, dotW, dotW, color);
  _display->fillRect(cx + (colonW - dotW) / 2, y + 2 * h / 3 - dotW, dotW, dotW, color);

  drawDigit(cx + colonW + gap, y, w, h, t, minute / 10, color);
  drawDigit(cx + colonW + gap + w + gap, y, w, h, t, minute % 10, color);
}

void Clockface::render()
{
  _display->fillRect(0, 0, 64, 64, 0);

  if (_bigMode)
  {
    // 大数字模式：时间占满屏幕，不显示其它元素
    // 总宽 = 4w + 4gap + colonW = 4*12 + 4*2 + 4 = 60 -> x=2，左右各留 2px
    // 高 32 -> 垂直居中 y=(64-32)/2=16
    drawTime(2, 16, 12, 32, 3, 2, 4, COLOR_TIME);
  }
  else
  {
    // 正常模式：上方时间，下方日期
    // 总宽 = 4*10 + 4*3 + 4 = 56 -> x=(64-56)/2=4 居中
    drawTime(4, 15, 10, 20, 2, 3, 4, COLOR_TIME);

    String date = _dateTime->getFormattedTime("m-d");
    _display->setFont(&Picopixel);
    _display->setTextColor(COLOR_DATE);

    int16_t x1, y1;
    uint16_t tw, th;
    _display->getTextBounds(date, 0, 0, &x1, &y1, &tw, &th);
    _display->setCursor((64 - tw) / 2 - x1, 44);
    _display->print(date);

    _display->setFont(); // 还原默认字体
  }
}

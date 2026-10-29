#include "OfflineClock.h"

#include <time.h>
#include <picopixel.h>

namespace
{
  // 7 段编码：bit0=上, bit1=右上, bit2=右下, bit3=下, bit4=左下, bit5=左上, bit6=中
  const uint8_t SEGMENTS[10] = {0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F};
  const uint8_t SEG_MINUS = 0x40;   // 只亮中间一横，表示"这个位没有数字"

  // 几何：4 位数字 + 冒号，共 4*12 + 4*2 + 4 = 60px，居中后左边距 2
  const int DIGIT_W = 12;
  const int DIGIT_H = 32;
  const int STROKE = 3;
  const int GAP = 2;
  const int COLON_W = 4;
  const int TOP_Y = 14;
  const int LEFT_X = 2;
  const uint16_t COLOR_ON = 0xFFFF;

  void drawDigit(MatrixPanel_I2S_DMA *disp, int x, int y, int8_t digit)
  {
    const int w = DIGIT_W;
    const int h = DIGIT_H;
    const int t = STROKE;
    const int half = (h - t) / 2;
    const int vert = half - t;
    const uint8_t m = (digit < 0) ? SEG_MINUS : SEGMENTS[digit % 10];

    if (m & 0x01) disp->fillRect(x + t, y, w - 2 * t, t, COLOR_ON);                 // 上
    if (m & 0x40) disp->fillRect(x + t, y + half, w - 2 * t, t, COLOR_ON);           // 中
    if (m & 0x08) disp->fillRect(x + t, y + h - t, w - 2 * t, t, COLOR_ON);          // 下
    if (m & 0x20) disp->fillRect(x, y + t, t, vert, COLOR_ON);                       // 左上
    if (m & 0x02) disp->fillRect(x + w - t, y + t, t, vert, COLOR_ON);               // 右上
    if (m & 0x10) disp->fillRect(x, y + (h + t) / 2, t, vert, COLOR_ON);             // 左下
    if (m & 0x04) disp->fillRect(x + w - t, y + (h + t) / 2, t, vert, COLOR_ON);     // 右下
  }

  // 在 y 位置居中打印一行 Picopixel 小字
  void drawCentered(MatrixPanel_I2S_DMA *disp, const char *msg, int y, uint16_t color)
  {
    int16_t x1, y1;
    uint16_t w, h;
    disp->setFont(&Picopixel);
    disp->setTextColor(color);
    disp->getTextBounds(msg, 0, 0, &x1, &y1, &w, &h);
    disp->setCursor((64 - w) / 2 - x1, y);
    disp->print(msg);
    disp->setFont();
  }
}

namespace offline_clock
{
  void draw(MatrixPanel_I2S_DMA *display)
  {
    if (!display)
      return;

    display->fillRect(0, 0, 64, 64, 0);

    // 时间是否可信：NTP 同步过才会有 2023 年以后的时间
    const bool timeValid = (time(nullptr) > 1700000000L);
    int8_t h1 = -1, h2 = -1, m1 = -1, m2 = -1;

    if (timeValid)
    {
      // 用 localtime_r 而不是 cwDateTime：离线时 cwDateTime.begin() 可能还没跑过
      const time_t now = time(nullptr);
      struct tm lt;
      localtime_r(&now, &lt);
      h1 = lt.tm_hour / 10;
      h2 = lt.tm_hour % 10;
      m1 = lt.tm_min / 10;
      m2 = lt.tm_min % 10;
    }

    drawDigit(display, LEFT_X, TOP_Y, h1);
    drawDigit(display, LEFT_X + DIGIT_W + GAP, TOP_Y, h2);

    const int colonX = LEFT_X + 2 * (DIGIT_W + GAP);
    display->fillRect(colonX + 1, TOP_Y + DIGIT_H / 3, 2, 2, COLOR_ON);
    display->fillRect(colonX + 1, TOP_Y + 2 * DIGIT_H / 3 - 2, 2, 2, COLOR_ON);

    drawDigit(display, colonX + COLON_W + GAP, TOP_Y, m1);
    drawDigit(display, colonX + COLON_W + GAP + DIGIT_W + GAP, TOP_Y, m2);

    drawCentered(display, timeValid ? "no wifi" : "no wifi / no time", 52, 0xF800);
  }
}

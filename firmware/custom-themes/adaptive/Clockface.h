#pragma once

#include <Arduino.h>

#include <Adafruit_GFX.h>
#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>
#include <Locator.h>

// Commons
#include "IClockface.h"
#include "CWDateTime.h"
#include "CWPreferences.h"
#include "picopixel.h"

#define CLOCKFACE_NAME "adaptive"

// 主循环里的自动亮度是否由主题接管。
// 定义在 main.cpp，主题在 setup() 里置 true，避免两处同时写亮度寄存器互相打架。
extern bool g_themeControlsBrightness;

class Clockface : public IClockface
{
public:
  Clockface(Adafruit_GFX *display);
  void setup(CWDateTime *dateTime);
  void update();

private:
  Adafruit_GFX *_display;
  MatrixPanel_I2S_DMA *_panel;
  CWDateTime *_dateTime;

  bool _bigMode = false;        // true = 大数字模式（只留时间）
  int _lastMinute = -1;         // -1 表示需要强制重绘
  uint8_t _lastBright = 255;
  unsigned long _lastLightCheck = 0;

  void applyLightPolicy();
  void render();

  // 7 段数码管绘制
  void drawTime(int x, int y, int w, int h, int t, int gap, int colonW, uint16_t color);
  void drawDigit(int x, int y, int w, int h, int t, uint8_t digit, uint16_t color);
};

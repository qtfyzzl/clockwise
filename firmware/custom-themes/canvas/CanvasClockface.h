#pragma once

#include <Arduino.h>

#include <Adafruit_GFX.h>
#include <Locator.h>
#include <ArduinoJson.h>
#include <vector>
#include <CWPreferences.h>
#include <StatusController.h>

// Commons
#include "IClockface.h"
#include "Icons.h"
#include "picopixel.h"
#include "fonts/atari.h"
#include "fonts/hour8pt7b.h"
#include "fonts/minute7pt7b.h"
#include "CustomSprite.h"
#include "CWHttpClient.h"

#define CLOCKFACE_NAME "cw-cf-0x07"

const uint8_t CW_ICON_CANVAS[] PROGMEM = { 
	0x00, 0x0e, 0x00, 0x00, 0x00, 0x1f, 0x00, 0x00, 0x00, 0x1f, 0x00, 0x00, 0x00, 0x1f, 0x00, 0x00, 
	0x00, 0x3f, 0x80, 0x00, 0x00, 0x40, 0x40, 0x00, 0x1f, 0xc0, 0x7f, 0x00, 0x20, 0x3f, 0x80, 0x80, 
	0x20, 0x00, 0x00, 0x80, 0x20, 0x00, 0x00, 0x80, 0x20, 0x00, 0x00, 0x80, 0x20, 0x00, 0x00, 0x80, 
	0x20, 0x00, 0x00, 0x80, 0x20, 0x00, 0x00, 0x80, 0x20, 0x00, 0x00, 0x80, 0x20, 0x00, 0x00, 0x80, 
	0x20, 0x00, 0x00, 0x80, 0x20, 0x00, 0x00, 0x80, 0x20, 0x00, 0x00, 0x80, 0x20, 0x00, 0x00, 0x80, 
	0x20, 0x00, 0x00, 0x80, 0x7f, 0xff, 0xff, 0xc0, 0x80, 0x00, 0x00, 0x20, 0x7f, 0xff, 0xff, 0xc0, 
	0x0e, 0x1f, 0x0e, 0x00, 0x0e, 0x1f, 0x0e, 0x00, 0x1f, 0xff, 0xff, 0x00, 0x1e, 0x1f, 0x0f, 0x00, 
	0x3f, 0xff, 0xff, 0x80, 0x3c, 0x1f, 0x07, 0x80, 0x3c, 0x1f, 0x07, 0x80, 0x18, 0x0e, 0x03, 0x00
};

class CanvasClockface : public IClockface
{
private:
  Adafruit_GFX *_display;
  CWDateTime *_dateTime;
  uint16_t delay;

  void setFont(const char *fontName);
  bool deserializeDefinition();
  void clockfaceSetup();
  void clockfaceLoop();
  void renderElements(JsonArrayConst elements);
  void renderText(String text, JsonVariantConst value);
  void createSprites();
  void refreshDateTime();
  void drawSplashScreen(uint16_t color, const char *msg);
  // 位移与帧推进已解耦（见 固件待修-位移与刷新.md）：
  //   handleSpriteAnimation 只推帧索引，handleSpriteMovement 每轮主循环都跑，
  //   两者都返回「是否有变化」，由 clockfaceLoop 决定是否重绘。
  bool handleSpriteAnimation(std::shared_ptr<CustomSprite> &sprite);
  bool handleSpriteMovement(std::shared_ptr<CustomSprite> &sprite);
  void renderSpriteFrame(std::shared_ptr<CustomSprite> &sprite);

  // 时间元素的重绘缓存。
  //
  // 旧实现里 update() 每秒无条件调 refreshDateTime()，而 renderText() 是
  // 「fillRect 擦背景色 → print 重新画字」。单缓冲面板上，擦掉和画上之间那一瞬
  // 会被 DMA 扫描读到，表现为时间区域每秒闪一下；即使 H:i 一分钟才变一次。
  //
  // 这里缓存上一次真正画出去的内容、位置和包围盒：全都没变就一个像素都不写。
  struct DateTimeSlot
  {
    String text;
    int16_t x = 0;
    int16_t y = 0;
    uint16_t w = 0;
    uint16_t h = 0;
    bool drawn = false;
    void reset()
    {
      text = "";
      x = y = 0;
      w = h = 0;
      drawn = false;
    }
  };
  static const uint8_t DT_SLOT_MAX = 8;
  DateTimeSlot _dtSlots[DT_SLOT_MAX];

  std::vector<std::shared_ptr<CustomSprite>> sprites;

public:
  CanvasClockface(Adafruit_GFX *display);
  void setup(CWDateTime *dateTime);
  void update();
};

#pragma once

#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Locator.h>

#include <IClockface.h>
#include <CWDateTime.h>

// 长春大冬会主题 —— 原生模式 v4
//
// 架构：
//   · 静态元素（夜空、滑冰人物、雪地3行、星星）只在 setup() 画一次
//   · 背景快照数组：动态粒子擦除时恢复原色，不破坏静态元素
//   · 8×8 大雪花：3~4 个，在滑冰人物周边上下漂浮
//   · 小雪花粒子：密集，从上到下铺满上半空间
//   · 中央：一个大的滑冰运动人物（大冬会主题）

class WinterGamesClockface : public IClockface
{
private:
    Adafruit_GFX *_display;
    CWDateTime *_dateTime;

    static const int8_t W = 64, H = 64;
    uint16_t _bg[64 * 64];      // 背景快照

    // 8×8 大雪花（上下漂浮）
    struct BigSnow
    {
        int8_t x;
        int8_t y;
        float baseY;       // 漂浮中心
        float phase;
        float amp;
        float speed;
    };
    static const uint8_t BIGSNOW_COUNT = 4;
    BigSnow _bigsnow[BIGSNOW_COUNT];

    // 小雪花粒子（密集飘落，铺满上半空间）
    struct Snowflake
    {
        int8_t x;
        int8_t y;
        float fx;
        float speed;
        float phase;
    };
    static const uint8_t SNOW_COUNT = 24;
    Snowflake _snow[SNOW_COUNT];

    unsigned long _lastAnimMs = 0;

    void resetSnowflake(Snowflake &s);

    // 静态
    void drawStatic();
    void drawSky();
    void drawSkater();      // 中央滑冰人物
    void drawStars();
    void drawGround();

    // 动态
    void drawSnow();        // 小粒子
    void drawBigSnow();     // 8×8 大雪花上下漂浮
    void putPx(int8_t x, int8_t y, uint16_t c);
    void erasePx(int8_t x, int8_t y);

public:
    WinterGamesClockface(Adafruit_GFX *display);
    void setup(CWDateTime *dateTime);
    void update();
};

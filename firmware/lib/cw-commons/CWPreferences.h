#pragma once

#include <Preferences.h>

#ifndef CW_PREF_DB_NAME
    #define CW_PREF_DB_NAME "clockwise"
#endif

// 手动亮度的安全上限。
// 面板库注释提示 64 宽面板在 >239 时开始鬼影，但更早的约束是电源：
// 5V 全亮度点阵瞬间电流可超过 3A 电源能力，电压跌落触发 ESP32 掉电重启
// （表现就是「调高亮度死机」，实测 200 附近就中招）。所以这里取 180，
// 给不同批次的电源留余量。自动亮度同样以它封顶。
#ifndef DISPLAY_BRIGHT_MAX
    #define DISPLAY_BRIGHT_MAX 180
#endif


struct ClockwiseParams
{
    Preferences preferences;

    const char* const PREF_SWAP_BLUE_GREEN = "swapBlueGreen";
    const char* const PREF_SWAP_BLUE_RED = "swapBlueRed";
    const char* const PREF_USE_24H_FORMAT = "use24hFormat";
    const char* const PREF_DISPLAY_BRIGHT = "displayBright";
    const char* const PREF_DISPLAY_ABC_MIN = "autoBrightMin";
    const char* const PREF_DISPLAY_ABC_MAX = "autoBrightMax";
    const char* const PREF_LDR_PIN = "ldrPin";
    const char* const PREF_TIME_ZONE = "timeZone";
    const char* const PREF_WIFI_SSID = "wifiSsid";
    const char* const PREF_WIFI_PASSWORD = "wifiPwd";
    const char* const PREF_NTP_SERVER = "ntpServer";
    const char* const PREF_CANVAS_FILE = "canvasFile";
    const char* const PREF_CLOCKFACE_ENGINE = "clockfaceEngine";
    const char* const PREF_CANVAS_SERVER = "canvasServer";
    const char* const PREF_AUTO_ROTATE = "autoRotate";
    const char* const PREF_LAST_EPOCH = "lastEpoch";
    const char* const PREF_MANUAL_POSIX = "manualPosix";
    const char* const PREF_CACHED_POSIX = "cachedPosix";
    const char* const PREF_CACHED_TZ = "cachedTz";
    const char* const PREF_DISPLAY_ROTATION = "displayRotation";
    const char* const PREF_DRIVER = "driver";
    const char* const PREF_I2CSPEED = "i2cSpeed";
    const char* const PREF_E_PIN = "E_pin";
    // 防卡死：连续崩溃计数。panic/brownout 复位时 +1，稳定运行后清零。
    // 连续崩溃 >= 3 次时回退到内置原生时钟（避免某个坏主题导致无限重启）。
    const char* const PREF_CRASH_COUNT = "crashCount";
    // 上一次崩溃时的主题引擎 + 文件名，用于回退后在设置页提示用户「原主题已隔离」。
    const char* const PREF_CRASHED_ENGINE = "crashedEngine";
    const char* const PREF_CRASHED_FILE = "crashedFile";    

    bool swapBlueGreen;
    bool swapBlueRed;
    bool use24hFormat;
    uint8_t displayBright;
    uint16_t autoBrightMin;
    uint16_t autoBrightMax;
    uint8_t ldrPin;
    String timeZone;
    String wifiSsid;
    String wifiPwd;
    String ntpServer;
    String canvasFile;
    // 主题引擎："canvas"（解析 JSON，可上传任意主题）
    // 或 "native-mario"（图片编译进 flash，零 RAM 开销）
    String clockfaceEngine;
    // 主题引擎："canvas"（解析 JSON，可上传任意主题）
    // 或 "native-mario"（图片编译进 flash，零 RAM 开销）
    String canvasServer;
    bool autoRotate;
    // 最后一次已知正确的 UTC 时间戳（秒）。没网启动时用它恢复时间，
    // 否则系统时间是 1970，离线页面只能显示 --:--。
    uint32_t lastEpoch;
    String manualPosix;
    String cachedPosix;
    String cachedTz;
    uint8_t displayRotation;
    uint8_t driver;
    uint32_t i2cSpeed;
    uint8_t E_pin;
    // 防卡死：连续崩溃计数
    uint8_t crashCount;
    String crashedEngine;
    String crashedFile;

    ClockwiseParams() {
        preferences.begin("clockwise", false); 
        //preferences.clear();
    }

    static ClockwiseParams* getInstance() {
        static ClockwiseParams base;
        return &base;
    }

   
    // 只写时间戳这一个键。
    // 时间每 30 分钟存一次，如果走 save() 会把 22 个键全部重写一遍，
    // 白白增加 flash 磨损。NVS 的每个 key 独立写入，这里只动 lastEpoch。
    void saveLastEpoch()
    {
        preferences.putULong(PREF_LAST_EPOCH, lastEpoch);
    }

    void save()
    {
        preferences.putBool(PREF_SWAP_BLUE_GREEN, swapBlueGreen);
        preferences.putBool(PREF_SWAP_BLUE_RED, swapBlueRed);
        preferences.putBool(PREF_USE_24H_FORMAT, use24hFormat);
        preferences.putUInt(PREF_DISPLAY_BRIGHT, displayBright);
        preferences.putUInt(PREF_DISPLAY_ABC_MIN, autoBrightMin);
        preferences.putUInt(PREF_DISPLAY_ABC_MAX, autoBrightMax);
        preferences.putUInt(PREF_LDR_PIN, ldrPin);        
        preferences.putString(PREF_TIME_ZONE, timeZone);
        preferences.putString(PREF_WIFI_SSID, wifiSsid);
        preferences.putString(PREF_WIFI_PASSWORD, wifiPwd);
        preferences.putString(PREF_NTP_SERVER, ntpServer);
        preferences.putString(PREF_CANVAS_FILE, canvasFile);
        preferences.putString(PREF_CLOCKFACE_ENGINE, clockfaceEngine);
        preferences.putString(PREF_CLOCKFACE_ENGINE, clockfaceEngine);
        preferences.putString(PREF_CANVAS_SERVER, canvasServer);
        preferences.putBool(PREF_AUTO_ROTATE, autoRotate);
        preferences.putULong(PREF_LAST_EPOCH, lastEpoch);
        preferences.putString(PREF_MANUAL_POSIX, manualPosix);
        preferences.putString(PREF_CACHED_POSIX, cachedPosix);
        preferences.putString(PREF_CACHED_TZ, cachedTz);
        preferences.putUInt(PREF_DISPLAY_ROTATION, displayRotation);
        preferences.putUInt(PREF_DRIVER, driver);
        preferences.putUInt(PREF_I2CSPEED, i2cSpeed);
        preferences.putUInt(PREF_E_PIN, E_pin);
        preferences.putUChar(PREF_CRASH_COUNT, crashCount);
        preferences.putString(PREF_CRASHED_ENGINE, crashedEngine);
        preferences.putString(PREF_CRASHED_FILE, crashedFile);
    }

    void load()
    {
        swapBlueGreen = preferences.getBool(PREF_SWAP_BLUE_GREEN, false);
        swapBlueRed = preferences.getBool(PREF_SWAP_BLUE_RED, false);
        use24hFormat = preferences.getBool(PREF_USE_24H_FORMAT, true);
        displayBright = preferences.getUInt(PREF_DISPLAY_BRIGHT, 32);
        // 读出来也要钳位：NVS 里可能残留旧固件存下的超限值（>180 曾导致高亮度掉电重启）
        if (displayBright > DISPLAY_BRIGHT_MAX)
            displayBright = DISPLAY_BRIGHT_MAX;
        autoBrightMin = preferences.getUInt(PREF_DISPLAY_ABC_MIN, 0);
        // 默认开启自动亮度：0 = 关闭（见 main.cpp 的 autoBrightEnabled）。
        // 800 是上游 wiki 在 GL5539 + 10k 分压下的实测推荐值：
        // 全暗约 40，全亮约 3700，取 800 作为"已足够亮"的拐点。
        autoBrightMax = preferences.getUInt(PREF_DISPLAY_ABC_MAX, 800);
        ldrPin = preferences.getUInt(PREF_LDR_PIN, 35);        
        timeZone = preferences.getString(PREF_TIME_ZONE, "America/Sao_Paulo");
        wifiSsid = preferences.getString(PREF_WIFI_SSID, "");
        wifiPwd = preferences.getString(PREF_WIFI_PASSWORD, "");
        ntpServer = preferences.getString(PREF_NTP_SERVER, "time.google.com");
        canvasFile = preferences.getString(PREF_CANVAS_FILE, "");
        // 默认沿用 Canvas：老设备升级后行为不变
        clockfaceEngine = preferences.getString(PREF_CLOCKFACE_ENGINE, "canvas");
        // 默认沿用 Canvas：老设备升级后行为不变
        clockfaceEngine = preferences.getString(PREF_CLOCKFACE_ENGINE, "canvas");
        canvasServer = preferences.getString(PREF_CANVAS_SERVER, "raw.githubusercontent.com");
        autoRotate = preferences.getBool(PREF_AUTO_ROTATE, false);
        lastEpoch = preferences.getULong(PREF_LAST_EPOCH, 0);
        manualPosix = preferences.getString(PREF_MANUAL_POSIX, "");
        cachedPosix = preferences.getString(PREF_CACHED_POSIX, "");
        cachedTz = preferences.getString(PREF_CACHED_TZ, "");
        displayRotation = preferences.getUInt(PREF_DISPLAY_ROTATION, 0);
        driver = preferences.getUInt(PREF_DRIVER, 0);
        i2cSpeed = preferences.getUInt(PREF_I2CSPEED, (uint32_t)8000000);
        E_pin = preferences.getUInt(PREF_E_PIN, 18);
        crashCount = preferences.getUChar(PREF_CRASH_COUNT, 0);
        crashedEngine = preferences.getString(PREF_CRASHED_ENGINE, "");
        crashedFile = preferences.getString(PREF_CRASHED_FILE, "");
    }

};


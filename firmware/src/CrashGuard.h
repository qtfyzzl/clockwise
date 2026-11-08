#pragma once
//
// CrashGuard —— 防卡死三件套之一：崩溃计数回退。
//
// 背景：设备「一直自己重启」的典型场景是某个坏主题（JSON 超 16KB 缓冲、
// PNG 解码越界、堆耗尽）导致 panic / brownout → ESP32 复位 → 又加载同一个
// 坏主题 → 再崩，死循环。用户只能手动重烧才能逃出来。
//
// 机制（看 NVS 三个键）：
//   crashCount    连续崩溃计数。panic/brownout 复位时 +1，稳定运行后清零。
//   crashedEngine 上次崩溃时的引擎标识（回退后供设置页提示）
//   crashedFile   上次崩溃时的画布主题文件名
//
// 流程：
//   setup() 最开头调 detectCrash()：读 esp_reset_reason()，
//     是 panic / brownout / watchdog → crashCount+1 并存下当前主题；
//     连续 >= 3 次 → 回退到内置原生时钟（零 JSON、零解码，最稳），
//     并记录原主题到 crashedEngine/crashedFile。
//   loop() 稳定运行一段时间后调 markStable()：crashCount 清零。
//
// 依赖：esp_reset_reason()（ESP32 core 自带）、CWPreferences。
//

#include <esp_system.h>   // esp_reset_reason()
#include <CWPreferences.h>

#ifndef CRASH_GUARD_THRESHOLD
    #define CRASH_GUARD_THRESHOLD 3    // 连续崩溃几次后回退
#endif

#ifndef CRASH_GUARD_STABLE_MS
    #define CRASH_GUARD_STABLE_MS 30000  // 稳定运行多久后清零计数（30 秒）
#endif

namespace crashguard
{

// 复位原因里哪些算「主题崩溃」而非用户主动重启。
static bool isCrashReset()
{
    const esp_reset_reason_t r = esp_reset_reason();
    switch (r)
    {
        case ESP_RST_PANIC:          // 异常/断言/未处理异常
        case ESP_RST_BROWNOUT:       // 电源跌落（高亮度常见）
        case ESP_RST_WDT:            // 看门狗超时
        case ESP_RST_TASK_WDT:       // 任务看门狗
        case ESP_RST_INT_WDT:        // 中断看门狗
        case ESP_RST_SW:             // 软件复位（可能是 assert）
            return true;
        default:
            return false;            // 上电、按键、OTA 等不算崩溃
    }
}

// setup() 开头调用。返回 true 表示发生了「回退到安全主题」的动作。
static bool detectCrash()
{
    ClockwiseParams *p = ClockwiseParams::getInstance();

    if (!isCrashReset())
    {
        // 非崩溃复位（正常上电/用户重启/OTA），不累加计数。
        // 但计数不清零 —— 清零交给 markStable()，避免「崩溃后用户手动重启」
        // 就绕过检测。只有真正稳定运行一段才清零。
        return false;
    }

    uint8_t n = p->crashCount;
    if (n < 255) n++;          // 饱和递增，避免 uint8_t 回绕
    p->crashCount = n;

    // 记下这次崩溃时正在用的主题（回退后才知道要提示用户什么）
    p->crashedEngine = p->clockfaceEngine;
    p->crashedFile   = p->canvasFile;

    Serial.printf("[CrashGuard] 检测到崩溃复位（reason=%d），连续第 %u 次\n",
                  (int)esp_reset_reason(), (unsigned)n);

    if (n < CRASH_GUARD_THRESHOLD)
    {
        p->save();   // 只把计数和崩溃主题存下来，这次还照常启动
        return false;
    }

    // 达到阈值：回退到内置原生时钟（native-mario 零 JSON、零堆解码，最稳）
    Serial.println("[CrashGuard] 连续崩溃达阈值，回退到内置原生时钟");
    p->clockfaceEngine = "native-mario";
    p->canvasFile = "";
    p->crashCount = 0;              // 回退后重置计数，给下次检测留空间
    p->save();

    // 清空 SPIFFS 里的坏主题名？不删文件——用户可能想修复后恢复。
    // 只把「指向它的指针」清掉即可，文件留着。
    return true;
}

// loop() 稳定运行一段时间后调用，清零计数。
// 只有主题真正加载并跑起来了才到这里，说明这次启动是健康的。
static void markStable()
{
    static unsigned long stableSince = 0;
    ClockwiseParams *p = ClockwiseParams::getInstance();

    if (p->crashCount == 0)
    {
        stableSince = 0;
        return;
    }

    if (stableSince == 0)
        stableSince = millis();

    if (millis() - stableSince >= CRASH_GUARD_STABLE_MS)
    {
        Serial.printf("[CrashGuard] 稳定运行 %u 秒，崩溃计数清零\n",
                      (unsigned)(CRASH_GUARD_STABLE_MS / 1000));
        p->crashCount = 0;
        p->crashedEngine = "";
        p->crashedFile = "";
        p->save();
        stableSince = 0;
    }
}

// 给设置页查询：上次是否有主题被隔离。
static bool hasCrashedTheme()
{
    return ClockwiseParams::getInstance()->crashedFile.length() > 0
        || ClockwiseParams::getInstance()->crashedEngine.length() > 0;
}

} // namespace crashguard

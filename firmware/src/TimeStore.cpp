#include "TimeStore.h"

#include <Arduino.h>
#include <time.h>
#include <sys/time.h>
#include <stdlib.h>

#include <CWPreferences.h>

namespace
{
  // 2023-11-14 之后的时间才算"有效"，用来区分"真的同步过"和"开机默认值 1970"
  const time_t MIN_VALID_EPOCH = 1700000000L;
  const uint32_t MIN_VALID_EPOCH_U32 = 1700000000UL;

  const unsigned long SAVE_INTERVAL_MS = 30UL * 60UL * 1000UL;   // 30 分钟

  unsigned long lastSaveMillis = 0;
  bool savedOnce = false;
}

namespace time_store
{
  void applyTimeZone()
  {
    const String posix = ClockwiseParams::getInstance()->manualPosix;
    if (posix.length() == 0)
      return;   // 用户没填手动 POSIX，交给 ezTime / configTime 处理

    setenv("TZ", posix.c_str(), 1);
    tzset();
  }

  void restore()
  {
    applyTimeZone();

    const uint32_t saved = ClockwiseParams::getInstance()->lastEpoch;
    if (saved < MIN_VALID_EPOCH_U32)
      return;                                  // 从来没有同步成功过
    if (time(nullptr) >= MIN_VALID_EPOCH)
      return;                                  // 系统时间已经是对的，别覆盖

    struct timeval tv;
    tv.tv_sec = (time_t)saved;
    tv.tv_usec = 0;
    settimeofday(&tv, nullptr);

    Serial.printf("[Time] 无网络，用存档时间恢复: %lu\n", (unsigned long)saved);
  }

  void saveIfDue()
  {
    const time_t now = time(nullptr);
    if (now < MIN_VALID_EPOCH)
      return;                                  // 时间还不可信，存了反而污染存档

    if (savedOnce && (millis() - lastSaveMillis) < SAVE_INTERVAL_MS)
      return;

    lastSaveMillis = millis();
    savedOnce = true;

    ClockwiseParams *p = ClockwiseParams::getInstance();
    p->lastEpoch = (uint32_t)now;
    p->saveLastEpoch();   // 只写这一个键，别为存时间把整张参数表重写一遍
  }
}

#pragma once

// 时间持久化。
//
// ESP32 没有电池 RTC，断电后系统时间是 1970，离线画面只能显示 --:--。
// 这里把最后一次有效的 NTP 时间写进 NVS，下次没网启动时先恢复它，
// 时间就能从上次同步点继续走（误差 = 关机时长）。
//
// 存档频率 30 分钟：既让误差可控，又不至于频繁写 flash。

namespace time_store
{
  // 启动时调用（要早于任何依赖时间的绘制）。
  // 若系统时间已经有效（刚 NTP 同步过），什么也不做。
  void restore();

  // 主循环里调用；内部按 30 分钟节流，不需要调用方记账。
  void saveIfDue();

  // 把 manualPosix（如 "CST-8"）写进 TZ 环境变量，
  // 让 localtime() 在没有 ezTime 参与的情况下也能给出本地时间。
  void applyTimeZone();
}

#pragma once

// 离线简约时钟。
//
// 背景：Canvas 主题靠 clockface->setup() 渲染，而 setup() 挂在"网络就绪"回调上。
// WiFi 一直连不上时它永远不会被调用，屏幕就停在静态提示上（黑屏/半截画面）。
// 这里提供一个不依赖任何主题、不依赖网络的兜底画面：
//
//     1 1 : 4 7        ← 7 段大数字
//      no wifi         ← 红色小字
//
// 时间来源见 TimeStore.h：没网时用 NVS 里存档的最后一次 NTP 时间恢复，
// 所以断网但没断电时时间是准的；断电重启的误差 = 关机时长。

#include <Arduino.h>
#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>

namespace offline_clock
{
  // 在给定面板上画一帧（调用方负责决定何时画、多久画一次）
  void draw(MatrixPanel_I2S_DMA *display);
}

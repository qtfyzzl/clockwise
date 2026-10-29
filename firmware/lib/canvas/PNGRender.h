#pragma once

// PNG 图片解码 + 绘制到面板的对外接口。
// 实现在 PNGRender.cpp；内部状态（PNG 句柄、解码缓冲）不再暴露给包含者。
//
// 设备兼容性：
//   · 只认 PNG；JPEG 等格式会被拒绝并打印日志
//   · 1-bit / 2-bit 索引色会让设备端 PNGdec 跳空指针 → 无限重启，务必用 8-bit RGB
//   · 单张图解码后必须 ≤ IMAGE_BUFFER_SIZE，否则 mbedtls 返回 -42 且会越界读

#include <Arduino.h>

// 单张图片 base64 解码后的缓冲。
// 上游是 1024，实测官方主题库里 amazon(2802B)、bugcat-1(2232B)、
// mymelo-1(1208B) 三个超限，提到 4096 后全部可渲染（代价 3KB 静态 RAM）。
#define IMAGE_BUFFER_SIZE 4096

// 提前把 48KB 的 PNG 解码缓冲抢下来。
// **必须在 WiFi 启动之前调用**：晚了堆会被 WiFi 栈切碎，new PNG() 会失败，
// 表现是图片和精灵全部不显示。CanvasClockface 的构造函数负责调这个。
void reservePngBuffers();

// 把 base64 编码的 PNG 画到 (x, y)。不是 PNG、超限、解码失败都只跳过并打日志。
void renderImage(const char *base64Image, const uint8_t x, const uint8_t y);

// 读取图片尺寸（不解码像素）。失败时 width/height 保持不变。
void getImageDimensions(const char *base64Image, uint8_t &width, uint8_t &height);

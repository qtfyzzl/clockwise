#pragma once

// 启动与状态提示：LED、Logo、WiFi / NTP 的图标和小字提示。
//
// 位图数据与实现都在 StatusController.cpp —— 原来全写在头文件里，
// 每个包含它的编译单元都会各存一份 PROGMEM 数组，也导致改一行就要全量重编。

#include <Arduino.h>

#define ESP32_LED_BUILTIN 2

struct StatusController
{
	static StatusController *getInstance()
	{
		static StatusController base;
		return &base;
	}

	void clockwiseLogo();
	void wifiConnecting();
	void wifiConnectionFailed(const char *msg);
	void ntpConnecting();
	void printCenter(const char *buf, int y);
	void blink_led(int d, int times);
	void forceRestart();
};

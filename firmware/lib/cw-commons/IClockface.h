#pragma once

#include "CWDateTime.h"

// 所有主题（原生与 Canvas）都实现这个接口。
// 注意：早期版本这里没有 public:，接口方法实际是 private 的，
// 只因为各具体类又自己声明了一遍 public 才没报错。
// 现在 main.cpp 通过 IClockface* 使用，必须显式 public。
class IClockface {
public:
    virtual ~IClockface() = default;

    virtual void setup(CWDateTime *dateTime) = 0;
    virtual void update() = 0;
};

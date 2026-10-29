# Canvas 主题 JSON 生成规范

> 依据：设备端实测。2026-10-29 定位到 `snake-text.json` 闪退的根因。
> 生成完主题后跑 `python tools/check_theme.py 你的文件.json` 自检。

---

## 一、闪退根因（重要）

设备端图形库 **PNGdec 1.0.1** 解码 **1-bit / 2-bit 索引色 PNG** 时有缺陷：
位解包后解到一半跳到空指针，表现为

```
Guru Meditation Error: Core 1 panic'ed (Unhandled debug exception)
Debug exception reason: BREAK instr
EXCVADDR: 0xffffffe0
Backtrace: 只有一层（栈已损坏）
```

设备会**无限重启**，且因为 `canvasFile` 指向这个主题，重启后继续崩，出不来。

### 实测对照

| 主题 | 图片格式 | 结果 |
|---|---|---|
| pac-man | 5×5，8-bit，**RGB (类型 2)** | ✅ 正常 |
| nyan-cat | 64×26，8-bit，**RGBA (类型 6)** | ✅ 正常 |
| christmassnoopy | 64×10，8-bit，**RGBA (类型 6)** | ✅ 正常 |
| keqing-1 | 64×64，**4-bit 调色板 (类型 3)** | ✅ 正常（官方在用） |
| kuromi-1 | **4-bit 调色板** | ✅ 正常 |
| **snake-text** | 64×22，**1-bit / 2-bit 调色板** | ❌ **闪退** |

**结论：位深 1 和 2 是雷区；4/8 位调色板可用，但 8-bit RGB/RGBA 最保险。**

---

## 二、图片规范

| 项 | 要求 | 说明 |
|---|---|---|
| 格式 | **PNG** | 不支持 JPEG/BMP/GIF/WebP |
| 位深 | **8 bit**（保险做法） | 绝对不要 1/2 bit；4 bit 可用但不推荐 |
| 颜色类型 | **2 (RGB) 或 6 (RGBA)** 最稳 | 3（调色板）4-bit/8-bit 一般可用 |
| 宽度 | **≤ 64 px** | 设备每行缓冲只有 64 像素 |
| 高度 | **≤ 64 px** | 超出会被拒绝绘制 |
| 单张体积 | 解码后 **≤ 4096 字节** | `IMAGE_BUFFER_SIZE`（原为 1024，官方主题有 3 个超限） |
| 隔行扫描 | **不要隔行** | 脚本会直接拒绝 |
| 透明 | 支持，但透明像素按主题 `bgColor` 处理 | 半透明会被当不透明 |

### 各软件怎么导出

- **Photoshop**：`文件 → 导出 → 导出为 PNG`，预设选 **PNG-24**；
  如果用「存储为 Web 所用格式」，选 **PNG-8** 或 **PNG-24**，**不要选 PNG-1/2/4**
- **Figma**：直接 Export as PNG（默认就是 8-bit RGBA）
- **Aseprite**：`导出 → PNG`，色彩模式选 **RGB** 或 **Indexed（8-bit）**
- **ImageMagick**：
  ```bash
  magick in.png -depth 8 -define png:bit-depth=8 -define png:color-type=2 out.png
  ```
- **Python (PIL)**：
  ```python
  Image.open('in.png').convert('RGB').save('out.png')
  ```

---

## 三、JSON 结构规范

```jsonc
{
  "name": "显示名（设备日志会打印）",
  "version": "1",
  "author": "@你的名字",
  "bgColor": 0,              // RGB565，0 = 黑
  "delay": 50,               // 默认帧延迟(ms)

  "setup": [                 // 静态元素，每秒刷新一次（放时间/文字）
    { "type": "datetime", "content": "H:i", "font": "big",
      "fgColor": 65535, "bgColor": 0, "x": 2, "y": 1 }
  ],

  "sprites": [               // 二维数组：一组精灵 = 一个帧数组
    [ {"image": "iVBORw0KG..."}, {"image": "..."} ]
  ],

  "loop": [                  // 动画元素，sprite 字段指向 sprites 的下标
    { "type": "sprite", "sprite": 0, "x": 0, "y": 21,
      "frameDelay": 50, "loopDelay": 2000 }
  ]
}
```

### 硬性约束

| 项 | 要求 |
|---|---|
| 整个 JSON | **≤ 16 KB**（设备缓冲 16384，超过直接解析失败） |
| 每个元素 | **必须有 `type` 字段**（缺了设备会 `strcmp(nullptr)` 崩溃） |
| 可用 `type` | `text` `datetime` `image` `rect` `fillrect` `line` `sprite` |
| `loop[].sprite` | 必须在 `sprites` 下标范围内 |
| 坐标 `x`/`y` | 0~63 |

### 性能建议

- 精灵总像素（帧数 × 宽 × 高）**建议 < 40000**
  - 60 帧 × 64×22 = 84,480 → 太大会卡
  - 你的 snake-text 是 39 × 64×22 = 54,912 → 偏大，动画可能掉帧
- 帧数多的话可以**降采样**：39 帧 → 20 帧，`frameDelay` 翻倍，观感接近

---

## 四、两个工具

### 1. 生成前自检

```bash
python tools/check_theme.py canvas/themes/你的主题.json
```

输出每项检查结果，最后给出 `✅ 通过` / `❌ 需要修改`。

### 2. 自动修复图片格式

已经做好但格式不对的主题，**不用重画**：

```bash
python tools/fix_theme_images.py canvas/snake-text.json
# 输出 canvas/snake-text-fixed.json
```

它会把每帧解码后用 8-bit RGB 重新编码，透明像素填成主题背景色。
实测像素级完全一致（0 差异）。

---

## 五、常见错误速查

| 现象 | 原因 |
|---|---|
| 设备无限重启、串口刷 `Guru Meditation` | 图是 1/2-bit 索引色 PNG |
| 主题显示 `Error! Check logs` | JSON > 16KB，或格式错误 |
| 图片不显示但主题能跑 | 单张图解码后 > 4096 字节 |
| 动画卡顿/掉帧 | 帧数 × 尺寸太大 |
| 时间不显示 | `setup` 里没有 `datetime` 元素 |

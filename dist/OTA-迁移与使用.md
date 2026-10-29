# OTA 迁移与使用

> 一次性迁移：需要**按一次 BOOT** 把新分区表烧进去。
> 之后所有固件更新都可以走空中升级，不用再插 USB。

---

## 一、为什么要迁移

上游的分区表 `huge_app.csv` 是**单个 3MB app 分区**，没有备用分区——
而 OTA 的原理是「新固件写进空闲的那一个，校验通过才切换启动」，所以必须有两个 app 分区。

新表 `firmware/partitions_ota.csv`：

```
nvs        0x009000      20 KB
otadata    0x00E000       8 KB   ← OTA 用它记录当前从哪个分区启动
app0       0x010000    1.81 MB
app1       0x1E0000    1.81 MB
spiffs     0x3B0000     256 KB
coredump   0x3F0000      64 KB
                        ─────────
                末尾 0x400000 = 4 MB，无浪费
```

空间账（实测）：

| 项 | 数值 | 说明 |
|---|---|---|
| 固件 | 1,685,357 / 1,900,544 = **88.7%** | 还剩 215 KB 代码余量 |
| SPIFFS | 256 KB | 17 个主题占 107 KB，均值算还能放约 20 个 |

---

## 二、迁移步骤（一次性）

### 1. 烧录（这次仍需按 BOOT）

```powershell
cd dist
.\flash.ps1 -Port COM8
```

按 BOOT 不放，等「写入成功」再松手。**默认分段烧录即可**，`partitions.bin` 已在 0x8000 被覆盖成新表。

> ⚠️ 确认 `dist\partitions.bin` 是新的：它和旧的**大小一样都是 3072 字节**，
> 但内容不同（旧的 app0 是 3072K，新的 app0/app1 各 1856K）。

### 2. 格式化 SPIFFS

SPIFFS 的起始地址从 `0x310000` 变成了 `0x3B0000`，原有主题数据对不上，
启动时会报「存储未就绪」。

设置页 → 主题描述文件 → **格式化存储**（点两次确认），设备会重启。

> 也可以直接发：`curl -X POST "http://<IP>/fs-format"`

### 3. 重传保留的 17 个主题

```bash
python tools/upload_themes.py <设备IP> --only amazon,christmassnoopy,cinnamoroll-1,clock-club,donkey-kong,eletrogate,keqing-1,kuromi-1,nyan-cat,pac-man,peach-gomo-1,pepsi-final-2,retro-computer,sanrio-2,snake-text-fixed,snoopy3,star-wars
```

清单存在 `dist/keep-themes.txt`。**NVS 没有移动**，所以 WiFi、亮度、主题名等设置全部保留。

---

## 三、之后怎么升级固件

### 方式 A：网页上传（不用装工具）

设置页最下面 → **固件升级** → 选 `dist/firmware.bin` → 上传并升级。

- 1.66 MB 约需 1 分钟（实测上传 30~37 KB/s）
- 页面会显示上传百分比
- 传完自动重启，等 20 秒刷新页面

### 方式 B：命令行

```bash
cd firmware
~/.platformio/penv/Scripts/pio.exe run -e ota -t upload --upload-port 192.168.137.216
```

---

## 四、安全性

- **双分区天然回滚**：新固件写完才切换启动分区；`Update.end(true)` 之前任何失败都会 `Update.abort()`，
  设备继续从旧分区启动，不会变砖。
- **中断保护**：30 秒收不到数据自动放弃，不会留半截固件。
- **风险点只有一个**：升级过程中断电。此时 otadata 可能处于中间状态，
  最坏情况是启动到旧固件（数据没坏），但有极小概率需要重新串口烧录。

---

## 五、回退到单分区（如果以后不需要 OTA）

把 `platformio.ini` 里的 `board_build.partitions` 改回 `huge_app.csv`，
重新编译并按 BOOT 整片烧录即可。SPIFFS 会回到 896 KB，但主题需要再传一次。

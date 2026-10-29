#include "PNGRender.h"

// 图片解码与绘制的实现。
//
// 这里的东西原来都写在 PNGRender.h 里（全是 static 函数 + static 缓冲），
// 导致每个包含该头文件的编译单元都各有一份副本，而且改了就要全量重编。
// 现在只把 renderImage / getImageDimensions 两个接口暴露出去，其余仍是文件内 static。
//
// 设备兼容性（改之前先读）：
//   · 只认 PNG，不认 JPEG/BMP/GIF
//   · 1-bit / 2-bit 索引色会让 PNGdec 跳空指针，设备无限重启
//   · 单张解码后 ≤ IMAGE_BUFFER_SIZE（4096）

#include <Locator.h>
#include "mbedtls/base64.h"
#include <PNGdec.h>

// 单张图片 base64 解码后的缓冲。
// 上游是 1024，实测官方主题库里有 3 个超了：amazon(2802B)、bugcat-1(2232B)、
// mymelo-1(1208B)。超限时 mbedtls 返回 -42(BUFFER_TOO_SMALL)，而上游没检查返回值，
// 会拿着"需要的长度"去读一块更小的缓冲 —— 越界读。
// 提到 4096 后 33 个官方主题全部可渲染，代价是 3KB 静态 RAM。
#define IMAGE_BUFFER_SIZE 4096

// PNGdec 的 PNG 结构体自带 4 个内嵌缓冲：
//   ucZLIB[32768 + sizeof(inflate_state)]  ~34KB （作者注释：为了避免 malloc/free）
//   ucPalette[1024]
//   ucPixels[PNG_MAX_BUFFERED_PIXELS * 2]  ~5KB  （640*4+1 个像素）
//   ucFileBuf[2048]
// 合计约 48KB。上游把它声明成 `static PNG png;`，这 48KB 会常驻 .bss，
// 把静态内存从 52KB 顶到 101KB，导致 ESP-IDF 启动时连主任务的栈都分配不出来：
//   assert failed: esp_startup_start_app app_startup.c:86 (res == pdTRUE)
// 因此改成首次使用时从堆分配一次，之后常驻复用（不 free，避免碎片）。
static PNG *g_png = nullptr;

static PNG *pngHandle()
{
  if (g_png == nullptr)
  {
    // 用 new 而不是 malloc：PNG 是类，需要走构造函数
    g_png = new PNG();
    if (g_png == nullptr)
    {
      Serial.printf("[Canvas] PNG 缓冲分配失败 free=%u maxAlloc=%u\n",
                    ESP.getFreeHeap(), ESP.getMaxAllocHeap());
    }
    else
    {
      Serial.printf("[Canvas] PNG 缓冲就绪 size=%u free=%u\n",
                    (unsigned)sizeof(PNG), ESP.getFreeHeap());
    }
  }
  return g_png;
}

// 前几帧打点，用来定位崩溃发生在哪一步（正常跑起来后自动静默）
static uint8_t g_renderDebugCount = 0;

static unsigned char decodedArray[IMAGE_BUFFER_SIZE];
static size_t decodedArrayLength;

typedef struct png_position
{
  uint8_t xoff, yoff;
} PNG_POSITION;


static void PNGDraw(PNGDRAW *pDraw)
{
  // usPixels 只有 64 像素。图比 64 宽时 getLineAsRGB565 会写穿这块栈内存，
  // 现象是 Guru Meditation / BREAK instr / EXCVADDR 0xffffffe0，栈被打烂只剩一层回溯。
  // 所以这里按实际行宽截断，宁可画不全也不能崩。
  uint16_t usPixels[64];

  if (pDraw->iWidth > 64)
  {
    if (g_renderDebugCount < 3)
      Serial.printf("[dbg]   行宽 %d > 64，跳过\n", pDraw->iWidth);
    return;
  }

  PNG_POSITION *pPos = (PNG_POSITION *)pDraw->pUser;

  pngHandle()->getLineAsRGB565(pDraw, usPixels, PNG_RGB565_LITTLE_ENDIAN, 0xffffffff);

  Locator::getDisplay()->drawRGBBitmap(pPos->xoff, pPos->yoff + pDraw->y, usPixels, pDraw->iWidth, 1);
}


static bool openImage(const char *base64Image)
{
  PNG *png = pngHandle();
  if (png == nullptr)
    return false;

  // 主题 JSON 里缺 image 字段时这里是 nullptr，直接 strlen 会崩
  if (base64Image == nullptr || base64Image[0] == '\0')
    return false;

  decodedArrayLength = 0;
  int b64rc = mbedtls_base64_decode(decodedArray, IMAGE_BUFFER_SIZE, &decodedArrayLength,
                                    (const unsigned char *)base64Image, strlen(base64Image));
  if (b64rc != 0 || decodedArrayLength == 0)
  {
    // -42 = MBEDTLS_ERR_BASE64_BUFFER_TOO_SMALL：解码后体积超过 IMAGE_BUFFER_SIZE。
    // 注意 mbedtls 失败时会把 decodedArrayLength 改成「需要的长度」，
    // 上游没检查返回值就拿这个长度去读缓冲 —— 越界读，所以这里必须拦。
    Serial.printf("[Canvas] base64 解码失败 rc=%d 需要 %u 字节（上限 %u）\n",
                  b64rc, (unsigned)decodedArrayLength, (unsigned)IMAGE_BUFFER_SIZE);
    return false;
  }

  // 先验签名再交给解码器：主题里可能混入 JPEG（官方 amazon 主题就有一张），
  // 不检查的话 openRAM 会失败但说不清原因。
  if (!(decodedArray[0] == 0x89 && decodedArray[1] == 'P' &&
        decodedArray[2] == 'N' && decodedArray[3] == 'G'))
  {
    Serial.printf("[Canvas] 图片不是 PNG（首字节 %02X %02X），已跳过\n",
                  decodedArray[0], decodedArray[1]);
    return false;
  }

  int rc = png->openRAM(decodedArray, decodedArrayLength, PNGDraw);
  if (rc != PNG_SUCCESS)
    return false;

  // 尺寸超过面板就拒绝，否则绘制会越界
  if (png->getWidth() > 64 || png->getHeight() > 64)
  {
    Serial.printf("[Canvas] 图片 %ux%u 超出 64x64，跳过\n", png->getWidth(), png->getHeight());
    png->close();
    return false;
  }

  return true;
}


void reservePngBuffers()
{
  pngHandle();
}

void renderImage(const char *base64Image, const uint8_t x, const uint8_t y)
{
  const bool dbg = (g_renderDebugCount < 3);
  if (dbg)
    Serial.printf("[dbg] #%u renderImage 进入 x=%u y=%u\n", g_renderDebugCount, x, y);

  PNG_POSITION pos;

  if (openImage(base64Image))
  {
    if (dbg)
      Serial.println("[dbg]   openImage 成功");

    PNG *png = pngHandle();
    pos.xoff = x;
    pos.yoff = y;

    if (dbg)
      Serial.println("[dbg]   调用 decode ...");
    png->decode((void *)&pos, 0);
    if (dbg)
      Serial.println("[dbg]   decode 返回");

    png->close();
  }
  else if (dbg)
  {
    Serial.println("[dbg]   openImage 失败（已跳过）");
  }

  if (g_renderDebugCount < 255)
    g_renderDebugCount++;
}


void getImageDimensions(const char *base64Image, uint8_t &width, uint8_t &height)
{
  if (openImage(base64Image)) {
    PNG *png = pngHandle();
    width = png->getWidth();
    height = png->getHeight();

    png->close();
  }
}

/* gfx.js — Adafruit GFX 语义的 64×64 软渲染器
 *
 * 目标是「编辑器里看到的 = 点阵屏上亮出来的」。所有绘制都按固件里的真实调用实现：
 *   fillRect / drawRect / drawLine / setCursor+print / getTextBounds
 * 字体字形取自 firmware 的 Adafruit GFXfont 头文件（由 tools/extract_fonts.py 抽取）。
 */
(function (global) {
  'use strict';

  // ---------- 颜色：RGB565 <-> RGB888 ----------
  function rgb565ToRgb(v) {
    v = v & 0xffff;
    const r = (v >> 11) & 0x1f, g = (v >> 5) & 0x3f, b = v & 0x1f;
    return {
      r: (r * 255 + 15) / 31 | 0,
      g: (g * 255 + 31) / 63 | 0,
      b: (b * 255 + 15) / 31 | 0,
    };
  }
  function rgbTo565(r, g, b) {
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
  }
  function hexTo565(hex) {
    const h = String(hex).replace('#', '');
    const n = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h, 16);
    return rgbTo565((n >> 16) & 255, (n >> 8) & 255, n & 255);
  }
  function rgb565ToHex(v) {
    const c = rgb565ToRgb(v);
    return '#' + [c.r, c.g, c.b].map(x => x.toString(16).padStart(2, '0')).join('').toUpperCase();
  }
  // 打包成 0xRRGGBB，方便直接写 canvas ImageData
  function pack(r, g, b) { return ((r & 255) << 16) | ((g & 255) << 8) | (b & 255); }
  function pack565(v) { const c = rgb565ToRgb(v); return pack(c.r, c.g, c.b); }

  // ---------- 字体 ----------
  let FONTDB = null;
  const FONT_NAMES = ['big', 'medium', 'square', 'picopixel'];
  const FONT_LABEL = {
    big: 'big（hour8pt7b，字高 14）',
    medium: 'medium（minute7pt7b，字高 9）',
    square: 'square（atariFont，字高 11）',
    picopixel: 'picopixel（字高 5）',
    '': '默认 5×7（固件内置）',
  };

  function setFontData(json) { FONTDB = json.fonts; }
  function fontFor(name) { return (FONTDB && FONTDB[name]) || null; }
  function fontInfo(name) {
    const f = fontFor(name);
    if (!f) return { known: false, label: FONT_LABEL[''], yAdvance: 8, first: 32, last: 126 };
    return { known: true, label: FONT_LABEL[name] || name, yAdvance: f.yAdvance, first: f.first, last: f.last };
  }
  // square 字体只有 12 个字形有像素，用它写字母等于画空白
  function glyphCoverage(name) {
    const f = fontFor(name);
    if (!f) return { painted: 95, total: 95 };
    return { painted: f.painted, total: f.total };
  }

  // Adafruit_GFX::getTextBounds 的逐字复刻
  // 返回 {x1,y1,w,h}（相对光标 x,y 的包围盒），与固件 renderText 里 fillRect 用的值一致
  function getTextBounds(fontName, str, x, y) {
    const f = fontFor(fontName);
    let minx = 32767, miny = 32767, maxx = -1, maxy = -1, cx = x;
    if (!f) {
      // 默认字体：6px 步进、5×7 字形、基线在 y，向上 7px
      for (const ch of String(str)) {
        if (ch === ' ') { cx += 6; continue; }
        if (cx < minx) minx = cx;
        if (y - 7 < miny) miny = y - 7;
        if (cx + 5 > maxx) maxx = cx + 5;
        if (y > maxy) maxy = y;
        cx += 6;
      }
      if (maxx < 0) return { x1: x, y1: y, w: 0, h: 0, advance: cx - x, approx: true };
      return { x1: minx, y1: miny, w: maxx - minx, h: maxy - miny, advance: cx - x, approx: true };
    }
    for (const ch of String(str)) {
      const gi = ch.codePointAt(0) - f.first;
      if (gi < 0 || gi >= f.glyphs.length) continue;
      const g = f.glyphs[gi];
      const gx = cx + g[4], gy = y + g[5];
      if (gx < minx) minx = gx;
      if (gy < miny) miny = gy;
      if (gx + g[1] > maxx) maxx = gx + g[1];
      if (gy + g[2] > maxy) maxy = gy + g[2];
      cx += g[3];
    }
    if (maxx < 0) return { x1: x, y1: y, w: 0, h: 0, advance: 0, approx: false };
    return { x1: minx, y1: miny, w: maxx - minx, h: maxy - miny, advance: cx - x, approx: false };
  }

  // ---------- 像素缓冲 ----------
  function Buf(w, h, bgPacked) {
    this.w = w; this.h = h;
    this.data = new Int32Array(w * h);
    if (bgPacked !== undefined) this.data.fill(bgPacked);
  }
  Buf.prototype.set = function (x, y, c) {
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return;
    this.data[y * this.w + x] = c;
  };
  Buf.prototype.get = function (x, y) {
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return 0;
    return this.data[y * this.w + x];
  };
  // Adafruit_GFX::fillRect —— 覆盖 x .. x+w-1
  Buf.prototype.fillRect = function (x, y, w, h, c) {
    for (let py = y; py < y + h; py++) this.hline(x, x + w - 1, py, c);
  };
  Buf.prototype.hline = function (x0, x1, y, c) {
    if (y < 0 || y >= this.h) return;
    if (x0 > x1) { const t = x0; x0 = x1; x1 = t; }
    for (let x = x0; x <= x1; x++) this.set(x, y, c);
  };
  Buf.prototype.vline = function (y0, y1, x, c) {
    if (x < 0 || x >= this.w) return;
    if (y0 > y1) { const t = y0; y0 = y1; y1 = t; }
    for (let y = y0; y <= y1; y++) this.set(x, y, c);
  };
  // Adafruit_GFX::drawRect
  Buf.prototype.drawRect = function (x, y, w, h, c) {
    this.hline(x, x + w - 1, y, c);
    this.hline(x, x + w - 1, y + h - 1, c);
    this.vline(y, y + h - 1, x, c);
    this.vline(y, y + h - 1, x + w - 1, c);
  };
  // Adafruit_GFX::drawLine（Bresenham，含 steep 换轴，逐像素一致）
  Buf.prototype.drawLine = function (x0, y0, x1, y1, c) {
    const steep = Math.abs(y1 - y0) > Math.abs(x1 - x0);
    if (steep) { let t = x0; x0 = y0; y0 = t; t = x1; x1 = y1; y1 = t; }
    if (x0 > x1) { let t = x0; x0 = x1; x1 = t; t = y0; y0 = y1; y1 = t; }
    const dx = x1 - x0, dy = Math.abs(y1 - y0);
    let err = dx >> 1, y = y0;
    const ystep = y0 < y1 ? 1 : -1;
    for (; x0 <= x1; x0++) {
      if (steep) this.set(y, x0, c); else this.set(x0, y, c);
      err -= dy;
      if (err < 0) { y += ystep; err += dx; }
    }
  };

  // Adafruit_GFX::drawChar —— 位图是连续比特流（跨行不分字节对齐），MSB 先行
  function drawText(buf, fontName, str, x, y, color) {
    const f = fontFor(fontName);
    let cx = x;
    if (!f) return cx; // 默认字体不预览字形（见 properties 提示）
    for (const ch of String(str)) {
      const gi = ch.codePointAt(0) - f.first;
      if (gi < 0 || gi >= f.glyphs.length) continue;
      const g = f.glyphs[gi];
      const [off, gw, gh, xadv, xo, yo] = g;
      let bit = off * 8;
      const end = bit + gw * gh;
      for (let row = 0; row < gh; row++) {
        for (let col = 0; col < gw; col++, bit++) {
          if (bit >= end) break;
          const byteIdx = bit >> 3;
          if (byteIdx >= f.bitmaps.length) continue;
          const on = (f.bitmaps[byteIdx] >> (7 - (bit & 7))) & 1;
          if (on) buf.set(cx + xo + col, y + yo + row, color);
        }
      }
      cx += xadv;
    }
    return cx;
  }

  // ---------- 时间格式（ezTime 的 PHP 风格） ----------
  const DAY3 = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const MON3 = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const DAYFULL = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const MONFULL = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  function pad2(n) { return n < 10 ? '0' + n : '' + n; }

  function phpFormat(fmt, d) {
    d = d || new Date();
    let out = '';
    for (let i = 0; i < fmt.length; i++) {
      const ch = fmt[i];
      if (ch === '\\') { out += fmt[++i] || ''; continue; }
      const H = d.getHours(), m = d.getMinutes(), s = d.getSeconds();
      switch (ch) {
        case 'H': out += pad2(H); break;
        case 'G': out += H; break;
        case 'h': out += pad2(H % 12 === 0 ? 12 : H % 12); break;
        case 'g': out += (H % 12 === 0 ? 12 : H % 12); break;
        case 'i': out += pad2(m); break;
        case 's': out += pad2(s); break;
        case 'A': out += H < 12 ? 'AM' : 'PM'; break;
        case 'a': out += H < 12 ? 'am' : 'pm'; break;
        case 'd': out += pad2(d.getDate()); break;
        case 'j': out += d.getDate(); break;
        case 'D': out += DAY3[d.getDay()]; break;
        case 'l': out += DAYFULL[d.getDay()]; break;
        case 'N': out += d.getDay() === 0 ? 7 : d.getDay(); break;
        case 'w': out += d.getDay(); break;
        case 'm': out += pad2(d.getMonth() + 1); break;
        case 'n': out += d.getMonth() + 1; break;
        case 'M': out += MON3[d.getMonth()]; break;
        case 'F': out += MONFULL[d.getMonth()]; break;
        case 'Y': out += d.getFullYear(); break;
        case 'y': out += pad2(d.getFullYear() % 100); break;
        default: out += ch;
      }
    }
    return out;
  }

  // ---------- 主题渲染 ----------
  // 绘制顺序与固件一致：先铺 bgColor，再按顺序画 setup 里的静态元素，
  // 最后才画 datetime（refreshDateTime 在 clockfaceSetup 末尾跑，永远压在上面）。
  function drawElement(buf, el, ctx) {
    switch (el.type) {
      case 'fillrect':
        buf.fillRect(el.x | 0, el.y | 0, el.width | 0, el.height | 0, pack565(el.color | 0));
        break;
      case 'rect':
        buf.drawRect(el.x | 0, el.y | 0, el.width | 0, el.height | 0, pack565(el.color | 0));
        break;
      case 'line':
        buf.drawLine(el.x | 0, el.y | 0, el.x1 | 0, el.y1 | 0, pack565(el.color | 0));
        break;
      case 'text':
      case 'datetime': {
        const content = el.type === 'datetime' ? phpFormat(el.content || '', ctx.now) : String(el.content || '');
        const b = getTextBounds(el.font || '', content, el.x | 0, el.y | 0);
        // 固件先按 bbox 铺一次 bgColor，再画字 —— 所以文字永远是不透明底
        if (el.bgColor !== undefined) buf.fillRect(el.x + b.x1, el.y + b.y1, b.w, b.h, pack565(el.bgColor));
        drawText(buf, el.font || '', content, el.x | 0, el.y | 0, pack565(el.fgColor | 0));
        break;
      }
      case 'image': {
        const img = ctx.images.get(el._id);
        if (img) drawRGBA(buf, img, el.x | 0, el.y | 0);
        break;
      }
    }
  }

  function drawRGBA(buf, img, ox, oy) {
    const { w, h, rgba } = img;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 4;
        if (rgba[i + 3] === 0) continue; // 全透明像素不画（固件里是透明色，视觉上等于没画）
        buf.set(ox + x, oy + y, pack(rgba[i], rgba[i + 1], rgba[i + 2]));
      }
    }
  }

  function renderTheme(theme, opts) {
    opts = opts || {};
    const buf = new Buf(64, 64, pack565(theme.bgColor | 0));
    const ctx = { now: opts.now || new Date(), images: opts.images || new Map() };
    const setup = theme.setup || [];
    for (const el of setup) if (el.type !== 'datetime') drawElement(buf, el, ctx);
    for (const el of setup) if (el.type === 'datetime') drawElement(buf, el, ctx);
    // 精灵：由调用方决定当前帧与位置
    if (opts.sprites) {
      for (const s of opts.sprites) {
        if (s && s.img) drawRGBA(buf, s.img, s.x | 0, s.y | 0);
      }
    }
    return buf;
  }

  // 把 64×64 缓冲画到可见 canvas（scale 为整数缩放，最近邻）
  function blit(buf, cvs, scale, dpr) {
    dpr = dpr || 1;
    const px = Math.max(1, Math.round(scale * dpr));
    const W = buf.w * px, H = buf.h * px;
    if (cvs.width !== W) cvs.width = W;
    if (cvs.height !== H) cvs.height = H;
    const g = cvs.getContext('2d');
    g.imageSmoothingEnabled = false;
    const im = g.createImageData(buf.w * px, buf.h * px);
    const d = im.data;
    for (let y = 0; y < buf.h; y++) {
      for (let x = 0; x < buf.w; x++) {
        const c = buf.data[y * buf.w + x];
        const r = (c >> 16) & 255, gg = (c >> 8) & 255, b = c & 255;
        for (let sy = 0; sy < px; sy++) {
          let o = ((y * px + sy) * W + x * px) * 4;
          for (let sx = 0; sx < px; sx++, o += 4) {
            d[o] = r; d[o + 1] = gg; d[o + 2] = b; d[o + 3] = 255;
          }
        }
      }
    }
    g.putImageData(im, 0, 0);
    return g;
  }

  const API = {
    rgb565ToRgb, rgbTo565, hexTo565, rgb565ToHex, pack565, pack, Buf,
    setFontData, fontFor, fontInfo, glyphCoverage, getTextBounds, drawText,
    phpFormat, renderTheme, drawRGBA, blit, FONT_NAMES, FONT_LABEL,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  else global.GFX = API;
})(typeof window !== 'undefined' ? window : globalThis);

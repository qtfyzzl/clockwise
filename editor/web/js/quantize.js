/* quantize.js — 图片缩放 + 调色板量化
 *
 * 点阵屏的硬限制：单张 PNG 解码后 ≤1024 字节，所以图片必须
 *   ① 缩小（32×32 已经算大）② 索引色（≤16 色，4bpp）③ 无元数据
 * 这里负责 ①②，编码见 png.js。
 */
(function (global) {
  'use strict';

  // 最近邻：像素画保真，不糊
  function resizeNearest(src, sw, sh, dw, dh) {
    const out = new Uint8ClampedArray(dw * dh * 4);
    for (let y = 0; y < dh; y++) {
      const sy = Math.min(sh - 1, Math.floor((y + 0.5) * sh / dh));
      for (let x = 0; x < dw; x++) {
        const sx = Math.min(sw - 1, Math.floor((x + 0.5) * sw / dw));
        const si = (sy * sw + sx) * 4, di = (y * dw + x) * 4;
        out[di] = src[si]; out[di + 1] = src[si + 1]; out[di + 2] = src[si + 2]; out[di + 3] = src[si + 3];
      }
    }
    return out;
  }

  // 盒式平均：照片类缩小时更稳（按 alpha 加权，避免透明边缘发黑）
  function resizeBox(src, sw, sh, dw, dh) {
    const out = new Uint8ClampedArray(dw * dh * 4);
    for (let y = 0; y < dh; y++) {
      const y0 = Math.floor(y * sh / dh), y1 = Math.max(y0 + 1, Math.floor((y + 1) * sh / dh));
      for (let x = 0; x < dw; x++) {
        const x0 = Math.floor(x * sw / dw), x1 = Math.max(x0 + 1, Math.floor((x + 1) * sw / dw));
        let r = 0, g = 0, b = 0, a = 0, n = 0;
        for (let yy = y0; yy < y1 && yy < sh; yy++) {
          for (let xx = x0; xx < x1 && xx < sw; xx++) {
            const i = (yy * sw + xx) * 4;
            const al = src[i + 3] / 255;
            r += src[i] * al; g += src[i + 1] * al; b += src[i + 2] * al; a += al; n++;
          }
        }
        const di = (y * dw + x) * 4;
        if (a > 0.001) {
          out[di] = r / a; out[di + 1] = g / a; out[di + 2] = b / a;
          out[di + 3] = Math.round(a / n * 255);
        } else {
          out[di] = 0; out[di + 1] = 0; out[di + 2] = 0; out[di + 3] = 0;
        }
      }
    }
    return out;
  }

  // 透明像素压到背景色（固件没有 alpha 混合，透明像素会直接按原色画）
  function flatten(rgba, bg) {
    const out = new Uint8ClampedArray(rgba.length);
    for (let i = 0; i < rgba.length; i += 4) {
      const a = rgba[i + 3] / 255;
      out[i] = rgba[i] * a + bg[0] * (1 - a);
      out[i + 1] = rgba[i + 1] * a + bg[1] * (1 - a);
      out[i + 2] = rgba[i + 2] * a + bg[2] * (1 - a);
      out[i + 3] = 255;
    }
    return out;
  }

  // 中位切分（median cut）：比固定调色板更贴合图片本身
  function medianCut(rgba, maxColors) {
    const px = [];
    for (let i = 0; i < rgba.length; i += 4) px.push([rgba[i], rgba[i + 1], rgba[i + 2]]);

    // 先统计唯一色，色数不够就直接用
    const uniq = new Map();
    for (const p of px) {
      const k = (p[0] << 16) | (p[1] << 8) | p[2];
      uniq.set(k, (uniq.get(k) || 0) + 1);
    }
    if (uniq.size <= maxColors) {
      const palette = [...uniq.keys()].map(k => [(k >> 16) & 255, (k >> 8) & 255, k & 255]);
      return palette;
    }

    let boxes = [{ px, rmin: 0 }];
    boxes[0] = boxOf(px);
    while (boxes.length < maxColors) {
      // 选「颜色跨度最大 × 像素数」的盒子来切，避免只切到大片纯色
      let bi = -1, best = -1;
      for (let i = 0; i < boxes.length; i++) {
        const b = boxes[i];
        if (b.px.length < 2) continue;
        const span = Math.max(b.rr, b.gr, b.br) * Math.log(b.px.length + 1);
        if (span > best) { best = span; bi = i; }
      }
      if (bi < 0) break;
      const b = boxes[bi];
      const axis = (b.rr >= b.gr && b.rr >= b.br) ? 0 : (b.gr >= b.br ? 1 : 2);
      b.px.sort((p, q) => p[axis] - q[axis]);
      const mid = b.px.length >> 1;
      const left = boxOf(b.px.slice(0, mid)), right = boxOf(b.px.slice(mid));
      if (!left.px.length || !right.px.length) break;
      boxes.splice(bi, 1, left, right);
    }
    return boxes.map(b => {
      let r = 0, g = 0, bl = 0;
      for (const p of b.px) { r += p[0]; g += p[1]; bl += p[2]; }
      const n = b.px.length;
      return [Math.round(r / n), Math.round(g / n), Math.round(bl / n)];
    });
  }

  function boxOf(px) {
    let rmin = 255, rmax = 0, gmin = 255, gmax = 0, bmin = 255, bmax = 0;
    for (const p of px) {
      if (p[0] < rmin) rmin = p[0]; if (p[0] > rmax) rmax = p[0];
      if (p[1] < gmin) gmin = p[1]; if (p[1] > gmax) gmax = p[1];
      if (p[2] < bmin) bmin = p[2]; if (p[2] > bmax) bmax = p[2];
    }
    return { px, rr: rmax - rmin, gr: gmax - gmin, br: bmax - bmin };
  }

  function nearest(pal, r, g, b) {
    let bi = 0, bd = Infinity;
    for (let i = 0; i < pal.length; i++) {
      const dr = r - pal[i][0], dg = g - pal[i][1], db = b - pal[i][2];
      // 人眼对绿更敏感，加权欧氏距离
      const d = dr * dr * 3 + dg * dg * 6 + db * db * 1;
      if (d < bd) { bd = d; bi = i; }
    }
    return bi;
  }

  // 索引化（可选 Floyd–Steinberg 抖动）
  function mapToPalette(rgba, w, h, pal, dither) {
    const idx = new Uint8Array(w * h);
    if (!dither) {
      for (let i = 0, p = 0; i < rgba.length; i += 4, p++) idx[p] = nearest(pal, rgba[i], rgba[i + 1], rgba[i + 2]);
      return idx;
    }
    const buf = new Float32Array(rgba.length);
    for (let i = 0; i < rgba.length; i++) buf[i] = rgba[i];
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 4;
        const r = Math.max(0, Math.min(255, buf[i])), g = Math.max(0, Math.min(255, buf[i + 1])), b = Math.max(0, Math.min(255, buf[i + 2]));
        const k = nearest(pal, r, g, b);
        idx[y * w + x] = k;
        const er = r - pal[k][0], eg = g - pal[k][1], eb = b - pal[k][2];
        const put = (xx, yy, f) => {
          if (xx < 0 || xx >= w || yy < 0 || yy >= h) return;
          const j = (yy * w + xx) * 4;
          buf[j] += er * f; buf[j + 1] += eg * f; buf[j + 2] += eb * f;
        };
        put(x + 1, y, 7 / 16); put(x - 1, y + 1, 3 / 16); put(x, y + 1, 5 / 16); put(x + 1, y + 1, 1 / 16);
      }
    }
    return idx;
  }

  // 主入口：源图 RGBA + 目标尺寸/色数 -> 索引图 + 调色板 + 量化后 RGBA（用于预览）
  function rasterize(src, sw, sh, opt) {
    opt = opt || {};
    const dw = Math.max(1, Math.min(64, opt.w | 0 || sw));
    const dh = Math.max(1, Math.min(64, opt.h | 0 || sh));
    const maxColors = Math.max(2, Math.min(256, opt.maxColors | 0 || 16));
    let img = (opt.resize === 'box') ? resizeBox(src, sw, sh, dw, dh) : resizeNearest(src, sw, sh, dw, dh);
    img = flatten(img, opt.bg || [0, 0, 0]);
    const pal = medianCut(img, maxColors);
    const idx = mapToPalette(img, dw, dh, pal, !!opt.dither);
    const prev = new Uint8ClampedArray(dw * dh * 4);
    for (let p = 0; p < idx.length; p++) {
      const c = pal[idx[p]];
      prev[p * 4] = c[0]; prev[p * 4 + 1] = c[1]; prev[p * 4 + 2] = c[2]; prev[p * 4 + 3] = 255;
    }
    return { w: dw, h: dh, palette: pal, indices: idx, rgba: prev, colors: pal.length };
  }

  const API = { resizeNearest, resizeBox, flatten, medianCut, mapToPalette, rasterize };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  else global.QZ = API;
})(typeof window !== 'undefined' ? window : globalThis);

/* png.js — 索引色 PNG 编码器（专为 1024 字节预算设计）
 *
 * 为什么不直接用 canvas.toDataURL('image/png')：
 *   浏览器只能导出 24/32 位真彩 PNG，40×40 就要 1.5KB+，必然超限。
 *   这里手写 IHDR/PLTE/IDAT/IEND，用索引色 + 4bpp + 无滤镜，
 *   同样的图能压到 300~600 字节。
 * 压缩走 CompressionStream('deflate')（输出即 zlib 流，正好是 IDAT 要的格式），
 * 环境没有该 API 时退化为 stored block（合法但更大）。
 */
(function (global) {
  'use strict';

  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      t[n] = c >>> 0;
    }
    return t;
  })();

  function crc32(bytes, start, end) {
    let c = 0xFFFFFFFF;
    for (let i = start; i < end; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  function adler32(bytes) {
    let a = 1, b = 0;
    for (let i = 0; i < bytes.length; i++) {
      a = (a + bytes[i]) % 65521;
      b = (b + a) % 65521;
    }
    return ((b << 16) | a) >>> 0;
  }

  const SIG = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];

  function chunk(type, data) {
    const out = new Uint8Array(12 + data.length);
    const len = data.length;
    out[0] = (len >>> 24) & 255; out[1] = (len >>> 16) & 255; out[2] = (len >>> 8) & 255; out[3] = len & 255;
    for (let i = 0; i < 4; i++) out[4 + i] = type.charCodeAt(i);
    out.set(data, 8);
    const c = crc32(out, 4, 8 + len);
    out[8 + len] = (c >>> 24) & 255; out[9 + len] = (c >>> 16) & 255;
    out[10 + len] = (c >>> 8) & 255; out[11 + len] = c & 255;
    return out;
  }

  function concat(parts) {
    let n = 0;
    for (const p of parts) n += p.length;
    const out = new Uint8Array(n);
    let o = 0;
    for (const p of parts) { out.set(p, o); o += p.length; }
    return out;
  }

  function bitDepthFor(colors) {
    if (colors <= 2) return 1;
    if (colors <= 4) return 2;
    if (colors <= 16) return 4;
    return 8;
  }

  // 每行一个 filter 字节(0)，像素按位深打包，MSB 在前，行末补齐到字节
  function packScanlines(indices, w, h, bd) {
    const perByte = 8 / bd;
    const rowBytes = Math.ceil(w / perByte);
    const out = new Uint8Array((rowBytes + 1) * h);
    const mask = (1 << bd) - 1;
    let o = 0;
    for (let y = 0; y < h; y++) {
      out[o++] = 0;
      const rowStart = o;
      for (let x = 0; x < w; x++) {
        const shift = 8 - bd * ((x % perByte) + 1);
        out[rowStart + ((x / perByte) | 0)] |= (indices[y * w + x] & mask) << shift;
      }
      o += rowBytes;
    }
    return out;
  }

  function zlibStored(raw) {
    const parts = [new Uint8Array([0x78, 0x01])];
    let off = 0;
    if (raw.length === 0) {
      parts.push(new Uint8Array([0x01, 0x00, 0x00, 0xFF, 0xFF]));
    }
    while (off < raw.length) {
      const n = Math.min(65535, raw.length - off);
      const final = off + n >= raw.length ? 1 : 0;
      const head = new Uint8Array(5);
      head[0] = final;
      head[1] = n & 255; head[2] = (n >>> 8) & 255;
      head[3] = (~n) & 255; head[4] = ((~n) >>> 8) & 255;
      parts.push(head, raw.subarray(off, off + n));
      off += n;
    }
    const ad = adler32(raw);
    parts.push(new Uint8Array([(ad >>> 24) & 255, (ad >>> 16) & 255, (ad >>> 8) & 255, ad & 255]));
    return concat(parts);
  }

  async function zlibDeflate(raw) {
    if (typeof CompressionStream === 'undefined') return zlibStored(raw);
    try {
      const cs = new CompressionStream('deflate');
      const stream = new Blob([raw]).stream().pipeThrough(cs);
      const buf = await new Response(stream).arrayBuffer();
      const out = new Uint8Array(buf);
      return out.length < zlibStored(raw).length ? out : zlibStored(raw);
    } catch (e) {
      return zlibStored(raw);
    }
  }

  /**
   * 编码索引色 PNG。
   * @param {number} w
   * @param {number} h
   * @param {Uint8Array} indices 每像素调色板下标
   * @param {Array<[number,number,number]>} palette
   * @returns {Promise<Uint8Array>}
   */
  async function encodeIndexed(w, h, indices, palette) {
    const bd = bitDepthFor(palette.length);
    const ihdr = new Uint8Array(13);
    ihdr[0] = (w >>> 24) & 255; ihdr[1] = (w >>> 16) & 255; ihdr[2] = (w >>> 8) & 255; ihdr[3] = w & 255;
    ihdr[4] = (h >>> 24) & 255; ihdr[5] = (h >>> 16) & 255; ihdr[6] = (h >>> 8) & 255; ihdr[7] = h & 255;
    ihdr[8] = bd; ihdr[9] = 3; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;

    const plte = new Uint8Array(palette.length * 3);
    for (let i = 0; i < palette.length; i++) {
      plte[i * 3] = palette[i][0]; plte[i * 3 + 1] = palette[i][1]; plte[i * 3 + 2] = palette[i][2];
    }
    const raw = packScanlines(indices, w, h, bd);
    const z = await zlibDeflate(raw);

    return concat([
      new Uint8Array(SIG),
      chunk('IHDR', ihdr),
      chunk('PLTE', plte),
      chunk('IDAT', z),
      chunk('IEND', new Uint8Array(0)),
    ]);
  }

  function bytesToBase64(bytes) {
    let s = '';
    const CH = 0x8000;
    for (let i = 0; i < bytes.length; i += CH) s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
    return btoa(s);
  }

  function base64ToBytes(b64) {
    const s = atob(b64);
    const out = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
    return out;
  }

  const API = { encodeIndexed, bitDepthFor, crc32, adler32, zlibStored, bytesToBase64, base64ToBytes, packScanlines };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  else global.PNGX = API;
})(typeof window !== 'undefined' ? window : globalThis);

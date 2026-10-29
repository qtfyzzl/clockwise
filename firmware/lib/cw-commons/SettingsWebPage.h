#pragma once

#include <Arduino.h>

// 设置页：完全自包含（不依赖任何 CDN），UTF-8 中文。
// 设计约束：
//   1. 设备常常连在没有外网的热点上，任何外部 CSS/字体都会加载失败 → 全部内联
//   2. 页面以 PROGMEM 常量存放在 flash，用 client.println 直接流式发送，不占 RAM
//   3. 与服务端的契约不能变：
//        GET  /get        -> 204 + X-<键>: <值> 响应头
//        POST /set?k=v    -> 204（服务端不做 URL 解码，值必须原样传）
//        POST /restart    -> 204
//        GET  /read?pin=n -> 204 + X-pin: <模拟量>

const char SETTINGS_PAGE[] PROGMEM = R""""(
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Clockwise 设置</title>
<style>
  :root{
    --bg:#eef2f7; --card:#fff; --line:#e3e9f2; --text:#1b2434; --muted:#6b7a90;
    --brand:#1f6feb; --brand-d:#1553b8; --ok:#18a058; --warn:#f0a020;
  }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0}
  body{
    background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei","PingFang SC","Hiragino Sans GB",sans-serif;
    font-size:15px; line-height:1.6; -webkit-font-smoothing:antialiased;
  }
  /* ---------- 顶栏 ---------- */
  header{
    position:sticky; top:0; z-index:20;
    display:flex; align-items:center; gap:14px; flex-wrap:wrap;
    padding:12px 18px;
    background:linear-gradient(120deg,#12457f,#0f7a63);
    color:#fff; box-shadow:0 2px 10px rgba(15,40,80,.18);
  }
  .brand{display:flex; align-items:center; gap:10px; font-size:19px; font-weight:700; letter-spacing:.3px}
  .brand svg{width:28px; height:28px; flex:none}
  .spacer{flex:1}
  .chips{display:flex; gap:8px; flex-wrap:wrap; font-size:12.5px}
  .chip{
    background:rgba(255,255,255,.16); border:1px solid rgba(255,255,255,.22);
    padding:3px 10px; border-radius:999px; white-space:nowrap;
  }
  .chip b{font-weight:600}
  header button{
    background:#fff; color:#12457f; border:0; border-radius:8px;
    padding:8px 14px; font-size:14px; font-weight:600; cursor:pointer;
  }
  header button:hover{background:#eaf1ff}
  header button:active{transform:translateY(1px)}
  /* ---------- 内容 ---------- */
  main{max-width:1080px; margin:0 auto; padding:18px 14px 60px}
  .group{margin:22px 0 10px; display:flex; align-items:baseline; gap:10px}
  .group h2{margin:0; font-size:16px; font-weight:700}
  .group span{font-size:13px; color:var(--muted)}
  .grid{display:grid; grid-template-columns:repeat(auto-fit,minmax(330px,1fr)); gap:14px}
  .card{
    background:var(--card); border:1px solid var(--line); border-radius:12px;
    display:flex; flex-direction:column; overflow:hidden;
    box-shadow:0 1px 3px rgba(20,40,80,.05);
  }
  .card-body{padding:14px 16px 10px; flex:1}
  .card h3{margin:0 0 4px; font-size:15px; font-weight:650}
  .hint{margin:0 0 12px; font-size:13px; color:var(--muted)}
  .hint code{background:#f2f5fa; padding:1px 5px; border-radius:4px; font-size:12.5px}
  .hint a{color:var(--brand); text-decoration:none; border-bottom:1px dashed rgba(31,111,235,.4)}
  .ctl{display:flex; align-items:center; gap:10px; flex-wrap:wrap}
  .card-foot{
    padding:10px 16px 14px; display:flex; align-items:center; justify-content:space-between; gap:10px;
  }
  .val{font-variant-numeric:tabular-nums; font-weight:700; color:var(--brand); min-width:3em; text-align:right}
  /* ---------- 控件 ---------- */
  input[type=text],input[type=number],select{
    width:100%; padding:8px 10px; font-size:14px; color:var(--text);
    background:#f7f9fc; border:1px solid var(--line); border-radius:8px; outline:none;
    font-family:inherit;
  }
  input[type=text]:focus,input[type=number]:focus,select:focus{
    border-color:var(--brand); background:#fff; box-shadow:0 0 0 3px rgba(31,111,235,.12);
  }
  input[type=range]{width:100%; accent-color:var(--brand); height:26px}
  .row2{display:flex; gap:10px; width:100%}
  .row2 > *{flex:1}
  .lbl{font-size:12.5px; color:var(--muted); display:block; margin-bottom:3px}
  /* 开关 */
  .sw{display:flex; align-items:center; gap:10px; cursor:pointer; user-select:none}
  .sw input{position:absolute; opacity:0; width:0; height:0}
  .track{
    width:44px; height:25px; border-radius:999px; background:#cfd8e5; position:relative;
    transition:background .18s; flex:none;
  }
  .track::after{
    content:""; position:absolute; top:3px; left:3px; width:19px; height:19px;
    border-radius:50%; background:#fff; transition:transform .18s; box-shadow:0 1px 2px rgba(0,0,0,.2);
  }
  .sw input:checked + .track{background:var(--ok)}
  .sw input:checked + .track::after{transform:translateX(19px)}
  .sw .txt{font-size:14px}
  /* 按钮 */
  button.primary{
    background:var(--brand); color:#fff; border:0; border-radius:8px;
    padding:7px 16px; font-size:13.5px; font-weight:600; cursor:pointer; white-space:nowrap;
  }
  button.primary:hover{background:var(--brand-d)}
  button.ghost{
    background:#f2f5fa; color:var(--text); border:1px solid var(--line); border-radius:8px;
    padding:6px 12px; font-size:13px; cursor:pointer; white-space:nowrap;
  }
  button.ghost:hover{background:#e8eef8}
  .readout{font-variant-numeric:tabular-nums; font-weight:700; color:var(--warn)}
  /* ---------- 提示 ---------- */
  #toast{
    position:fixed; left:50%; bottom:26px; transform:translate(-50%,20px);
    background:#12203a; color:#fff; padding:10px 18px; border-radius:10px;
    font-size:14px; opacity:0; pointer-events:none; transition:all .22s; z-index:50;
    box-shadow:0 6px 20px rgba(0,0,0,.25);
  }
  #toast.show{opacity:1; transform:translate(-50%,0)}
  #loading{text-align:center; color:var(--muted); padding:60px 0}
  .err{
    max-width:640px; margin:40px auto; background:#fff3f3; border:1px solid #f5c2c2;
    color:#8b1a1a; padding:16px 18px; border-radius:12px; font-size:14px;
  }
  footer{text-align:center; color:var(--muted); font-size:12.5px; padding:0 14px 30px}
  @media (max-width:520px){
    .grid{grid-template-columns:1fr}
    header{padding:10px 12px}
    .brand{font-size:17px}
  }
</style>
</head>
<body>

<header>
  <div class="brand">
    <svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round">
      <circle cx="12" cy="12" r="9.2"/><path d="M12 6.8V12l3.6 2.4"/>
    </svg>
    <span>Clockwise</span>
  </div>
  <div class="spacer"></div>
  <div class="chips">
    <span class="chip" id="chip-fw">固件 —</span>
    <span class="chip" id="chip-ssid">WiFi —</span>
    <span class="chip" id="chip-cf">主题 —</span>
  </div>
  <button onclick="restartDevice()">重启设备</button>
</header>

<main id="app">
  <p id="loading">正在读取设备配置…</p>
</main>

<footer>
  修改后需点右下角「保存」，然后<b>重启设备</b>才会生效。
</footer>

<div id="toast">已保存</div>

<script>
/* ============ 与服务端的契约 ============ */
// 服务端把字符串类参数做了 percent 编码（HTTP 头只允许 latin1，
// 中文直接塞进去浏览器会解成乱码），这里还原。纯 ASCII 值不受影响。
function dec(v){
  try { return decodeURIComponent(v); } catch (e) { return v; }
}

function splitHeaders(req){
  var out = {};
  req.getAllResponseHeaders().trim().split(/[\r\n]+/).forEach(function(line){
    var i = line.indexOf(':');
    if (i < 0) return;
    var k = line.slice(0, i).trim();
    var v = line.slice(i + 1).trim();
    // 服务端发的是 X-<键>，浏览器可能改变大小写 → 统一小写便于查找
    if (k.slice(0,2).toLowerCase() === 'x-') k = k.slice(2);
    out[k.toLowerCase()] = dec(v);
  });
  return out;
}

// ---------------- 请求队列 ----------------
// 设备的 Web 服务是「单连接」的：同一时刻只能处理一个请求。
// 页面里并发发两个请求（比如点主题时先 /set 再 /theme），后一个会排队等待，
// 严重时让 loop() 长时间卡住，表现为「点一下就卡死」。
// 所以所有请求统一进队列，一个一个发。
var __q = [], __busy = false;
var __previewCache = {};   // 主题名 -> 解析后的 JSON，避免重复拉取

function qrun(job){
  __q.push(job);
  if (!__busy) __nextQ();
}

function __nextQ(){
  if (!__q.length) { __busy = false; return; }
  __busy = true;
  var job = __q.shift();
  var done = false;
  var guard = setTimeout(function(){ finish(); }, 15000);   // 单请求最长 15 秒
  function finish(){
    if (done) return;
    done = true;
    clearTimeout(guard);
    setTimeout(__nextQ, 120);   // 给设备一点喘息时间再发下一个
  }
  try { job(finish); } catch (e) { finish(); }
}

function requestGet(path, cb){
  var xhr = new XMLHttpRequest();
  xhr.onreadystatechange = function(){
    if (this.readyState === 2 && this.status === 204) cb(this);
  };
  xhr.open('GET', path, true);
  xhr.send();
}

// 注意：服务端不做 URL 解码，值必须原样拼接（不能 encodeURIComponent）
function setPref(key, value){
  qrun(function(done){
    var xhr = new XMLHttpRequest();
    xhr.onreadystatechange = function(){
      if (this.readyState === 4) { toast(); done(); }
    };
    xhr.open('POST', '/set?' + key + '=' + value, true);
    xhr.send();
  });
}

function toast(msg){
  var t = document.getElementById('toast');
  t.textContent = msg || '已保存，重启后生效';
  t.classList.add('show');
  clearTimeout(t._h);
  t._h = setTimeout(function(){ t.classList.remove('show'); }, 1800);
}

function restartDevice(){
  if (!confirm('确定重启设备？')) return;
  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/restart', true);
  xhr.send();
  toast('正在重启…');
}

function readPin(){
  var pin = document.getElementById('ldrPin').value;
  requestGet('/read?pin=' + pin, function(req){
    var h = splitHeaders(req);
    document.getElementById('ldrRead').textContent = (h['pin'] !== undefined ? h['pin'] : '读取失败');
  });
}
/* ============ 工具 ============ */
function esc(s){
  return String(s === undefined || s === null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
function pad4(v){ return String(v || 0).padStart(4, '0'); }
function fmtBytes(n){
  n = Number(n) || 0;
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1048576).toFixed(2) + ' MB';
}

/* ============ 页面渲染 ============ */
var S = {};   // settings（键统一小写）
var CLOCKFACE = '';

function sw(id, checked, text){
  return '<label class="sw"><input type="checkbox" id="' + id + '"' + (checked ? ' checked' : '') +
         '><span class="track"></span><span class="txt">' + text + '</span></label>';
}
function card(title, hint, control, saveCall){
  return '<section class="card">' +
    '<div class="card-body"><h3>' + title + '</h3>' +
    (hint ? '<p class="hint">' + hint + '</p>' : '') +
    '<div class="ctl">' + control + '</div></div>' +
    '<div class="card-foot"><span></span>' +
    (saveCall ? '<button class="primary" onclick="' + saveCall + '">保存</button>' : '') +
    '</div>' +
    '</section>';
}

// 读取设备闪存里已有的主题列表（/themes 返回纯文本，每行一个名字）
function loadThemes(cb){
  qrun(function(done){
    var xhr = new XMLHttpRequest();
    xhr.onreadystatechange = function(){
      if (this.readyState !== 4) return;
      cb(this.status === 200 ? (this.responseText || '') : '');
      done();
    };
    xhr.open('GET', '/themes', true);
    xhr.send();
  });
}

// 从设备闪存删除当前选中的主题
function deleteTheme(){
  var el = document.getElementById('canvasFile');
  var name = ((el && el.value) || '').trim();
  if (!name) { toast('请先选择一个主题'); return; }
  if (!confirm('从设备删除主题「' + name + '」？\n\n删除后如果它正是当前使用的主题，' +
               '设备重启会找不到主题，需要重新选一个。')) return;

  var xhr = new XMLHttpRequest();
  xhr.onreadystatechange = function(){
    if (this.readyState !== 4) return;
    if (this.status === 204) {
      toast('已删除 ' + name);
      refreshThemes();
    } else {
      toast('删除失败 HTTP ' + this.status);
    }
  };
  xhr.open('POST', '/theme-delete?name=' + name, true);
  xhr.send();
}

// ---------------- 主题预览 ----------------
// 在浏览器里按 Canvas JSON 的 setup 数组画一遍 64×64，用于挑主题。
// 注意：字体是近似值（设备用的是 picopixel/square/big/medium 点阵字体，
// 浏览器里没有），所以预览只保证布局和配色接近，字形不精确。
function rgb565(c){
  c = (Number(c) || 0) & 0xFFFF;
  var r = (c >> 11) & 0x1F, g = (c >> 5) & 0x3F, b = c & 0x1F;
  return 'rgb(' + Math.round(r * 255 / 31) + ',' +
                  Math.round(g * 255 / 63) + ',' +
                  Math.round(b * 255 / 31) + ')';
}

function nowParts(){
  var d = new Date(), H = d.getHours();
  return { H: H, G: (H % 12) || 12, h: (H % 12) || 12, i: d.getMinutes(), s: d.getSeconds(),
           A: H < 12 ? 'AM' : 'PM', a: H < 12 ? 'am' : 'pm' };
}

function fmtPattern(p){
  var t = nowParts(), out = '';
  for (var k = 0; k < p.length; k++){
    var ch = p.charAt(k);
    if (t.hasOwnProperty(ch)){
      var v = t[ch];
      out += (typeof v === 'number' && v < 10) ? ('0' + v) : ('' + v);
    } else {
      out += ch;
    }
  }
  return out;
}

function fontPx(f){
  switch (String(f || '').toLowerCase()){
    case 'big': return 10;
    case 'medium': return 7;
    case 'square': return 5;
    case 'picopixel': return 4;
    default: return 5;
  }
}

function drawEl(el, ctx){
  if (!el || !el.type) return;
  var t = el.type;
  var fg = rgb565(el.fgColor || 0xFFFF);
  var hasBg = (el.bgColor !== undefined && el.bgColor !== 0);
  var bg = hasBg ? rgb565(el.bgColor) : null;

  if (t === 'fillrect'){
    ctx.fillStyle = fg;
    ctx.fillRect(el.x || 0, el.y || 0, el.width || 0, el.height || 0);
    return;
  }
  if (t === 'rect'){
    ctx.strokeStyle = fg; ctx.lineWidth = 1;
    ctx.strokeRect((el.x || 0) + 0.5, (el.y || 0) + 0.5, (el.width || 1) - 1, (el.height || 1) - 1);
    return;
  }
  if (t === 'line'){
    ctx.strokeStyle = fg; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(el.x1 || 0, el.y1 || 0); ctx.lineTo(el.x2 || 0, el.y2 || 0); ctx.stroke();
    return;
  }
  if (t === 'image'){
    if (!el.image) return;
    var img = new Image();
    img.onload = function(){ ctx.drawImage(img, el.x || 0, el.y || 0); };
    img.src = 'data:image/png;base64,' + el.image;
    return;
  }
  if (t === 'text' || t === 'datetime'){
    var txt = (t === 'datetime') ? fmtPattern(el.content || '') : (el.content || '');
    var px = fontPx(el.font);
    ctx.font = px + 'px ui-monospace,Menlo,Consolas,monospace';
    ctx.textBaseline = 'top';
    var w = ctx.measureText(txt).width;
    if (bg){ ctx.fillStyle = bg; ctx.fillRect((el.x || 0) - 1, el.y || 0, w + 2, px + 2); }
    ctx.fillStyle = fg;
    ctx.fillText(txt, el.x || 0, el.y || 0);
    return;
  }
  if (t === 'sprite'){
    // 动画预览只画一个淡色方块示意位置
    ctx.fillStyle = 'rgba(255,255,255,0.22)';
    ctx.fillRect(el.x || 0, el.y || 0, 7, 7);
  }
}

function previewTheme(name){
  var cv = document.getElementById('prev');
  if (!cv) return;
  var ctx = cv.getContext('2d');
  var info = document.getElementById('prevInfo');
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, 64, 64);

  name = (name || '').trim();
  if (!name){ if (info) info.textContent = '未选择主题'; return; }

  // 画一帧：背景 + setup 里的元素
  function paint(spec){
    ctx.fillStyle = rgb565(spec.bgColor || 0);
    ctx.fillRect(0, 0, 64, 64);
    (spec.setup || []).forEach(function(el){ drawEl(el, ctx); });

    var nsp = (spec.sprites || []).length;
    var nloop = (spec.loop || []).length;
    if (info) {
      info.innerHTML = '<b>' + esc(spec.name || name) + '</b>' +
        '<br>版本 ' + esc(spec.version || '?') + ' · 作者 ' + esc(spec.author || '?') +
        '<br>' + (spec.setup || []).length + ' 个静态元素 · ' + nsp + ' 组精灵 · ' + nloop + ' 个动画';
    }
  }

  // 同一个主题不重复拉，切来切去很快
  if (__previewCache[name]) { paint(__previewCache[name]); return; }

  if (info) info.textContent = '预览加载中…';
  qrun(function(done){
    var xhr = new XMLHttpRequest();
    xhr.onreadystatechange = function(){
      if (this.readyState !== 4) return;
      if (this.status !== 200){
        if (info) info.textContent = '无法预览（HTTP ' + this.status + '）';
        done(); return;
      }
      var spec;
      try { spec = JSON.parse(this.responseText); }
      catch (e) { if (info) info.textContent = 'JSON 解析失败'; done(); return; }
      __previewCache[name] = spec;
      paint(spec);
      done();
    };
    xhr.open('GET', '/theme?name=' + name, true);
    xhr.send();
  });
}

// 立即切到下一个本地主题（设备会重启）
function rotateNow(){  var xhr = new XMLHttpRequest();
  xhr.onreadystatechange = function(){
    if (this.readyState === 4) toast('正在切换到下一个主题…');
  };
  xhr.open('POST', '/rotate', true);
  xhr.send();
}

function pickTheme(name){
  if (!name) return;
  document.getElementById('canvasFile').value = name;
  setPref('canvasFile', name);
  previewTheme(name);
  toast('已选择「' + name + '」，重启后生效');
}

// 存储（SPIFFS）状态：挂载失败时主题存不进去，要把原因讲清楚，
// 而不是让用户对着"上传失败"发呆。挂载失败不会自动格式化，
// 必须用户显式点「格式化存储」。
function fsStateText(){
  if (S['fsready'] !== '1') {
    return '<span style="color:#c0392b">存储未就绪</span>：分区挂载失败，主题无法保存。' +
           '点「格式化存储」可重建（会清空已有主题）。';
  }
  var used = parseInt(S['fsused'] || '0', 10);
  var total = parseInt(S['fstotal'] || '0', 10);
  if (!total) return '';
  var kb = function(n){ return (n / 1024).toFixed(0) + ' KB'; };
  return '存储正常：已用 ' + kb(used) + ' / ' + kb(total) +
         '（' + Math.round(used * 100 / total) + '%）';
}

function formatStorage(){
  if (!confirm('格式化会删除设备上所有主题，确定继续？')) return;
  if (!confirm('再确认一次：主题将全部丢失，需要重新上传。')) return;
  qrun(function(done){
    var xhr = new XMLHttpRequest();
    xhr.onreadystatechange = function(){
      if (this.readyState === 4) { done(); toast('格式化中，设备即将重启'); }
    };
    xhr.open('POST', '/fs-format', true);
    xhr.send();
  });
}

// 渲染引擎列表（数据来自 /engines，每行 "id|显示名"）
function renderEngineList(){
  var box = document.getElementById('engineList');
  if (!box) return;
  requestGet('/engines', function(req){
    var txt = (req && req.responseText) || '';
    var cur = (S['clockfaceengine'] || 'canvas');
    var lines = txt.split(/\r?\n/).map(function(s){ return s.trim(); })
                   .filter(function(s){ return s.length; });
    if (!lines.length) {
      box.innerHTML = '<span class="hint">固件没有报告任何引擎</span>';
      return;
    }
    box.innerHTML = lines.map(function(line){
      var p = line.split('|');
      var id = p[0], nm = p[1] || p[0];
      var on = (id === cur);
      return '<button class="' + (on ? 'primary' : 'ghost') + '"' +
             (on ? '' : ' onclick="pickEngine(\'' + id + '\')"') + '>' +
             esc(nm) + (on ? ' · 使用中' : '') + '</button>';
    }).join('');
  });
}

// 切换主题引擎（写 NVS，重启生效）
function pickEngine(id){
  if (id === (S['clockfaceengine'] || 'canvas')) return;
  if (!confirm('切换到「' + id + '」需要重启设备，确定？')) return;
  setPref('clockfaceEngine', id);
  setTimeout(function(){
    if (confirm('已切换，现在重启生效？')) restartDevice();
  }, 700);
}

// 上传固件并升级。
// 特意不走 qrun 队列：队列给单个请求设了 15 秒超时，而 1.6MB 固件要传几十秒，
// 走队列会被提前判定超时并放行下一个请求，两个请求撞在单连接服务上。
function uploadFirmware(){
  var input = document.getElementById('fwFile');
  var prog  = document.getElementById('fwProg');
  var file  = input && input.files && input.files[0];

  if (!file) { toast('先选一个 .bin 固件文件'); return; }
  if (file.size < 100000) { toast('文件太小，不像固件'); return; }

  var kb = Math.round(file.size / 1024);
  if (!confirm('上传并升级固件？\n\n' + file.name + '（' + kb + ' KB）\n' +
               '约需 1 分钟，期间不要断电。')) return;

  if (prog) prog.textContent = '准备上传…';
  var xhr = new XMLHttpRequest();

  xhr.upload.onprogress = function(e){
    if (e.lengthComputable && prog) {
      var pct = Math.round(e.loaded * 100 / e.total);
      prog.textContent = '上传中 ' + pct + '%（' + Math.round(e.loaded/1024) + ' / ' + kb + ' KB）';
    }
  };

  xhr.onreadystatechange = function(){
    if (this.readyState !== 4) return;
    if (this.status === 200) {
      if (prog) prog.textContent = '升级成功，设备重启中…等 20 秒后刷新页面';
      toast('升级成功，等待重启');
    } else {
      if (prog) prog.textContent = '升级失败：HTTP ' + this.status + '（设备未重启，可重试）';
      toast('升级失败');
    }
  };

  xhr.open('POST', '/update', true);
  xhr.send(file);
}

function refreshThemes(){
  var sel = document.getElementById('themeList');
  if (!sel) return;
  sel.innerHTML = '<option value="">读取中…</option>';
  loadThemes(function(txt){
    var names = txt.split(/\r?\n/).map(function(s){ return s.trim(); })
                   .filter(function(s){ return s.length; });
    var curEl = document.getElementById('canvasFile');
    var cur = curEl ? (curEl.value || '').trim() : '';
    if (!names.length) {
      sel.innerHTML = '<option value="">（设备上还没有本地主题）</option>';
      return;
    }
    sel.innerHTML = names.map(function(n){
      return '<option value="' + esc(n) + '"' + (n === cur ? ' selected' : '') + '>' +
             esc(n) + '</option>';
    }).join('');
    // 当前选中的主题不在列表里（比如只存在于远程），补一项并标注
    if (cur && names.indexOf(cur) < 0) {
      sel.insertAdjacentHTML('afterbegin',
        '<option value="' + esc(cur) + '" selected>' + esc(cur) + '（远程/未存储）</option>');
    }
  });
}

// 上传主题 JSON 到设备 SPIFFS。
// 注意：服务端不做 URL 解码，文件名只允许字母数字下划线中划线，避免特殊字符。
function uploadTheme(input){
  var file = input.files && input.files[0];
  if (!file) return;
  var status = document.getElementById('upStatus');
  var nameEl = document.getElementById('canvasFile');
  var name = (nameEl.value || file.name.replace(/\.json$/i, '')).trim();

  if (!/^[A-Za-z0-9_-]{1,40}$/.test(name)) {
    status.textContent = '主题名只能是字母/数字/_/-，且不超过 40 字符';
    status.style.color = '#c0392b';
    return;
  }
  nameEl.value = name;

  var reader = new FileReader();
  reader.onload = function(){
    var text = reader.result;
    status.style.color = '';
    status.textContent = '上传中… ' + text.length + ' 字节';
    var xhr = new XMLHttpRequest();
    xhr.onreadystatechange = function(){
      if (this.readyState !== 4) return;
      if (this.status === 204) {
        status.textContent = '已保存到设备（' + text.length + ' 字节），重启后生效';
        toast('上传成功，重启后生效');
        refreshThemes();
      } else {
        status.style.color = '#c0392b';
        status.textContent = '上传失败 HTTP ' + this.status + '（文件过大或连接中断）';
      }
    };
    xhr.open('POST', '/theme?name=' + name, true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.send(text);
  };
  reader.readAsText(file);
}

function render(){
  var bright   = S['displaybright'] || '32';
  var use24    = S['use24hformat'] === '1';
  var ldrPin   = S['ldrpin'] || '35';
  var abMin    = S['autobrightmin'] || '0';
  var abMax    = S['autobrightmax'] || '0';
  var rot      = S['displayrotation'] || '0';
  var spd      = S['i2cspeed'] || '8000000';
  CLOCKFACE    = S['clockface_name'] || '';

  // 顶栏信息
  document.getElementById('chip-fw').innerHTML   = '固件 <b>' + esc(S['cw_fw_version'] || '—') + '</b>';
  document.getElementById('chip-ssid').innerHTML = 'WiFi <b>' + esc(S['wifissid'] || '未连接') + '</b>';
  // 顶栏显示"当前实际在用的主题"：Canvas 引擎下是 canvasFile，其它引擎直接显示引擎名
  var engineNow = (S['clockfaceengine'] || 'canvas');
  var themeLabel = (CLOCKFACE === 'cw-cf-0x07')
      ? (S['canvasfile'] || '未选择')
      : (engineNow === 'native-mario' ? 'Mario（原生）' : (CLOCKFACE || '—'));
  document.getElementById('chip-cf').innerHTML   = '主题 <b>' + esc(themeLabel) + '</b>';

  var html = '';

  /* ---------- 显示 ---------- */
  html += '<div class="group"><h2>显示</h2><span>亮度、自动亮度、屏幕方向、刷新率</span></div><div class="grid">';

  html += card('屏幕亮度',
    '范围 0–255。<code>0</code> 等于关屏，<code>255</code> 最亮。亮度越高耗电越大，电源不足时会出现闪烁。',
    '<input type="range" id="bright" min="0" max="255" value="' + esc(bright) + '" ' +
    'oninput="document.getElementById(\'brightVal\').textContent=this.value">' +
    '<span class="val" id="brightVal">' + esc(bright) + '</span>',
    "setPref('displayBright', document.getElementById('bright').value)");

  html += card('自动亮度（光敏电阻）',
    '让屏幕亮度跟着房间走：<b>房间越暗屏幕越暗，越亮屏幕越亮</b>。' +
    '填入房间<b>全暗</b>与<b>全亮</b>时 LDR 的读数（0–4095），中间自动线性过渡。' +
    '<b>最大值填 0 = 关闭该功能</b>；读数低于最小值时熄屏（夜里自动关屏）。' +
    '不确定填多少就点下面「读取当前值」，开灯关灯各看一次。',
    '<div class="row2">' +
      '<div><span class="lbl">最小值（暗）</span><input type="number" id="abMin" min="0" max="4095" value="' + esc(abMin) + '"></div>' +
      '<div><span class="lbl">最大值（亮）</span><input type="number" id="abMax" min="0" max="4095" value="' + esc(abMax) + '"></div>' +
    '</div>',
    "setPref('autoBright', pad4(document.getElementById('abMin').value) + ',' + pad4(document.getElementById('abMax').value))");

  html += card('光敏电阻引脚（LDR Pin）',
    'LDR 接在哪个 GPIO 上（默认 <code>35</code>）。可以点「读取」看当前实时光照值，用来标定上面两个阈值。',
    '<div class="row2">' +
      '<input type="number" id="ldrPin" min="0" max="39" value="' + esc(ldrPin) + '">' +
      '<button class="ghost" onclick="readPin()">读取当前值</button>' +
    '</div><span class="readout" id="ldrRead">—</span>',
    "setPref('ldrPin', document.getElementById('ldrPin').value)");

  html += card('屏幕方向',
    '点阵屏的安装方向。装反了就改成 180°，横竖构图不同就选 90°/270°。',
    '<select id="rotation">' +
      ['0|0°（默认）','1|90°','2|180°','3|270°'].map(function(o){
        var p = o.split('|');
        return '<option value="' + p[0] + '"' + (rot === p[0] ? ' selected' : '') + '>' + p[1] + '</option>';
      }).join('') +
    '</select>',
    "setPref('displayRotation', document.getElementById('rotation').value)");

  html += card('I2S 时钟速度（刷新率）',
    '面板的扫描速率。<code>8 MHz</code> 最稳；<code>16/20 MHz</code> 画面更流畅，' +
    '但对线材和面板要求高，出现闪屏就退回 8 MHz。',
    '<select id="speed">' +
      [['8000000','8 MHz（默认）'],['16000000','16 MHz'],['20000000','20 MHz']]
      .map(function(o){ return '<option value="' + o[0] + '"' + (spd === o[0] ? ' selected' : '') + '>' + o[1] + '</option>'; })
      .join('') +
    '</select>',
    "setPref('i2cSpeed', document.getElementById('speed').value)");

  html += '</div>';

  /* ---------- 时间 ---------- */
  html += '<div class="group"><h2>时间</h2><span>时区、对时、显示格式</span></div><div class="grid">';

  html += card('24 小时制',
    '开启后显示 <code>20:00</code>，关闭则显示 <code>8:00 PM</code>。',
    sw('use24', use24, use24 ? '已开启（24 小时制）' : '已关闭（12 小时制）'),
    "setPref('use24hFormat', document.getElementById('use24').checked ? 1 : 0)");

  html += card('时区',
    '填 tz database 名称，国内用 <code>Asia/Shanghai</code>。' +
    '完整列表见 <a href="https://en.wikipedia.org/wiki/List_of_tz_database_time_zones" target="_blank">TZ 列表</a>。',
    '<input type="text" id="tz" value="' + esc(S['timezone'] || '') + '" placeholder="Asia/Shanghai">',
    "setPref('timeZone', document.getElementById('tz').value)");

  html += card('NTP 服务器',
    '网络对时用的服务器。国内可用 <code>ntp.aliyun.com</code> 或 <code>cn.pool.ntp.org</code>，' +
    '默认 <code>time.google.com</code> 在国内常被墙。',
    '<input type="text" id="ntp" value="' + esc(S['ntpserver'] || '') + '" placeholder="ntp.aliyun.com">',
    "setPref('ntpServer', document.getElementById('ntp').value)");

  html += card('手动 POSIX 时区串（可选）',
    '留空则自动从网络查询。断网也想正确走时的话，填 POSIX 串，例如 <code>CST-8</code>。' +
    '<a href="https://github.com/nayarsystems/posix_tz_db/blob/master/zones.csv" target="_blank">对照表</a>',
    '<input type="text" id="posix" value="' + esc(S['manualposix'] || '') + '" placeholder="留空 = 自动">',
    "setPref('manualPosix', document.getElementById('posix').value)");

  html += '</div>';

  /* ---------- 主题引擎（始终显示，决定下面显示哪一组） ---------- */
  html += '<div class="group"><h2>主题引擎</h2><span>决定用哪种方式渲染画面，切换后重启生效</span></div><div class="grid">';

  html += card('渲染方式',
    '下面列出这个固件里内置的全部引擎，点一个即切换。<br>' +
    '<b>画布模式</b>：运行时解析闪存里的 JSON 主题，可以上传任意主题，' +
    '但受 16KB 缓冲和堆限制。<br>' +
    '<b>原生模式</b>：图片编译进 Flash，运行时几乎不占内存、动画更流畅，' +
    '但只能选固件内置的那些。',
    '<div id="engineList" style="display:flex;gap:8px;flex-wrap:wrap">' +
      '<span class="hint">读取中…</span></div>',
    null);

  html += '</div>';

  /* ---------- Canvas 主题（仅 cw-cf-0x07） ---------- */
  if (CLOCKFACE === 'cw-cf-0x07') {
    html += '<div class="group"><h2>Canvas 主题</h2><span>仅当前使用 Canvas 主题时生效</span></div><div class="grid">';

    html += card('主题服务器地址',
      '存放主题 JSON 的服务器。<b>填 <code>raw.</code> 开头会自动指向官方 clock-club 仓库</b>；' +
      '填局域网 IP 则从本地 HTTPS 4443 端口读取。',
      '<input type="text" id="canvasServer" value="' + esc(S['canvasserver'] || '') + '" placeholder="192.168.1.20">',
      "setPref('canvasServer', document.getElementById('canvasServer').value)");

    html += card('主题描述文件',
      '当前使用的主题名（<b>不带 .json</b>）。设备先找本地闪存，找不到才去上面的服务器拉。' +
      '下面的下拉列表是从设备闪存里读出来的。',
      '<input type="text" id="canvasFile" value="' + esc(S['canvasfile'] || '') + '" placeholder="my-theme">' +
      '<select id="themeList" onchange="pickTheme(this.value)" style="margin-top:8px">' +
      '<option value="">读取中…</option></select>' +
      '<div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">' +
        '<button class="ghost" onclick="refreshThemes()">刷新列表</button>' +
        '<button class="ghost" style="color:#c0392b" onclick="deleteTheme()">删除当前主题</button>' +
        '<button class="ghost" style="color:#c0392b" onclick="formatStorage()">格式化存储</button>' +
      '</div>' +
      '<div class="hint" id="fsState" style="margin-top:6px">' + fsStateText() + '</div>' +
      '<div style="display:flex;gap:12px;align-items:flex-start;margin-top:12px">' +
        '<canvas id="prev" width="64" height="64" ' +
        'style="width:128px;height:128px;flex:none;image-rendering:pixelated;' +
        'border:1px solid #d8e2f0;border-radius:8px;background:#000"></canvas>' +
        '<div class="hint" id="prevInfo" style="margin:0">选择主题后显示预览</div>' +
      '</div>',
      "setPref('canvasFile', document.getElementById('canvasFile').value)");

    html += card('上传主题到设备',
      '把 <code>.json</code> 主题文件直接存进设备闪存（约 896KB 可用）。' +
      '<b>上传后设备不再依赖网络或电脑</b>，重启即生效。' +
      '文件名取上面「主题描述文件」里填的名字。',
      '<input type="file" id="themeFile" accept=".json,application/json" ' +
      'onchange="uploadTheme(this)" ' +
      'style="width:100%;font-size:13px;padding:6px;background:#f7f9fc;border:1px dashed #c8d4e4;border-radius:8px">' +
      '<div class="hint" id="upStatus" style="margin:8px 0 0">选择 .json 文件即可上传</div>',
      null);

    // 存储占用
    var fsUsed = parseInt(S['fsused'] || '0', 10) || 0;
    var fsTotal = parseInt(S['fstotal'] || '0', 10) || 0;
    var pct = fsTotal ? Math.min(100, fsUsed * 100 / fsTotal) : 0;
    var avgTheme = 3200;   // pac-man 约 2.8KB，取 3.2KB 作估算基准
    var room = fsTotal ? Math.max(0, Math.floor((fsTotal - fsUsed) / avgTheme)) : 0;

    html += card('闪存占用',
      '本地主题存在设备闪存里。按每个主题约 3KB 估算，当前还能再放 <b>约 ' + room + ' 个</b>。',
      '<div style="width:100%">' +
        '<div style="height:10px;border-radius:6px;background:#e6edf7;overflow:hidden">' +
          '<div style="height:100%;width:' + pct.toFixed(1) + '%;background:linear-gradient(90deg,#3fa9f5,#1f6feb)"></div>' +
        '</div>' +
        '<div style="display:flex;justify-content:space-between;margin-top:6px;font-size:12.5px;color:#6b7a90">' +
          '<span>已用 <b style="color:#1f6feb">' + fmtBytes(fsUsed) + '</b></span>' +
          '<span>共 ' + fmtBytes(fsTotal) + ' · ' + pct.toFixed(1) + '%</span>' +
        '</div>' +
      '</div>',
      null);

    // 自动更换表盘
    var rot = (S['autorotate'] === '1');
    html += card('自动更换表盘',
      '每天 <b>00:00</b> 自动切到下一个本地主题（按名字字母序循环）。' +
      '设备上至少要有两个本地主题才会生效。切换后会重启一次。',
      '<select id="autoRotate">' +
        '<option value="0"' + (!rot ? ' selected' : '') + '>不自动切换</option>' +
        '<option value="1"' + (rot ? ' selected' : '') + '>每天 0 点自动切换</option>' +
      '</select>' +
      '<button class="ghost" style="margin-top:8px" onclick="rotateNow()">立即切到下一个</button>',
      "setPref('autoRotate', document.getElementById('autoRotate').value)");

    html += '</div>';
  }

  /* ---------- 固件升级（始终显示） ---------- */
  html += '<div class="group"><h2>固件升级</h2><span>不用再按 BOOT 键，网页直接刷</span></div><div class="grid">';

  html += card('OTA 空中升级',
    '当前固件 <b>' + esc(S['cw_fw_version'] || '?') + '</b>。选择 <code>.bin</code> 文件上传，' +
    '设备会写进备用分区再切换启动，<b>升级失败会自动回退</b>，不会变砖。<br>' +
    '传完会自动重启，期间<b>不要断电</b>。1.6MB 约需 1 分钟（取决于 WiFi 速度）。',
    '<input type="file" id="fwFile" accept=".bin">' +
    '<button class="ghost" style="margin-top:8px" onclick="uploadFirmware()">上传并升级</button>' +
    '<div class="hint" id="fwProg" style="margin-top:6px"></div>',
    null);

  html += '</div>';

  document.getElementById('app').innerHTML = html;
  // Canvas 组渲染完再异步拉主题列表（只有 cw-cf-0x07 才有这个元素）
  if (document.getElementById('themeList')) {
    refreshThemes();
    previewTheme(S['canvasfile'] || '');
  }
  renderEngineList();
}

/* ============ 启动 ============ */
requestGet('/get', function(req){
  S = splitHeaders(req);
  try {
    render();
  } catch (e) {
    document.getElementById('app').innerHTML =
      '<div class="err"><b>页面渲染失败</b><br>' + esc(e.message) + '</div>';
  }
});

// 3 秒还没拿到配置就提示（通常是没连上设备）
setTimeout(function(){
  if (document.getElementById('loading')) {
    document.getElementById('app').innerHTML =
      '<div class="err"><b>读取配置超时</b><br>' +
      '请确认浏览器与时钟在同一网络，然后刷新页面。<br>' +
      '如果一直这样，按一下设备的重启键再试。</div>';
  }
}, 3000);
</script>
</body>
</html>
)"""";

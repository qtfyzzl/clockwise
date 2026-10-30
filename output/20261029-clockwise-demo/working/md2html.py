#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 stage1 的 Markdown 转成符合 S3 转换契约的 HTML。

按 doc-formatter §2.5 的硬要求：
  · 正文 SimSun / 12pt / text-indent:2em
  · 章节标题用 h1~h3（不能只用 class，否则目录收录不到）
  · 封面标题禁用 h1~h6（否则被 TOC 收录成第一条）
  · nav.doc-toc 独占一个 section[role=cover]
  · 正文 section 带 data-page-restart="1"
  · CSS 注释里禁止出现 @page 字样（会干扰解析器，导致页眉丢失）
  · 单个完整 HTML 文件，UTF-8 无 BOM
"""
import re
import sys
import os

SRC = sys.argv[1]
DST = sys.argv[2]

md = open(SRC, encoding='utf-8').read()
lines = md.splitlines()

# ---------------- 解析 ----------------
blocks = []          # (kind, payload)
i = 0
while i < len(lines):
    ln = lines[i]
    s = ln.strip()

    if not s:
        i += 1
        continue

    # 标题
    m = re.match(r'^(#{1,3})\s+(.*)$', ln)
    if m:
        level = len(m.group(1))
        blocks.append(('h%d' % level, m.group(2).strip()))
        i += 1
        continue

    # 表格：当前行以 | 开头且下一行是分隔行
    if s.startswith('|') and i + 1 < len(lines) and re.match(r'^\|[\s:|-]+\|$', lines[i+1].strip()):
        header = [c.strip() for c in s.strip('|').split('|')]
        i += 2
        rows = []
        while i < len(lines) and lines[i].strip().startswith('|'):
            rows.append([c.strip() for c in lines[i].strip().strip('|').split('|')])
            i += 1
        blocks.append(('table', (header, rows)))
        continue

    # 无序列表
    if re.match(r'^[-*]\s+', s):
        items = []
        while i < len(lines) and re.match(r'^[-*]\s+', lines[i].strip()):
            items.append(re.sub(r'^[-*]\s+', '', lines[i].strip()))
            i += 1
        blocks.append(('ul', items))
        continue

    # 有序列表
    if re.match(r'^\d+\.\s+', s):
        items = []
        while i < len(lines) and re.match(r'^\d+\.\s+', lines[i].strip()):
            items.append(re.sub(r'^\d+\.\s+', '', lines[i].strip()))
            i += 1
        blocks.append(('ol', items))
        continue

    # 段落（连续非空行合并）
    para = [s]
    i += 1
    while i < len(lines) and lines[i].strip() and not re.match(r'^(#{1,3}\s|\||[-*]\s|\d+\.\s)', lines[i].strip()):
        para.append(lines[i].strip())
        i += 1
    blocks.append(('p', ' '.join(para)))


def inline(t):
    """行内标记：**粗**、`代码`"""
    t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
    t = re.sub(r'`([^`]+)`', r'<code>\1</code>', t)
    return t


# ---------------- 组装 ----------------
title = blocks[0][1] if blocks[0][0] == 'h1' else '功能演示'
body_blocks = [b for b in blocks if b[0] != 'h1']

# 收集章节与目录条目
sections = []
sec_no = 0
toc = []
for kind, payload in body_blocks:
    if kind == 'h2':
        sec_no += 1
        sections.append((sec_no, payload, []))
        toc.append((sec_no, payload, 'h2'))
    elif kind == 'h3' and sections:
        sections[-1][2].append(payload)
        toc.append((sec_no, payload, 'h3'))

# TOC HTML
toc_html = []
last_sec = None
for no, text, lvl in toc:
    if lvl == 'h2':
        if last_sec is not None:
            toc_html.append('</li>')
        toc_html.append(f'<li><a href="#section-{no}">{text}</a>')
        last_sec = no
    else:
        if not toc_html or not toc_html[-1].endswith('</li>'):
            pass
        # 二级条目：塞进上一个 li 的嵌套 ol
        if toc_html and toc_html[-1] == '</li>':
            toc_html.pop()
        if toc_html:
            toc_html[-1] += f'<ol class="toc-sub"><li><a href="#sub-{no}-{abs(hash(text)) % 1000}">{text}</a></li></ol>'
if last_sec is not None:
    toc_html.append('</li>')
toc_inner = '\n'.join(toc_html)

# 正文 HTML
body_html = []
sec_idx = 0
for kind, payload in body_blocks:
    if kind == 'h2':
        sec_idx += 1
        body_html.append(f'<h1 class="section-header" id="section-{sec_idx}">{inline(payload)}</h1>')
    elif kind == 'h3':
        body_html.append(f'<h2 class="subsection">{inline(payload)}</h2>')
    elif kind == 'p':
        body_html.append(f'<p class="body-text">{inline(payload)}</p>')
    elif kind == 'table':
        header, rows = payload
        th = ''.join(f'<th>{inline(c)}</th>' for c in header)
        trs = ''.join('<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in r) + '</tr>' for r in rows)
        body_html.append(f'<table class="data-table"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>')
    elif kind == 'ul':
        lis = ''.join(f'<li>{inline(x)}</li>' for x in payload)
        body_html.append(f'<ul class="bullet-list">{lis}</ul>')
    elif kind == 'ol':
        lis = ''.join(f'<li>{inline(x)}</li>' for x in payload)
        body_html.append(f'<ol class="num-list">{lis}</ol>')

subtitle = ''
for kind, payload in body_blocks[:2]:
    if kind == 'p':
        subtitle = payload
        break

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="docx-page-size" content="A4">
<title>{title}</title>
<style>
/* 页面规则：正文页脚居中显示页码；封面与目录页不显示 */
@page {{
  @bottom-center {{ content: "第 " counter(page) " 页"; }}
}}
@page cover {{
  @bottom-center {{ content: none; }}
}}
section[role="cover"] {{ page: cover; }}

* {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: "SimSun", "宋体", serif;
  font-size: 12pt;
  line-height: 1.75;
  color: #1a1a1a;
  background: #ffffff;
}}

/* ---------- 封面 ---------- */
.cover {{
  padding: 3.2cm 2.5cm;
  min-height: 22cm;
  display: flex;
  flex-direction: column;
  justify-content: center;
}}
.cover-category {{
  font-family: "SimHei", "黑体", sans-serif;
  font-size: 12pt;
  letter-spacing: 0.35em;
  color: #1a73e8;
  margin-bottom: 1.4em;
}}
.cover-title {{
  font-family: "SimHei", "黑体", sans-serif;
  font-size: 30pt;
  font-weight: bold;
  line-height: 1.35;
  color: #0f2b46;
  margin-bottom: 0.7em;
}}
.cover-subtitle {{
  font-size: 13pt;
  line-height: 1.9;
  color: #4a5568;
  margin-bottom: 3em;
  max-width: 14cm;
}}
.cover-rule {{
  width: 2.6cm;
  height: 3px;
  background: #1a73e8;
  margin-bottom: 1.6em;
}}
.cover-meta {{
  font-size: 10.5pt;
  color: #718096;
  line-height: 2;
}}

/* ---------- 目录 ---------- */
.toc-wrap {{ padding: 2.4cm 2.5cm; }}
.toc-title {{
  font-family: "SimHei", "黑体", sans-serif;
  font-size: 18pt;
  font-weight: bold;
  color: #0f2b46;
  margin-bottom: 1.2em;
  padding-bottom: 0.5em;
  border-bottom: 2px solid #1a73e8;
}}
.toc-list, .toc-list ol, .toc-list ul {{ list-style: none; }}
.toc-list > li {{ margin: 0.55em 0; text-indent: 0; }}
.toc-list > li > a {{
  font-family: "SimHei", "黑体", sans-serif;
  font-size: 11.5pt;
  color: #0f2b46;
  text-decoration: none;
}}
.toc-sub {{ margin: 0.22em 0 0.35em 1.6em; }}
.toc-sub li {{ margin: 0.2em 0; text-indent: 0; }}
.toc-sub a {{ font-size: 10.5pt; color: #5a6b7f; text-decoration: none; }}

/* ---------- 正文 ---------- */
.report-body {{ padding: 1.6cm 2.5cm 2.2cm; }}
section[role="cover"]::after,
.report-body {{ page-break-before: always; }}

h1.section-header {{
  font-family: "SimHei", "黑体", sans-serif;
  font-size: 17pt;
  font-weight: bold;
  color: #0f2b46;
  margin: 1.9em 0 0.85em;
  padding: 0 0 0.42em 0;
  border-bottom: 2px solid #1a73e8;
  text-indent: 0;
}}
.report-body > h1.section-header:first-of-type {{ margin-top: 0.2em; }}

h2.subsection {{
  font-family: "SimHei", "黑体", sans-serif;
  font-size: 13pt;
  font-weight: bold;
  color: #1a73e8;
  margin: 1.35em 0 0.55em;
  text-indent: 0;
}}

p.body-text {{
  font-family: "SimSun", "宋体", serif;
  font-size: 12pt;
  line-height: 1.85;
  text-indent: 2em;
  margin-bottom: 0.72em;
  text-align: justify;
}}

ul.bullet-list, ol.num-list {{
  margin: 0.55em 0 0.9em 0;
  padding-left: 2.6em;
}}
ul.bullet-list li, ol.num-list li {{
  font-family: "SimSun", "宋体", serif;
  font-size: 12pt;
  line-height: 1.8;
  margin-bottom: 0.32em;
  text-indent: 0;
}}

table.data-table {{
  width: 100%;
  border-collapse: collapse;
  margin: 0.85em 0 1.15em;
  font-family: "SimSun", "宋体", serif;
  font-size: 10.5pt;
}}
table.data-table th {{
  background: #eef3fa;
  font-family: "SimHei", "黑体", sans-serif;
  font-size: 10.5pt;
  font-weight: bold;
  color: #0f2b46;
  padding: 0.5em 0.7em;
  border: 1px solid #c9d6e5;
  text-align: left;
}}
table.data-table td {{
  padding: 0.45em 0.7em;
  border: 1px solid #dbe4ee;
  line-height: 1.6;
}}
table.data-table tbody tr:nth-child(even) {{ background: #fafcfe; }}

code {{
  font-family: "Consolas", monospace;
  font-size: 10.5pt;
  background: #f1f4f8;
  padding: 0.05em 0.3em;
  border-radius: 2px;
}}
strong {{ font-weight: bold; color: #0f2b46; }}
</style>
</head>
<body>

<!-- 封面 -->
<section role="cover" class="cover">
  <p class="cover-category">项目功能演示</p>
  <p class="cover-title">{title}</p>
  <div class="cover-rule"></div>
  <p class="cover-subtitle">双主题引擎 · 空中升级 · 离线兜底<br>ESP32 驱动 64×64 全彩点阵面板</p>
  <div class="cover-meta">
    <p>Clockwise 开源智能挂钟项目</p>
    <p>2026 年 10 月</p>
  </div>
</section>

<!-- 目录（独占一节，目录页无页眉页脚） -->
<section role="cover">
  <div class="toc-wrap">
    <p class="toc-title">目 录</p>
    <ol class="toc-list">
{toc_inner}
    </ol>
  </div>
</section>

<!-- 正文 -->
<section role="body" class="report-body" data-page-restart="1">
{chr(10).join(body_html)}
</section>

</body>
</html>
'''

os.makedirs(os.path.dirname(DST), exist_ok=True)
with open(DST, 'w', encoding='utf-8', newline='\n') as f:
    f.write(html)

print(f"HTML 已生成: {DST}")
print(f"  大小 {len(html)} 字节")
print(f"  章节 {sec_no} 个, 表格 {sum(1 for b in body_blocks if b[0]=='table')} 个, 目录条目 {len(toc)} 条")

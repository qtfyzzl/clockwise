#!/usr/bin/env python3
"""
Canvas 主题本地调试服务器（Clockwise cw-cf-0x07 用）

固件侧的取文件逻辑（见 clockfaces/cw-cf-0x07/Clockface.cpp:297-338）：

    WiFiClientSecure client;
    client->setInsecure();          // 不校验证书 -> 自签名可用
    GET /<canvasFile>.json HTTP/1.1
    Host: <canvasServer>
    端口：默认 4443；若 canvasServer 以 "raw." 开头则强制 443
         并把路径改写成 /robegamesios/clock-club/main/shared/<file>.json

也就是说：**固件只讲 HTTPS**，而且默认端口是 4443。所以本地调试必须起一个
HTTPS 服务监听 4443，并且 canvasServer 填本机局域网 IP（不能填 raw.xxx，
否则路径会被改写）。

用法：
    python canvas/serve-https.py                 # 默认服务本目录，端口 4443
    python canvas/serve-https.py --port 4443 --dir canvas

首次运行会用 openssl 生成自签名证书（cert.pem / key.pem，仅本地调试用）。
"""

import argparse
import http.server
import os
import socket
import ssl
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def ensure_cert(cert: str, key: str) -> None:
    if os.path.isfile(cert) and os.path.isfile(key):
        return
    if not shutil_which("openssl"):
        print("未找到 openssl，无法生成自签名证书。")
        print("可选方案：手动提供 --cert / --key，或用 mkcert 生成。")
        sys.exit(1)
    print("生成自签名证书（仅用于本地调试）...")
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", key, "-out", cert, "-days", "365",
            "-subj", "/CN=clockwise.local",
            "-addext", "subjectAltName=DNS:clockwise.local,IP:127.0.0.1",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def shutil_which(cmd):
    from shutil import which
    return which(cmd)


def _is_private(ip: str) -> bool:
    try:
        a, b = (int(x) for x in ip.split(".")[:2])
    except (ValueError, IndexError):
        return False
    return a == 10 or (a == 192 and b == 168) or (a == 172 and 16 <= b <= 31)


def local_ips():
    """列出本机 IPv4，内网地址优先。

    先解析 ipconfig / ifconfig 的真实网卡，再补 socket 探测。
    单靠 UDP-connect 技巧在有 VPN/虚拟网卡时会给出错误地址。
    """
    found = []

    def add(ip):
        if ip.startswith("127.") or ip.startswith("169.254."):
            return
        if ip not in found:
            found.append(ip)

    # 真实网卡枚举（中文 Windows 的 ipconfig 输出是 GBK，不能用 text=True）
    import re
    for cmd in (["ipconfig"], ["ifconfig"]):
        try:
            raw = subprocess.run(cmd, capture_output=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if not raw:
            continue
        txt = None
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                txt = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if not txt:
            continue
        for m in re.finditer(r"(?:IPv4[^\d]*|inet\s+(?:addr:)?)(\d+\.\d+\.\d+\.\d+)", txt):
            add(m.group(1))
        if found:
            break

    # 兜底
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        add(s.getsockname()[0])
        s.close()
    except OSError:
        pass

    # 内网地址排前面
    return sorted(found, key=lambda ip: (not _is_private(ip), ip))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4443,
                    help="监听端口，固件默认连 4443")
    ap.add_argument("--dir", default=HERE, help="要服务的目录（含 xxx.json）")
    ap.add_argument("--cert", default=os.path.join(HERE, "cert.pem"))
    ap.add_argument("--key", default=os.path.join(HERE, "key.pem"))
    args = ap.parse_args()

    serve_dir = os.path.abspath(args.dir)
    if not os.path.isdir(serve_dir):
        print(f"目录不存在: {serve_dir}")
        sys.exit(1)

    ensure_cert(args.cert, args.key)

    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
        *a, directory=serve_dir, **kw
    )
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), handler)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(args.cert, args.key)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

    json_files = sorted(f for f in os.listdir(serve_dir) if f.endswith(".json"))

    print("=" * 62)
    print(f"  服务目录 : {serve_dir}")
    print(f"  端口     : {args.port} (HTTPS，自签名)")
    print(f"  可用主题 : {', '.join(json_files) if json_files else '(目录里没有 .json)'}")
    print("=" * 62)
    print("在 Clockwise 设置页里填：")
    print("  [Canvas] Server Address : <下面任一 IP>")
    print("  [Canvas] Description file: 主题文件名（不含 .json）")
    print()
    for ip in local_ips():
        print(f"    -> {ip}")
    print()
    print(f"自测：浏览器打开 https://127.0.0.1:{args.port}/  （证书告警选继续）")
    print("Ctrl+C 停止")
    print()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()

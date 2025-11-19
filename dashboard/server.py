#!/usr/bin/env python3
"""
PolySurge 本地开发服务器
- 提供静态文件
- 代理 Polymarket API（解决 CORS 问题）
"""

import http.server
import socketserver
import urllib.request
import urllib.error
import json
import os
from urllib.parse import urlparse, parse_qs

PORT = 8080
API_BASE = "https://data-api.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        # API 代理
        if parsed.path.startswith('/api/'):
            self.proxy_api(parsed)
        else:
            # 静态文件
            super().do_GET()

    def proxy_api(self, parsed):
        path = parsed.path[4:]  # 去掉 /api 前缀
        query = parsed.query

        # 确定目标 URL
        if path.startswith('/gamma/'):
            url = f"{GAMMA_BASE}{path[6:]}"
        else:
            url = f"{API_BASE}{path}"

        if query:
            url += f"?{query}"

        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'PolySurge/1.0')

            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read()

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(data)

        except urllib.error.HTTPError as e:
            self.send_error(e.code, str(e))
        except Exception as e:
            self.send_error(500, str(e))

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    with socketserver.TCPServer(("", PORT), ProxyHandler) as httpd:
        print(f"""
╔════════════════════════════════════════════╗
║     PolySurge - 异常信号雷达               ║
╚════════════════════════════════════════════╝

服务器已启动: http://localhost:{PORT}

API 代理:
  - /api/trades    -> data-api.polymarket.com/trades
  - /api/gamma/... -> gamma-api.polymarket.com/...

按 Ctrl+C 停止服务器
""")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n服务器已停止")


if __name__ == "__main__":
    main()

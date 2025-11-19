#!/bin/bash

echo "
╔════════════════════════════════════════════╗
║     PolySurge - Polymarket 异常信号雷达     ║
╚════════════════════════════════════════════╝
"

cd "$(dirname "$0")"

# 检查端口是否被占用
if lsof -i:8080 > /dev/null 2>&1; then
    echo "端口 8080 已被占用，尝试关闭..."
    kill $(lsof -t -i:8080) 2>/dev/null
    sleep 1
fi

echo "启动服务器..."
python3 server.py &

sleep 2

echo "
服务器已启动！

打开浏览器访问: http://localhost:8080

按 Ctrl+C 停止服务器
"

# 自动打开浏览器
if command -v open > /dev/null; then
    open "http://localhost:8080"
elif command -v xdg-open > /dev/null; then
    xdg-open "http://localhost:8080"
fi

# 等待用户中断
wait

#!/usr/bin/env bash
# PikPak <-> 115 一键运行脚本
#
# 用法:
#   ./run.sh                  # 交互式菜单
#   ./run.sh install          # 装依赖
#   ./run.sh status           # 查看后台任务进度（任何时候都能跑）
#   ./run.sh stop             # 停止后台任务
#   ./run.sh daemon           # 后台静默启动（推荐：选完任务后用这个，关 SSH 不断）
#
set -euo pipefail
cd "$(dirname "$0")"

PY=python3
command -v $PY >/dev/null 2>&1 || { echo "[!] 未找到 python3: apt install -y python3 python3-pip"; exit 1; }

PID_FILE="./.run.pid"
LOG_FILE="./sync.log"

# ---- 子命令：install / status / stop / daemon ----
if [ $# -ge 1 ]; then
    case "$1" in
        install)
            $PY -c "import requests, p115client" 2>/dev/null && { echo "[*] 依赖已就绪。"; exit 0; }
            echo "[*] 安装依赖 ..."
            pip3 install --user --break-system-packages requests p115client 2>/dev/null \
                || pip3 install --user requests p115client
            exit 0 ;;
        status)
            if [ ! -f progress.json ]; then
                echo "还没有任何任务记录。先 ./run.sh 开始一个任务。"
                exit 0
            fi
            $PY - <<'PYEOF'
import json, time
from pathlib import Path
p = json.loads(Path("progress.json").read_text())
print("----- 任务进度 -----")
if p.get("error"):
    print(f"  状态: 失败 — {p['error']}")
elif p.get("running"):
    print("  状态: 传输中")
else:
    print("  状态: 已结束（或未启动）")
print(f"  方向: {p.get('direction','-')}")
print(f"  源:   {p.get('source','-')}")
print(f"  目标: {p.get('target','-')}")
if p.get("total_files"):
    pct = p["done_files"]/p["total_files"]*100
    print(f"  文件: {p['done_files']}/{p['total_files']} ({pct:.1f}%)")
if p.get("current_file"):
    print(f"  当前: {p['current_file']}")
if p.get("started_at"):
    print(f"  已运行: {int(time.time()-p['started_at'])} 秒")
if p.get("updated_at"):
    print(f"  上次更新: {time.strftime('%H:%M:%S', time.localtime(p['updated_at']))}")
print("--------------------")
PYEOF
            exit 0 ;;
        stop)
            if [ -f "$PID_FILE" ]; then
                PID=$(cat "$PID_FILE")
                if kill -0 "$PID" 2>/dev/null; then
                    kill "$PID" && echo "已停止 PID=$PID"
                else
                    echo "PID=$PID 已不在运行"
                fi
                rm -f "$PID_FILE"
            else
                echo "没有记录到后台进程。"
            fi
            exit 0 ;;
        daemon)
            if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
                echo "已有后台任务在跑 (PID=$(cat $PID_FILE))。先 ./run.sh stop 或 ./run.sh status。"
                exit 1
            fi
            nohup $PY cli.py >> "$LOG_FILE" 2>&1 &
            echo $! > "$PID_FILE"
            echo "已后台启动 (PID=$(cat $PID_FILE))。"
            echo "日志: $LOG_FILE"
            echo "随时查看进度: ./run.sh status"
            echo "停止: ./run.sh stop"
            exit 0 ;;
    esac
fi

# ---- 依赖 ----
$PY -c "import requests, p115client" 2>/dev/null || {
    echo "[*] 安装依赖 ..."
    pip3 install --user --break-system-packages requests p115client 2>/dev/null \
        || pip3 install --user requests p115client
}

# ---- 进交互菜单 ----
exec $PY cli.py

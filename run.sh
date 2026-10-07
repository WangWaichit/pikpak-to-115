#!/usr/bin/env bash
# PikPak -> 115 一键运行脚本
# 用法:
#   ./run.sh              # 正式同步
#   ./run.sh --dry-run    # 预览，不上传
#   ./run.sh install      # 只装依赖，不跑

set -euo pipefail
cd "$(dirname "$0")"

PY=python3
command -v $PY >/dev/null 2>&1 || { echo "[!] 未找到 python3，请先安装: apt install -y python3 python3-pip"; exit 1; }

# ---- 1. 依赖 ----
need_install=0
$PY -c "import requests, p115client" 2>/dev/null || need_install=1
if [ "$need_install" = "1" ]; then
    echo "[*] 安装依赖 requests / p115client ..."
    pip3 install --user --break-system-packages requests p115client 2>/dev/null \
        || pip3 install --user requests p115client
fi

if [ "${1:-}" = "install" ]; then
    echo "[*] 依赖已就绪。"
    exit 0
fi

# ---- 2. .env ----
if [ ! -f .env ]; then
    cp .env.example .env
    echo "[!] 已生成 .env，请先编辑填入凭证:"
    echo "    - PIKPAK_LONG_TERM_TOKEN   (PikPak 开发者后台的长期令牌)"
    echo "    - PAN115_COOKIES            (115 的 UID/CID/SEID/KID)"
    echo "    - PAN115_TARGET_DIR         (115 目标目录)"
    echo
    echo "然后重跑: ./run.sh"
    exit 1
fi

# ---- 3. 跑 ----
exec $PY pikpak_to_115.py "$@"

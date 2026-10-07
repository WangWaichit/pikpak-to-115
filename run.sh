#!/usr/bin/env bash
# PikPak -> 115 一键运行脚本
#
# 用法:
#   ./run.sh                  # 进入交互式菜单（首次会引导填 token/cookies）
#   ./run.sh --dry-run        # 用上次记录的源/目标预览
#   ./run.sh sync             # 用上次记录的源/目标直接同步
#
# 也支持命令行传 key（跳过交互配置）:
#   ./run.sh --pikpak-token eyJ... --115-cookies "UID=..;CID=..;SEID=..;KID=.."
#
set -euo pipefail
cd "$(dirname "$0")"

PY=python3
command -v $PY >/dev/null 2>&1 || { echo "[!] 未找到 python3: apt install -y python3 python3-pip"; exit 1; }

# ---- 1. 解析命名参数 ----
PASSTHROUGH=()
while [ $# -gt 0 ]; do
    case "$1" in
        --pikpak-token)    export PIKPAK_LONG_TERM_TOKEN="$2"; shift 2 ;;
        --115-cookies)     export PAN115_COOKIES="$2"; shift 2 ;;
        --115-target)      export PAN115_TARGET_DIR="$2"; shift 2 ;;
        --pikpak-source)   export PIKPAK_SOURCE_DIR="$2"; shift 2 ;;
        --tmp-dir)         export TMP_DIR="$2"; shift 2 ;;
        install)
            $PY -c "import requests, p115client" 2>/dev/null && { echo "[*] 依赖已就绪。"; exit 0; }
            echo "[*] 安装依赖 ..."
            pip3 install --user --break-system-packages requests p115client 2>/dev/null \
                || pip3 install --user requests p115client
            exit 0 ;;
        *) PASSTHROUGH+=("$1"); shift ;;
    esac
done

# ---- 2. 依赖 ----
$PY -c "import requests, p115client" 2>/dev/null || {
    echo "[*] 安装依赖 ..."
    pip3 install --user --break-system-packages requests p115client 2>/dev/null \
        || pip3 install --user requests p115client
}

# ---- 3. 进交互菜单 ----
exec $PY cli.py "${PASSTHROUGH[@]}"

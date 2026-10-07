#!/usr/bin/env bash
# PikPak -> 115 一键运行脚本
#
# 用法:
#   ./run.sh                                          # 用 .env 里的凭证
#   ./run.sh --dry-run                                # 预览，用 .env
#   ./run.sh --pikpak-token eyJ... --115-cookies "UID=..;CID=..;SEID=..;KID=.."
#   ./run.sh --pikpak-token eyJ... --115-cookies "..." --115-target /备份 --dry-run
#
# 也支持环境变量:
#   PIKPAK_LONG_TERM_TOKEN=eyJ... PAN115_COOKIES="..." ./run.sh
#
# 第一次运行会自动装依赖。

set -euo pipefail
cd "$(dirname "$0")"

PY=python3
command -v $PY >/dev/null 2>&1 || { echo "[!] 未找到 python3，请先安装: apt install -y python3 python3-pip"; exit 1; }

# ---- 1. 解析命名参数（其余透传给 python） ----
PASSTHROUGH=()
while [ $# -gt 0 ]; do
    case "$1" in
        --pikpak-token)    PIKPAK_LONG_TERM_TOKEN="$2"; shift 2 ;;
        --115-cookies)     PAN115_COOKIES="$2"; shift 2 ;;
        --115-target)      PAN115_TARGET_DIR="$2"; shift 2 ;;
        --pikpak-source)   PIKPAK_SOURCE_DIR="$2"; shift 2 ;;
        --tmp-dir)         TMP_DIR="$2"; shift 2 ;;
        install)
            # 仅装依赖
            $PY -c "import requests, p115client" 2>/dev/null && { echo "[*] 依赖已就绪。"; exit 0; }
            echo "[*] 安装依赖 ..."
            pip3 install --user --break-system-packages requests p115client 2>/dev/null \
                || pip3 install --user requests p115client
            exit 0
            ;;
        *) PASSTHROUGH+=("$1"); shift ;;
    esac
done

# ---- 2. 依赖 ----
$PY -c "import requests, p115client" 2>/dev/null || {
    echo "[*] 安装依赖 requests / p115client ..."
    pip3 install --user --break-system-packages requests p115client 2>/dev/null \
        || pip3 install --user requests p115client
}

# ---- 3. 凭证来源优先级: 命令行 > 环境变量 > .env ----
if [ -z "${PIKPAK_LONG_TERM_TOKEN:-}" ] && [ -z "${PIKPAK_REFRESH_TOKEN:-}" ] && [ ! -f .env ]; then
    cp .env.example .env
    echo "[!] 未提供凭证。请用以下任一方式:"
    echo
    echo "  A) 命令行传 key:"
    echo "     ./run.sh --pikpak-token eyJ... --115-cookies \"UID=..;CID=..;SEID=..;KID=..\""
    echo
    echo "  B) 编辑 .env 后重跑: vim .env"
    exit 1
fi

# 有 .env 就 source 进来（已有的环境变量优先，不被覆盖）
if [ -f .env ]; then
    set -a; . ./.env; set +a
fi

# 把命令行传入的凭证 export 给 python（优先级最高）
[ -n "${PIKPAK_LONG_TERM_TOKEN:-}" ] && export PIKPAK_LONG_TERM_TOKEN
[ -n "${PAN115_COOKIES:-}" ]         && export PAN115_COOKIES
[ -n "${PAN115_TARGET_DIR:-}" ]      && export PAN115_TARGET_DIR
[ -n "${PIKPAK_SOURCE_DIR:-}" ]      && export PIKPAK_SOURCE_DIR
[ -n "${TMP_DIR:-}" ]                && export TMP_DIR

# ---- 4. 跑 ----
exec $PY pikpak_to_115.py "${PASSTHROUGH[@]}"

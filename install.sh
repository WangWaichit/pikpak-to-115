#!/usr/bin/env bash
# PikPak <-> 115 一键安装脚本
# 用法:
#   wget -O- https://raw.githubusercontent.com/WangWaichit/pikpak-to-115/main/install.sh | bash
#   或
#   curl -fsSL https://raw.githubusercontent.com/WangWaichit/pikpak-to-115/main/install.sh | bash
#
set -e

REPO="https://github.com/WangWaichit/pikpak-to-115.git"
DIR="pikpak-to-115"

echo "===== PikPak <-> 115 一键安装 ====="
echo

# ---- 1. 检测包管理器 ----
detect_pkgmgr() {
    if command -v apt-get >/dev/null 2>&1; then
        echo "apt"
    elif command -v dnf >/dev/null 2>&1; then
        echo "dnf"
    elif command -v yum >/dev/null 2>&1; then
        echo "yum"
    elif command -v apk >/dev/null 2>&1; then
        echo "apk"
    else
        echo "unknown"
    fi
}

PKG=$(detect_pkgmgr)
echo "[*] 包管理器: $PKG"

# ---- 2. 系统依赖 ----
NEED=()
command -v git      >/dev/null 2>&1 || NEED+=(git)
command -v python3  >/dev/null 2>&1 || NEED+=(python3)
if ! python3 -c "import pip" 2>/dev/null; then
    case "$PKG" in
        apt) NEED+=(python3-pip) ;;
        dnf|yum) NEED+=(python3-pip) ;;
        apk) NEED+=(py3-pip) ;;
    esac
fi

if [ ${#NEED[@]} -gt 0 ]; then
    echo "[*] 需要安装系统包: ${NEED[*]}"
    case "$PKG" in
        apt)
            apt-get update -y
            apt-get install -y "${NEED[@]}"
            ;;
        dnf)
            dnf install -y "${NEED[@]}"
            ;;
        yum)
            yum install -y "${NEED[@]}"
            ;;
        apk)
            apk add --no-cache "${NEED[@]}"
            ;;
        *)
            echo "[!] 不认识的包管理器，请手动安装: ${NEED[*]}"
            exit 1
            ;;
    esac
else
    echo "[*] 系统依赖已就绪 (git, python3, pip)"
fi

# ---- 3. Python 依赖 ----
echo "[*] 检查 Python 依赖..."
if ! python3 -c "import requests, p115client" 2>/dev/null; then
    echo "[*] pip 安装 requests p115client ..."
    pip3 install --user --break-system-packages requests p115client 2>/dev/null \
        || pip3 install --user requests p115client
else
    echo "[*] Python 依赖已就绪"
fi

# ---- 4. clone 仓库 ----
if [ -d "$DIR" ]; then
    echo "[*] 已存在 $DIR，git pull 更新..."
    cd "$DIR"
    git pull --ff-only || echo "[!] git pull 失败，继续用现有代码"
else
    echo "[*] 克隆仓库到 ./$DIR ..."
    git clone "$REPO" "$DIR"
    cd "$DIR"
fi

chmod +x run.sh

echo
echo "===== 安装完成 ====="
echo
echo "下一步:"
echo "  cd $DIR"
echo "  ./run.sh          # 交互菜单（首次会引导填凭证）"
echo "  ./run.sh daemon   # 后台静默跑（关 SSH 不断）"
echo "  ./run.sh status   # 看进度"
echo

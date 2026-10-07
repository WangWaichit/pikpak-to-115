#!/usr/bin/env bash
# PikPak <-> 115 一键安装脚本
# 用法:
#   wget -O- https://raw.githubusercontent.com/WangWaichit/pikpak-to-115/main/install.sh | bash
#   或
#   curl -fsSL https://raw.githubusercontent.com/WangWaichit/pikpak-to-115/main/install.sh | bash
#
# 行为：
#   1. 自动判断系统 (Debian/Ubuntu/CentOS/Rocky/Alma/Alpine/Arch)
#   2. 缺哪个依赖装哪个 (git, python3, pip, build 工具)
#   3. 如果系统 Python < 3.8，尝试装新版 Python
#   4. pip 装 requests, p115client
#   5. clone 仓库
#
set -e

REPO="https://github.com/WangWaichit/pikpak-to-115.git"
DIR="pikpak-to-115"

echo "===== PikPak <-> 115 一键安装 ====="
echo

# ---- 0. 必须 root 或 sudo ----
if [ "$(id -u)" -ne 0 ] && ! command -v sudo >/dev/null 2>&1; then
    echo "[!] 请用 root 跑，或先装 sudo"
    exit 1
fi
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

# ---- 1. 识别系统 ----
echo "[*] 识别系统..."
if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo "    系统: $PRETTY_NAME"
fi

detect_pkgmgr() {
    if command -v apt-get >/dev/null 2>&1; then
        echo "apt"
    elif command -v dnf >/dev/null 2>&1; then
        echo "dnf"
    elif command -v yum >/dev/null 2>&1; then
        echo "yum"
    elif command -v apk >/dev/null 2>&1; then
        echo "apk"
    elif command -v pacman >/dev/null 2>&1; then
        echo "pacman"
    else
        echo "unknown"
    fi
}
PKG=$(detect_pkgmgr)
echo "    包管理器: $PKG"

# ---- 2. 装系统依赖 ----
install_pkgs() {
    # $1..N = 包名列表
    case "$PKG" in
        apt)
            $SUDO apt-get update -y
            $SUDO apt-get install -y "$@"
            ;;
        dnf)
            $SUDO dnf install -y "$@"
            ;;
        yum)
            $SUDO yum install -y "$@"
            ;;
        apk)
            $SUDO apk add --no-cache "$@"
            ;;
        pacman)
            $SUDO pacman -S --needed --noconfirm "$@"
            ;;
        *)
            echo "[!] 不认识的包管理器 $PKG，请手动安装: $*"
            return 1
            ;;
    esac
}

# 收集缺什么
NEED=()
command -v git     >/dev/null 2>&1 || NEED+=(git)
command -v wget    >/dev/null 2>&1 || NEED+=(wget)
command -v python3 >/dev/null 2>&1 || NEED+=(python3)
command -v pip3    >/dev/null 2>&1 || NEED+=(python3-pip)

# Python 版本检查
PY_OK=0
if command -v python3 >/dev/null 2>&1; then
    PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info[0])')
    PY_MINOR=$(python3 -c 'import sys; print(sys.version_info[1])')
    if [ "$PY_MAJOR" -gt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -ge 8 ]; }; then
        PY_OK=1
        echo "    Python: $(python3 --version)"
    else
        echo "    Python 版本太老: $(python3 --version)（需要 >= 3.8）"
        PY_OK=0
    fi
fi

# 如果 Python 太老或没有，按系统装新版
if [ "$PY_OK" -eq 0 ]; then
    echo "[*] 需要安装 Python 3.8+"
    case "$PKG" in
        apt)
            # Ubuntu 20.04 自带 python3.8，新一点的版本自带更新的
            NEED+=(python3 python3-pip python3-venv)
            ;;
        dnf)
            NEED+=(python3.9 python3.9-pip)
            # CentOS/Rocky 8/9 用 python39
            ;;
        yum)
            NEED+=(python39 python39-pip)
            ;;
        apk)
            NEED+=(python3 py3-pip)
            ;;
        pacman)
            NEED+=(python python-pip)
            ;;
    esac
fi

if [ ${#NEED[@]} -gt 0 ]; then
    echo "[*] 安装系统包: ${NEED[*]}"
    install_pkgs "${NEED[@]}"
else
    echo "[*] 系统依赖已就绪"
fi

# CentOS/Rocky 8/9 装完 python39 后，python3 可能还是指向 3.6，需要用 python39
if ! python3 -c 'import sys; exit(0 if sys.version_info >= (3,8) else 1)' 2>/dev/null; then
    if command -v python3.9 >/dev/null 2>&1; then
        ln -sf "$(command -v python3.9)" /usr/local/bin/python3
        ln -sf "$(command -v pip3.9 2>/dev/null || echo pip3.9)" /usr/local/bin/pip3 2>/dev/null || true
        hash -r
        echo "    已切换 python3 -> $(python3 --version)"
    fi
fi

# ---- 3. pip 装 Python 依赖 ----
echo "[*] 检查 Python 依赖..."
if ! python3 -c "import requests, p115client" 2>/dev/null; then
    echo "[*] pip 安装 requests p115client ..."
    # 优先 --user --break-system-packages（新系统），失败回退到普通 pip
    pip3 install --user --break-system-packages requests p115client 2>/dev/null \
        || pip3 install --user requests p115client \
        || pip3 install requests p115client
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

chmod +x run.sh install.sh

echo
echo "===== 安装完成 ====="
echo
echo "下一步:"
echo "  cd $DIR"
echo "  ./run.sh          # 交互菜单（首次会引导填凭证）"
echo "  ./run.sh daemon   # 后台静默跑（关 SSH 不断）"
echo "  ./run.sh status   # 看进度"
echo

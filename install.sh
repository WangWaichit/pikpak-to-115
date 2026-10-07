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

# 检查 Python 3.12 是否可用（p115client 要求 >=3.12）
NEED_PY=0
CUR_PY_VER=""
if command -v python3.12 >/dev/null 2>&1; then
    PY_BIN=python3.12
elif command -v python3 >/dev/null 2>&1; then
    if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>/dev/null; then
        PY_BIN=python3
    else
        CUR_PY_VER=$(python3 --version)
        PY_BIN=""
        NEED_PY=1
    fi
else
    PY_BIN=""
    NEED_PY=1
fi

if [ -n "$PY_BIN" ]; then
    echo "    Python: $($PY_BIN --version)"
fi

# 如果 Python 3.12 没有，询问用户是否安装
if [ "$NEED_PY" -eq 1 ]; then
    echo
    echo "=========================================="
    echo "  ⚠️  检测到 Python 版本过低"
    if [ -n "$CUR_PY_VER" ]; then
        echo "  当前版本: $CUR_PY_VER"
    else
        echo "  当前版本: 未安装"
    fi
    echo "  本程序依赖 p115client，要求 Python >= 3.12"
    echo "=========================================="
    printf "  是否自动安装 Python 3.12? [Y/n]: "
    read ANSWER
    case "$ANSWER" in
        n|N|no|No|NO)
            echo "  已取消。请手动安装 Python 3.12 后重跑本脚本。"
            exit 1
            ;;
    esac

    # 按系统加包
    case "$PKG" in
        apt)
            NEED+=(software-properties-common)
            ;;
        dnf)
            NEED+=(python3.12 python3.12-pip)
            ;;
        yum)
            NEED+=(python3.12 python3.12-pip)
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
fi

# apt 系统：加 deadsnakes PPA 装 python3.12
if [ "$NEED_PY" -eq 1 ] && [ "$PKG" = "apt" ]; then
    if ! command -v python3.12 >/dev/null 2>&1; then
        echo "[*] 添加 deadsnakes PPA 并安装 python3.12 ..."
        $SUDO add-apt-repository -y ppa:deadsnakes/ppa
        $SUDO apt-get update -y
        $SUDO apt-get install -y python3.12 python3.12-venv python3.12-dev
    fi
fi

# 选定 Python 解释器
if command -v python3.12 >/dev/null 2>&1; then
    PY_BIN=python3.12
elif python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>/dev/null; then
    PY_BIN=python3
else
    echo "[!] 仍找不到 Python 3.12。请手动安装后重试。"
    exit 1
fi

# 确保 pip 可用
if ! $PY_BIN -m pip --version >/dev/null 2>&1; then
    echo "[*] 给 $PY_BIN 装 pip ..."
    $PY_BIN -m ensurepip --upgrade 2>/dev/null || \
        $SUDO apt-get install -y python3-pip 2>/dev/null || true
fi

# 切 python3 -> python3.12（如果系统默认太老）
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>/dev/null; then
    ln -sf "$(command -v $PY_BIN)" /usr/local/bin/python3
    ln -sf "$(command -v $PY_BIN)-m pip" /usr/local/bin/pip3 2>/dev/null || true
    hash -r
fi
echo "    使用: $(python3 --version)"

# ---- 3. pip 装 Python 依赖 ----
echo "[*] 检查 Python 依赖..."
if ! python3 -c "import requests, p115client" 2>/dev/null; then
    echo "[*] pip 安装 requests p115client ..."
    # 优先 --break-system-packages（新系统），失败回退到普通 pip
    python3 -m pip install --break-system-packages requests p115client 2>/dev/null \
        || python3 -m pip install --user requests p115client \
        || python3 -m pip install requests p115client
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

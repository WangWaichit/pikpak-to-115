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

# 跳过 apt 交互式弹窗（needrestart / 内核升级提示）
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
export NEEDRESTART_SUSPEND=1

REPO="https://github.com/WangWaichit/pikpak-to-115.git"
DIR="pikpak-to-115"

echo "===== PikPak <-> 115 一键安装 v3.2 ====="
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

# ---- 1.5 判断国内/国外，选镜像源 ----
IS_CN=0
PIP_INDEX=""
echo "[*] 检测网络位置（国内/国外）..."
COUNTRY=$(curl -s --max-time 5 http://ip-api.com/json?fields=countryCode 2>/dev/null \
    | grep -o '"countryCode":"[A-Z]*"' | cut -d'"' -f4 || true)
if [ "$COUNTRY" = "CN" ]; then
    IS_CN=1
    PIP_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
    echo "    位置: 国内 → 使用清华镜像"
else
    echo "    位置: 国外/未知 ($COUNTRY) → 使用官方源"
fi

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
    if ! command -v python3.12 >/dev/null 2>&1 && [ ! -x /usr/bin/python3.12 ]; then
        echo "[*] 添加 deadsnakes PPA 并安装 python3.12 ..."
        $SUDO add-apt-repository -y ppa:deadsnakes/ppa
        $SUDO apt-get update -y
        # 只装 python3.12 本体；不装 -venv/-dev（本程序不需要）
        if ! $SUDO apt-get install -y python3.12; then
            echo "[!] python3.12 安装失败。可能原因："
            echo "    1) Ubuntu 版本太老（<20.04）deadsnakes 不支持"
            echo "    2) 网络问题拉不到 PPA"
            echo "    请把上面的 apt 报错发出来。"
            exit 1
        fi
        hash -r
    fi
fi

# 选定 Python 解释器
hash -r
if command -v python3.12 >/dev/null 2>&1; then
    PY_BIN=python3.12
elif [ -x /usr/bin/python3.12 ]; then
    PY_BIN=/usr/bin/python3.12
elif python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>/dev/null; then
    PY_BIN=python3
else
    echo "[!] 仍找不到 Python 3.12。请手动安装后重试。"
    echo "    手动装: apt install -y python3.12"
    exit 1
fi
echo "    找到 Python: $($PY_BIN --version)  ($(command -v $PY_BIN 2>/dev/null || echo $PY_BIN))"

# 确保 pip 可用（Python 3.12 移除了 distutils，系统 pip 会崩，必须用 get-pip.py 重装）
if ! $PY_BIN -m pip --version >/dev/null 2>&1; then
    echo "[*] 给 $PY_BIN 重装 pip（get-pip.py，绕开 distutils 缺失）..."
    GETPIP=/tmp/get-pip.py
    if [ ! -f "$GETPIP" ]; then
        wget --no-cache -q https://bootstrap.pypa.io/get-pip.py -O "$GETPIP" || \
        curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$GETPIP"
    fi
    $SUDO $PY_BIN "$GETPIP" --break-system-packages 2>/dev/null \
        || $PY_BIN "$GETPIP" --user 2>/dev/null \
        || $PY_BIN "$GETPIP"
    rm -f "$GETPIP"
    hash -r
    if ! $PY_BIN -m pip --version >/dev/null 2>&1; then
        echo "[!] pip 安装失败。请手动跑: $PY_BIN /tmp/get-pip.py"
        exit 1
    fi
    echo "    pip: $($PY_BIN -m pip --version)"
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
    PIP_ARGS=""
    [ -n "$PIP_INDEX" ] && PIP_ARGS="-i $PIP_INDEX"
    python3 -m pip install --break-system-packages $PIP_ARGS requests p115client 2>/dev/null \
        || python3 -m pip install --user $PIP_ARGS requests p115client \
        || python3 -m pip install $PIP_ARGS requests p115client
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

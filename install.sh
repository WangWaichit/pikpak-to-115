#!/usr/bin/env bash
# PikPak <-> 115 一键安装脚本 v3.5
# 全程零交互弹窗，自动识别系统，装完只需填 config.json
#
# 用法:
#   wget --no-cache -O- https://raw.githubusercontent.com/WangWaichit/pikpak-to-115/main/install.sh | bash
#
set -euo pipefail

# ====================== 全局静默（屏蔽所有交互弹窗）======================
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
export NEEDRESTART_SUSPEND=1
export DPKG_OPTIONS="--force-confdef --force-confold"

REPO="https://github.com/WangWaichit/pikpak-to-115.git"
DIR="pikpak-to-115"

# ---- 等 apt 锁释放（新装 VPS 系统自动更新会锁 apt，最多等 5 分钟）----
echo "[*] 检查 apt 锁..."
for i in $(seq 1 60); do
    if ! fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 \
       && ! fuser /var/lib/dpkg/lock >/dev/null 2>&1 \
       && ! fuser /var/lib/apt/lists/lock >/dev/null 2>&1; then
        break
    fi
    PID=$(fuser /var/lib/dpkg/lock-frontend 2>/dev/null | awk '{print $1}')
    echo "  apt 被 PID=$PID 占用，等 5 秒... ($i/60)"
    sleep 5
done

# 兜底：等完还锁，停掉 unattended-upgrades
if fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; then
    echo "[*] 等满 5 分钟还在跑，停掉 unattended-upgrades..."
    systemctl stop unattended-upgrades 2>/dev/null || true
    pkill -f apt-get 2>/dev/null || true
    sleep 2
    dpkg --configure -a 2>/dev/null || true
fi

echo "===== PikPak <-> 115 一键安装 v3.5 (零交互) ====="
echo

# ---- root 检查 ----
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
else
    SUDO=""
fi

# ---- 识别系统 ----
if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo "  系统: $PRETTY_NAME"
fi

detect_pkgmgr() {
    if command -v apt-get >/dev/null 2>&1; then echo "apt"
    elif command -v dnf >/dev/null 2>&1; then echo "dnf"
    elif command -v yum >/dev/null 2>&1; then echo "yum"
    else echo "unsupported"; fi
}
PKG=$(detect_pkgmgr)
echo "  包管理器: $PKG"

if [ "$PKG" = "unsupported" ]; then
    echo "[!] 暂不支持的系统。仅支持 Ubuntu / Debian / CentOS / Rocky / AlmaLinux"
    exit 1
fi

# ---- 检测国内/国外，选 pip 源 ----
echo "[*] 检测网络位置..."
COUNTRY=$(curl -s --max-time 5 http://ip-api.com/json?fields=countryCode 2>/dev/null \
    | grep -o '"countryCode":"[A-Z]*"' | cut -d'"' -f4 || true)
PIP_INDEX=""
if [ "$COUNTRY" = "CN" ]; then
    PIP_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
    echo "  国内 → 清华镜像"
else
    echo "  国外/未知 ($COUNTRY) → 官方源"
fi

# ---- 装系统依赖 ----
echo "[*] 安装系统依赖..."
case "$PKG" in
    apt)
        $SUDO apt-get update -y
        $SUDO apt-get install -y git wget curl ca-certificates
        ;;
    dnf|yum)
        $SUDO $PKG install -y git wget curl ca-certificates
        ;;
esac

# ---- 装 Python 3.12 ----
install_py312() {
    if command -v python3.12 >/dev/null 2>&1; then
        echo "  python3.12 已存在: $(python3.12 --version)"
        return 0
    fi
    echo "[*] 安装 Python 3.12 ..."
    case "$PKG" in
        apt)
            $SUDO apt-get install -y software-properties-common
            $SUDO add-apt-repository -y ppa:deadsnakes/ppa
            $SUDO apt-get update -y
            $SUDO apt-get install -y python3.12
            ;;
        dnf)
            $SUDO dnf install -y python3.12
            ;;
        yum)
            $SUDO yum install -y python3.12
            ;;
    esac
    hash -r
}
install_py312

# ---- get-pip.py 修 distutils ----
if ! python3.12 -m pip --version >/dev/null 2>&1; then
    echo "[*] 用 get-pip.py 重装 pip（修 distutils 缺失）..."
    wget --no-cache -q https://bootstrap.pypa.io/get-pip.py -O /tmp/get-pip.py
    $SUDO python3.12 /tmp/get-pip.py --break-system-packages $PIP_INDEX 2>/dev/null \
        || python3.12 /tmp/get-pip.py --user $PIP_INDEX
    rm -f /tmp/get-pip.py
    hash -r
fi
echo "  pip: $(python3.12 -m pip --version)"

# ---- 软链 python3 -> python3.12 ----
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>/dev/null; then
    $SUDO ln -sf $(command -v python3.12) /usr/local/bin/python3
    hash -r
fi
echo "  python3 -> $(python3 --version)"

# ---- pip 装依赖 ----
echo "[*] 安装 requests p115client ..."
python3 -m pip install --break-system-packages $PIP_INDEX requests p115client

# ---- clone 仓库 ----
cd ~
if [ -d "$DIR" ]; then
    echo "[*] 已存在 $DIR，git pull 更新..."
    cd "$DIR"
    git pull --ff-only || true
else
    git clone "$REPO" "$DIR"
    cd "$DIR"
fi
chmod +x run.sh install.sh

# ---- systemd 服务文件（可选，用户后面自己 enable）----
WORKDIR=$(pwd)
SERVICE_FILE=/etc/systemd/system/pikpak-to-115.service
$SUDO tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=PikPak <-> 115 Sync (interactive CLI)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$WORKDIR
ExecStart=$(command -v python3) $WORKDIR/cli.py
Restart=on-failure
RestartSec=10
StandardOutput=append:$WORKDIR/sync.log
StandardError=append:$WORKDIR/sync.log

[Install]
WantedBy=multi-user.target
EOF
$SUDO systemctl daemon-reload
echo "  已注册 systemd 服务: pikpak-to-115.service"

echo
echo "===== 安装完成，进入配置 ====="
echo
# 直接进 cli.py，它会自动问你 token/cookies
exec ./run.sh

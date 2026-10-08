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

# ---- 等包管理器锁释放（新装 VPS 系统自动更新会锁，最多等 5 分钟）----
echo "[*] 检查包管理器锁..."
wait_for_pkgmgr_lock() {
    local locks=(
        /var/lib/dpkg/lock-frontend
        /var/lib/dpkg/lock
        /var/lib/apt/lists/lock
        /var/cache/apt/archives/lock
        /var/run/dnf/lock.pid
        /var/run/yum.pid
        /var/run/rpm.pid
        /lib/apk/db/lock
    )
    for i in $(seq 1 60); do
        local busy=0
        for l in "${locks[@]}"; do
            [ -e "$l" ] || continue
            if fuser "$l" >/dev/null 2>&1; then
                local pid=$(fuser "$l" 2>/dev/null | awk '{print $1}')
                echo "  锁 $l 被 PID=$pid 占用，等 5 秒... ($i/60)"
                busy=1
                break
            fi
        done
        [ $busy -eq 0 ] && return 0
        sleep 5
    done
    return 1
}

if ! wait_for_pkgmgr_lock; then
    echo "[*] 等满 5 分钟还在跑，停掉自动更新进程..."
    systemctl stop unattended-upgrades 2>/dev/null || true
    systemctl stop packagekit 2>/dev/null || true
    pkill -f "apt-get|dnf|yum|apk" 2>/dev/null || true
    sleep 2
    dpkg --configure -a 2>/dev/null || true
fi

echo "===== PikPak <-> 115 一键安装 v3.6 (零交互) ====="
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
    # 系统自带 python3 >= 3.12 就不用装
    if command -v python3 >/dev/null 2>&1; then
        SYS_PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
        SYS_PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3,12) else 0)' 2>/dev/null)
        if [ "$SYS_PY_OK" = "1" ]; then
            echo "  系统 python3 已是 $SYS_PY_VER (>=3.12)，直接用"
            ln -sf "$(command -v python3)" /usr/local/bin/python3.12
            return 0
        fi
    fi
    echo "[*] 安装 Python 3.12 ..."
    case "$PKG" in
        apt)
            $SUDO apt-get install -y software-properties-common || true
            # 先试 add-apt-repository，失败就手动加 PPA 源
            if ! $SUDO add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null; then
                echo "  [!] add-apt-repository 失败，手动加 deadsnakes 源..."
                CODENAME=$(. /etc/os-release && echo "$UBUNTU_CODENAME")
                [ -z "$CODENAME" ] && CODENAME=focal
                $SUDO mkdir -p /etc/apt/sources.list.d
                echo "deb https://ppa.launchpadcontent.net/deadsnakes/ppa/ubuntu $CODENAME main" \
                    | $SUDO tee /etc/apt/sources.list.d/deadsnakes.list > /dev/null
                # 导入 GPG key
                $SUDO apt-get install -y gnupg ca-certificates || true
                curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xF23C5A6CF475977595C89F51BA6932366A755776" \
                    | gpg --dearmor 2>/dev/null \
                    | $SUDO tee /etc/apt/trusted.gpg.d/deadsnakes.gpg > /dev/null
            fi
            $SUDO apt-get update -y
            $SUDO apt-get install -y python3.12 python3.12-venv python3.12-dev || {
                echo "  [!] apt 装 python3.12 失败，PPA 源可能没生效"
                $SUDO cat /etc/apt/sources.list.d/deadsnakes.list 2>/dev/null
                return 1
            }
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
install_py312 || {
    echo
    echo "[*] apt 装 python3.12 失败，改用源码编译（5-10 分钟）..."
    install -d /tmp/py312-build
    cd /tmp/py312-build
    $SUDO $PKG install -y build-essential libssl-dev zlib1g-dev libbz2-dev \
        libreadline-dev libsqlite3-dev libwrypt-dev libffi-dev \
        libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev liblzma-dev
    wget -q https://www.python.org/ftp/python/3.12.8/Python-3.12.8.tgz
    tar xzf Python-3.12.8.tgz
    cd Python-3.12.8
    ./configure --enable-optimizations --prefix=/usr/local > /tmp/py312-configure.log 2>&1
    make -j"$(nproc)" > /tmp/py312-make.log 2>&1
    $SUDO make altinstall > /tmp/py312-install.log 2>&1
    cd /
    rm -rf /tmp/py312-build
    if command -v python3.12 >/dev/null 2>&1; then
        echo "  源码编译安装成功: $(python3.12 --version)"
    else
        echo "===== 错误 ====="
        echo "自动安装 Python 3.12 失败。请手动安装后重跑本脚本。"
        exit 1
    fi
}

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
echo "[*] 安装 requests p115client (强制升级) ..."
python3 -m pip install --break-system-packages $PIP_INDEX --upgrade requests "p115client>=0.0.9.7"

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

# ---- 注册全局命令 p（用脚本，不用 alias，新开 SSH 也生效）----
$SUDO rm -f /usr/local/bin/pikpak  # 删旧的 pikpak 软链
cat > /tmp/p-run <<EOF
#!/usr/bin/env bash
cd "$WORKDIR" || exit 1
exec ./run.sh
EOF
$SUDO mv /tmp/p-run /usr/local/bin/p
$SUDO chmod +x /usr/local/bin/p

# 同时在 .bashrc 里留个 alias 兜底（去重）
ALIAS_LINE="alias p='cd $WORKDIR && ./run.sh'"
if [ -f /root/.bashrc ]; then
    grep -qxF "$ALIAS_LINE" /root/.bashrc || echo "$ALIAS_LINE" >> /root/.bashrc
fi
echo "  已注册命令: p（任意目录直接敲 p 回车即可）"

echo
echo "===== 安装完成 ====="
echo
echo "接下来手动运行（不要从 wget 管道里跑，否则无法输入凭证）:"
echo "  cd $WORKDIR && ./run.sh"
echo
echo "或者直接任意目录敲: p"
echo
echo "首次启动会问你 PikPak token 和 115 cookies。"
echo
echo "如要后台常驻+开机自启:"
echo "  systemctl enable --now pikpak-to-115"
echo "  journalctl -u pikpak-to-115 -f"
echo

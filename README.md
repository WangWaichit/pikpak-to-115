# PikPak ↔ 115 双向同步 / Bidirectional Sync

中文说明 / English README

---

## 一、设备最低配置 / Requirements

### 推荐操作系统 / Recommended OS

| 优先级 | 中文 | English |
|---|---|---|
| 🥇 首选 | **Ubuntu 22.04 LTS**（256M 小 VPS 首选） | **Ubuntu 22.04 LTS** (best for 256M VPS) |
| 🥈 次选 | **Ubuntu 24.04 LTS**（≥512M，自带 Python 3.12） | **Ubuntu 24.04 LTS** (≥512M, ships with Python 3.12) |
| 🥉 备选 | **Debian 12 (Bookworm)**（极简挂机） | **Debian 12 (Bookworm)** (minimal headless) |

**不推荐 / Not recommended**: Ubuntu 20.04, CentOS 7, Alpine (musl issues), Arch (rolling).

### 硬件 / Hardware

| 项 | 最低 Min | 推荐 Rec |
|---|---|---|
| CPU | 1 vCPU | 1+ vCPU |
| 内存 RAM | 256 MB | 512 MB+ |
| 磁盘 Disk | 5 GB | 10 GB+ |
| 网络 Network | 能访问 `api-drive.mypikpak.com` 和 `115.com` | same |

> 磁盘注意 / Disk note: 文件先临时下载到本地再上传，磁盘至少要装得下单次最大文件，传完自动清理。
> Files are downloaded locally before upload; disk must hold the largest single file. Cleaned up after.

---

## 二、一键安装 / One-line Install

**中文**：全程自动识别系统、自动装依赖、自动更新，无需手动操作。

**English**: Auto-detects OS, installs missing dependencies, updates itself.

```bash
wget -O- https://raw.githubusercontent.com/WangWaichit/pikpak-to-115/main/install.sh | bash
```

or / 或:

```bash
curl -fsSL https://raw.githubusercontent.com/WangWaichit/pikpak-to-115/main/install.sh | bash
```

脚本自动做 / What it does:
1. 检测系统 / Detects OS (apt/dnf/yum/apk/pacman)
2. 缺啥装啥 / Installs git/wget/python3/pip3
3. Python < 3.12 时询问并自动安装 / Asks and installs Python 3.12 if needed
4. 用 get-pip.py 修 distutils 问题 / Bootstraps pip via get-pip.py (fixes Python 3.12 distutils)
5. 国内自动切清华镜像 / Uses Tsinghua mirror if VPS is in CN
6. 装 requests + p115client / Installs deps
7. clone / 更新仓库 / Clones or `git pull`s the repo

---

## 三、启动 / Launch

```bash
cd pikpak-to-115 && ./run.sh
```

---

## 四、首次配置 / First-time Setup

中文：第一次启动会问你两个凭证，粘贴回车即可。

English: On first run, paste your credentials.

1. **PikPak Long-term Token** — JWT `eyJhbGciOi...` from PikPak dev console
2. **115 Cookies** — `UID=..; CID=..; SEID=..; KID=..` from browser

✅ 永久保存，无需重复配置 / Saved permanently.

---

## 五、菜单 / Menu

```
===== 主控菜单 Main Menu =====
  1. 列出 115 目录          List 115 directory
  2. 列出 PikPak 目录       List PikPak directory
  3. 拷贝 115 → PikPak      Copy 115 → PikPak
  4. 拷贝 PikPak → 115      Copy PikPak → 115
  5. 查看复制进度            Show sync progress
  6. 重新配置文件            Reconfigure credentials
  7. 测试 115 cookies        Test 115 cookies
  8. 测试 PikPak token       Test PikPak token
  9. 双侧连接测试            Test both (CN) / Test both
  10. 退出                   Exit
```

目录浏览通用操作 / In directory browser:
- 数字 `1/2/3...` = enter subdir
- `..` = up one level / 上一级
- `.` 或 Enter = select current / 选中当前
- `0` = cancel / 取消

---

## 六、传文件 / Copying Files

### 步骤 / Steps

以菜单 4（PikPak → 115）为例 / Menu 4 (PikPak → 115) shown:

1. 选 `4` / Choose `4`
2. 选源 PikPak 文件夹 / Pick source folder
3. 选目标父目录（115）/ Pick destination parent (115)
4. 选新文件夹命名方式 / Choose naming:
   - **`[1]` 保持原名 / Keep original name** — 直接建同名子文件夹
   - **`[2]` 自定义新名 / Custom name** — 输入新名
5. 确认 `Y` / Confirm

### 例子 / Example

源 / Source:
```
/离线下载/电影/
├── 港片/
│   ├── A计划.mkv
│   └── 警察故事.mkv
└── 好莱坞/盗梦空间.mp4
```

选 / Source = `/离线下载/电影`, 目标父目录 / Parent = `/备份`, 新名 / New name = `movie`:

结果 / Result:
```
/备份/movie/
├── 港片/
│   ├── A计划.mkv
│   └── 警察故事.mkv
└── 好莱坞/盗梦空间.mp4
```

子目录层级完全保留 / Subdirectory tree preserved.

### 覆盖规则 / Overwrite Rules

| 情况 / Case | 行为 / Action |
|---|---|
| 目标无同名 / No same-name file | 直接传 / Upload |
| 同名 + 新文件更大 / Same name, new is larger | **删旧传新 / Delete old, upload new** (old → recycle bin) |
| 同名 + 新文件更小或相等 / New is smaller or equal | **跳过 / Skip** |

---

## 七、后台挂机 / Background Mode

中文：关 SSH、断线、本地关机都不影响传输。

English: Survives SSH disconnect, terminal close, local shutdown.

```bash
# 后台启动 / Start in background
./run.sh daemon

# 看进度 / Check progress
./run.sh status

# 停止 / Stop
./run.sh stop
```

status 示例 / Example status:
```
----- 任务进度 / Progress -----
  状态: 传输中 / Running
  方向: pikpak->115
  源:   /离线下载/电影
  目标: /备份/movie
  文件: 12/30 (40.0%)
  当前: 盗梦空间.mp4
  已运行: 352 秒
```

---

## 八、更新 / Update

```bash
wget -O- https://raw.githubusercontent.com/WangWaichit/pikpak-to-115/main/install.sh | bash
```

配置保留 / Your config is preserved.

---

## 九、FAQ

**Q: 凭证会泄露吗？** / Are credentials leaked?
A: 存在本地 `config.json`，已 gitignore。/ Stored locally in gitignored `config.json`.

**Q: 关 SSH 会断吗？** / Does SSH disconnect kill the transfer?
A: 不会，用 `daemon` 启动后是后台进程。/ No, `daemon` detaches.

**Q: 同名文件会乱覆盖吗？** / Will it overwrite blindly?
A: 不会，只在新文件更大时才替换。/ No, only replaces when new is larger.

**Q: 能跑几个任务？** / How many parallel tasks?
A: 一个。/ One.

**Q: 传一半断了怎么办？** / What if transfer breaks mid-way?
A: 重跑同一条任务即可，已传完的会跳过。/ Re-run; completed files are skipped.

**Q: Token/Cookie 过期怎么办？** / Token expired?
A: 菜单 6 重新配置。/ Menu 6 to reconfigure.

---

## 十、文件 / Files

| 文件 File | 用途 Purpose |
|---|---|
| `pikpak_to_115.py` | Core sync engine / 核心同步逻辑 |
| `cli.py` | Interactive menu / 交互菜单 |
| `run.sh` | launcher / 启动器 (daemon/status/stop) |
| `install.sh` | One-line installer / 一键安装 |
| `config.json` | Credentials (gitignored) |
| `progress.json` | Live progress (gitignored) |
| `sync.log` | Log (gitignored) |
| `.tmp_sync/` | Partial downloads (gitignored) |

---

## Releases

See [releases page](https://github.com/WangWaichit/pikpak-to-115/releases) for version history.

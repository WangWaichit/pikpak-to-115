# PikPak ↔ 115 双向同步 / Bidirectional Sync

中文说明 / English README

---

## 一、设备要求 / Requirements

### 推荐系统 / Recommended OS

| 优先级 | 中文 | English |
|---|---|---|
| 🥇 首选 | Ubuntu 22.04 LTS（256M 小 VPS） | Ubuntu 22.04 LTS (256M VPS) |
| 🥈 次选 | Ubuntu 24.04 LTS（自带 Python 3.12） | Ubuntu 24.04 LTS |
| 🥉 备选 | Debian 12 / CentOS Stream / Rocky / Fedora / Alpine | same |

### 硬件 / Hardware

| 项 | 最低 | 推荐 |
|---|---|---|
| CPU | 1 vCPU | 1+ vCPU |
| 内存 | 256 MB | 512 MB+ |
| 磁盘 | 5 GB | 10 GB+ |
| 网络 | 能访问 api-drive.mypikpak.com 和 115.com | same |

> 磁盘注意：文件先临时下载到本地再上传，磁盘至少装得下单次最大文件，传完自动清理。

---

## 二、一键安装 / One-line Install

```bash
wget -O- https://raw.githubusercontent.com/WangWaichit/pikpak-to-115/main/install.sh | bash
```

脚本自动做 / What it does:
1. 等 apt/dnf/yum/apk 锁释放（最多 5 分钟）
2. 屏蔽所有交互弹窗（needrestart / sshd / cloud.cfg）
3. 自动识别系统（apt/dnf/yum/apk/pacman）
4. 检测国内/国外 IP，自动选 pip 源
5. Python < 3.12 时自动编译安装
6. get-pip.py 修 distutils
7. 强制升级 p115client >= 0.0.9.7
8. 注册全局命令 `p`（任意目录直接敲 p 启动）
9. 注册 systemd 服务（可选开机自启）

安装完手动启动（不要从 wget 管道跑，否则无法输入凭证）：
```bash
p
```

---

## 三、首次配置 / First-time Setup

第一次启动会引导你配置两边凭证。

### PikPak 凭证（二选一）

| 模式 | 说明 |
|---|---|
| 1. Long-term Access Token（推荐） | JWT `eyJhbGciOi...`，从 PikPak 开发者后台生成 |
| 2. OAuth refresh_token | 从 PikPak OAuth 登录拿到 |

### 115 凭证（二选一）

| 模式 | 说明 |
|---|---|
| 1. Cookies（推荐） | 浏览器登录 115 → F12 → Application → Cookies → 复制 `UID=..;CID=..;SEID=..;KID=..` |
| 2. Refresh Token | 115 开放平台 OAuth，回调 `https://api.oplist.org.cn/115cloud/callback`，需要填 app_id |

> ⚠️ 115 写操作（创建文件夹/上传）对 cookies 有效期敏感。如果测试连通性 ✅ 但拷贝时报 `errno 99 请重新登录`，重新粘贴 cookies 即可。

---

## 四、菜单 / Menu

```
[状态] PikPak:✅ | 115:✅
===== PikPak <-> 115 =====
  1. 安装/更新程序
  2. 列出 115 目录
  3. 列出 PikPak 目录
  4. 拷贝 115 → PikPak
  5. 拷贝 PikPak → 115
  6. 查看复制进度
  7. 重新配置文件
  8. 测试 115 连通性
  9. 测试 PikPak 连通性
  10. 测试双侧
  11. 卸载程序
  12. 退出
```

### 目录浏览 / In directory browser

```
[1] 📁 My Pack/
[2] 📄 file.mkv
[..] 返回上一级
[.] 选中当前目录
[0] 返回主菜单
```

- 数字 `1/2/3...` = 进入子目录或选中文件
- `..` = 上一级
- `.` 或 Enter = 选中当前目录
- `0` = 返回主菜单

### 重新配置（菜单 7）二级菜单

```
===== 重新配置 =====
  1. 仅配置 115 网盘凭证
  2. 仅配置 PikPak 凭证
  b. 返回主菜单
```

---

## 五、拷贝规则 / Copy Rules

### 目录命名方式

拷贝一个文件夹时，可选：
- **保持原名**：直接复制过去
- **新建目录名**：自定义新名，子目录层级完全保留

例：源 `/电影/港片/A计划.mkv`，目标父目录 `/备份`，新名 `movie`
→ 结果 `/备份/movie/港片/A计划.mkv`

### 同名文件覆盖

| 情况 | 行为 |
|---|---|
| 目标无同名 | 直接传 |
| 同名 + 新文件更大 | 删旧传新 |
| 同名 + 新文件更小或相等 | 跳过 |

---

## 六、后台运行 / Background

关 SSH 不影响传输：

```bash
# 前台菜单（交互用）
p

# 后台静默跑（nohup）
./run.sh daemon
./run.sh status
./run.sh stop

# systemd（开机自启）
systemctl enable --now pikpak-to-115
journalctl -u pikpak-to-115 -f
```

---

## 七、卸载 / Uninstall

菜单 11 输入 `YES` 后：
- 停 systemd 服务
- 删 `/etc/systemd/system/pikpak-to-115.service`
- 删 `/usr/local/bin/p`
- 从 `.bashrc` 删 alias
- **删整个项目目录**（含凭证、日志、缓存）

---

## 八、已知问题 / Known Issues

### PikPak 目录浏览看不到文件

PikPak 的 `list` 接口只返回子文件夹，不返回文件。文件需要用 search 接口。当前版本在根目录会自动合并 My Pack 里的文件，但子目录浏览仍可能显示 `(0 目录, 0 文件)`。

**临时方案**：直接在 PikPak 网页确认文件位置，拷贝时选到对应文件夹即可。

### 115 errno 99 请重新登录

测试连通性 ✅ 但拷贝时 115 报 `errno 99`，说明 cookies/refresh_token 写权限过期。重新粘贴 cookies（菜单 7 → 1）即可。

### 内存占用

流式传输，单次 ~40MB 内存。256M VPS 可跑。

---

## 九、FAQ

**Q: 凭证会泄露吗？**
A: 存在本地 `config.json`，已 gitignore。

**Q: 关 SSH 会断吗？**
A: 不会，用 daemon/systemd 启动后是后台进程。

**Q: 同名文件会乱覆盖吗？**
A: 不会，只在新文件更大时才替换。

**Q: 传一半断了怎么办？**
A: 重跑同一条任务即可，已传完的会跳过。

**Q: p 命令找不到？**
A: `/usr/local/bin/p` 是全局脚本，新开 SSH 也能用。如果没有，重跑 `bash install.sh`。

---

## 十、文件 / Files

| 文件 | 用途 |
|---|---|
| `pikpak_to_115.py` | 核心同步引擎 |
| `cli.py` | 交互菜单（唯一入口） |
| `run.sh` | 启动器（daemon/status/stop） |
| `install.sh` | 一键安装 |
| `config.json` | 凭证（gitignored） |
| `progress.json` | 进度（gitignored） |
| `sync.log` | 日志（gitignored） |

---

## Releases

见 [releases page](https://github.com/WangWaichit/pikpak-to-115/releases)。

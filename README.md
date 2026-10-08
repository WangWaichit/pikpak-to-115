# PikPak ↔ 115 双向同步 / Bidirectional Sync

中文说明 / English README

---

## 一、设备要求 / Requirements

### 推荐系统 / Recommended OS

| 优先级 | 中文 | English |
|---|---|---|
| 🥇 首选 | Ubuntu 22.04 / 24.04（256M 小 VPS） | Ubuntu 22.04 / 24.04 |
| 🥈 次选 | Debian 12 / CentOS Stream / Rocky / Fedora | same |
| 🥉 备选 | Alpine / Arch | same |

### 硬件 / Hardware

| 项 | 最低 | 推荐 |
|---|---|---|
| CPU | 1 vCPU | 1+ vCPU |
| 内存 | 256 MB | 512 MB+ |
| 磁盘 | 5 GB | 10 GB+ |
| 网络 | 能访问 api-drive.mypikpak.com 和 115.com | same |

---

## 二、一键安装 / One-line Install

```bash
wget -O- https://raw.githubusercontent.com/WangWaichit/pikpak-to-115/main/install.sh | bash
```

如果 raw.githubusercontent.com 连不上，用 jsdelivr：

```bash
wget -O- https://cdn.jsdelivr.net/gh/WangWaichit/pikpak-to-115@main/install.sh | bash
```

### 如果以上都连不上（国内 VPS 常见）

**方案 1：git clone 绕开 wget**
```bash
apt update && apt install git -y   # Debian/Ubuntu
# dnf install git -y              # CentOS/Rocky/Fedora
git clone https://github.com/WangWaichit/pikpak-to-115.git
cd pikpak-to-115 && chmod +x install.sh && ./install.sh
```

**方案 2：手动创建脚本**
1. 浏览器打开 `https://github.com/WangWaichit/pikpak-to-115/blob/main/install.sh`
2. 复制全部代码
3. VPS 上执行 `nano install.sh`，粘贴，`Ctrl+O` 保存，`Ctrl+X` 退出
4. `chmod +x install.sh && ./install.sh`

**方案 3：用 GitHub 代理**
```bash
wget -O- https://ghproxy.com/https://raw.githubusercontent.com/WangWaichit/pikpak-to-115/main/install.sh | bash
```

脚本自动做 / What it does:
1. 等包管理器锁释放（最多 5 分钟）
2. 屏蔽所有交互弹窗
3. 自动识别系统（apt/dnf/yum/apk/pacman）
4. 检测国内/国外 IP，自动选 pip 源
5. **下载预编译 Python 3.12**（~65MB，1分钟，不编译）
6. 装 requests + oss2
7. 注册全局命令 `p`（任意目录直接敲 p 启动）
8. 注册 systemd 服务（可选开机自启）

安装完手动启动（不要从 wget 管道跑）：
```bash
p
```

---

## 三、首次配置 / First-time Setup

### PikPak 凭证（二选一）

| 模式 | 说明 |
|---|---|
| 1. Long-term Access Token（推荐） | JWT `eyJhbGciOi...`，从 PikPak 开发者后台生成，永久有效 |
| 2. OAuth refresh_token | 自动刷新 access_token |

### 115 凭证（OAuth refresh_token）

从 https://api.oplist.org.cn/# 获取 115 refresh_token，粘贴即可。

> v5.0+ 完全使用 115 开放平台 API（proapi.115.com/open/...），不再依赖 p115client，不受网页 Cookie 写权限限制。

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

### 目录浏览

```
[1] 📁 My Pack/
[2] 📄 file.mkv
[..] 返回上一级
[.] 选中当前目录
[0] 返回主菜单
```

---

## 五、拷贝规则 / Copy Rules

| 情况 | 行为 |
|---|---|
| 目标无同名 | 直接传 |
| 同名 + 新文件更大 | 删旧传新 |
| 同名 + 新文件更小或相等 | 跳过 |

拷贝文件夹时可选：保持原名 / 新建目录名（子目录层级保留）。

---

## 六、后台运行 / Background

```bash
p                    # 前台菜单
./run.sh daemon      # 后台静默跑
./run.sh status      # 看进度
./run.sh stop        # 停止
```

systemd 开机自启：
```bash
systemctl enable --now pikpak-to-115
```

---

## 七、卸载 / Uninstall

菜单 11 输入 `YES`，删除所有相关文件和目录。

---

## 八、已知问题 / Known Issues

### PikPak 目录浏览看不到文件
PikPak list 接口只返回文件夹不返回文件。直接在网页确认位置即可。

### 内存占用
流式传输，单次 ~40MB 内存。256M VPS 可跑。

---

## 九、FAQ

**Q: 凭证会泄露吗？** A: 存在本地 config.json，已 gitignore。
**Q: 关 SSH 会断吗？** A: 不会，daemon/systemd 是后台进程。
**Q: p 命令找不到？** A: `/usr/local/bin/p` 是全局脚本，重跑 install.sh 即可。

---

## Releases

见 [releases page](https://github.com/WangWaichit/pikpak-to-115/releases)。

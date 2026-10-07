# PikPak ↔ 115 网盘同步工具

在小内存 VPS 上跑的双向同步工具：PikPak ↔ 115，流式传输、按文件名+大小智能去重、同名新文件自动覆盖旧文件。

## 一键安装

```bash
git clone https://github.com/WangWaichit/pikpak-to-115.git
cd pikpak-to-115
bash run.sh install
```

首次运行 `./run.sh` 会自动引导你填 PikPak 长期令牌和 115 cookies。

## 要求

- Python 3.8+
- 小内存 VPS 友好：常驻内存 ~40MB，传输时按 1MB 块流式处理，不把整个文件读进内存

## 启动

```bash
./run.sh
```

首次启动：
```
===== 配置 =====
PikPak 长期访问令牌 (eyJ...):  ← 粘贴，回车
115 cookies (UID=..;CID=..;SEID=..;KID=..):  ← 粘贴，回车
配置已保存到 config.json
```

之后进入主菜单：

```
===== PikPak <-> 115 =====
  1. 列出 115 目录
  2. 列出 PikPak 目录
  3. 拷贝 115 目录文件到 PikPak 目录
  4. 拷贝 PikPak 目录文件到 115 目录
  5. 查看复制进度
  6. 重新配置文件
  7. 测试 115 cookies 连通性
  8. 测试 PikPak token 连通性
  9. 测试网盘是否连接（双侧）
  10. 退出
===========================
请选择 [1-10]:
```

## 怎么用

### 传文件（菜单 3 或 4）

1. 选 `3`（115→PikPak）或 `4`（PikPak→115）
2. 在源目录浏览树里数字进子目录，`.` 选中当前目录
3. 在目标目录里再选一次
4. 确认 `Y` 后后台开始传
5. 回主菜单选 `5` 看进度

### 去重规则

| 情况 | 行为 |
|---|---|
| 目标里没有同名文件 | 正常传 |
| 同名 + 新文件 ≤ 旧文件 | 跳过 |
| 同名 + 新文件 > 旧文件 | 删旧传新（旧的进回收站，可恢复） |

### 测试连通性（菜单 7/8/9）

- `7`：单独测 115 cookies 能不能列目录
- `8`：单独测 PikPak token 能不能查配额
- `9`：两个一起测，同步前先跑一遍

## 凭证说明

### PikPak 长期令牌

从 PikPak 网页版「设置 / 开发者 / API」生成的 Long-term Access Token（`eyJ...` 开头的 JWT），直接粘即可。

### 115 cookies

浏览器登录 https://115.com 后 F12 → Application → Cookies，复制 `UID`、`CID`、`SEID`、`KID` 拼成一行：

```
UID=123456; CID=xxx; SEID=xxx; KID=xxx
```

## 文件说明

| 文件 | 作用 |
|---|---|
| `pikpak_to_115.py` | 核心：PikPak/115 客户端、流式下载上传、双向同步 |
| `cli.py` | 交互式菜单 |
| `run.sh` | 一键启动（自动装依赖、引导配置） |
| `.env.example` | 环境变量配置模板 |
| `config.json` | 你的凭证（已 gitignore，不会上传） |
| `.pikpak_token.json` | PikPak 短期 token 缓存（自动生成） |
| `.tmp_sync/` | 下载中的临时文件 |

## 后台常驻

```bash
nohup ./run.sh >> sync.log 2>&1 &
tail -f sync.log
```

## 注意

- 115→PikPak 方向（菜单 3）的 PikPak 上传是新写的，第一次跑如果报错把日志发我
- 同时只能跑一个任务
- 用完记得去 https://github.com/settings/tokens revoke 用来 push 的 PAT

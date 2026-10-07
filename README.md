# pikpak-to-115

PikPak → 115 网盘自动同步工具。专为小内存 VPS 设计，流式传输，内存占用恒定在 ~10MB。

## 功能

- 用 PikPak **长期 refresh token** 登录，access token 过期自动刷新并回写到本地 `.pikpak_token.json`
- **流式边下边传**：下载按 1MB 一块写盘，115 上传按 10MB 分片，全程不把整个文件读进内存
- **按 (文件名 + 大小) 去重**：115 已存在同名同大小文件就跳过，**绝不覆盖**
- **递归保留目录结构**
- **断点续传**：中断后 `.part` 文件保留，下次自动从断点继续
- 单文件失败不中断整体，自动重试 3 次

## 安装

```bash
# 要求 Python 3.8+
pip install requests p115client
```

> 小内存 VPS 提示：p115client 是纯 Python 包，装好后常驻内存大约 30~50MB，传输时再加 10MB 左右缓冲。

## 拿到凭证

### 1) PikPak 凭证（二选一）

**方式 A【推荐】：官方长期访问令牌 (Long-term Access Token)**

1. 浏览器登录 https://mypikpak.com
2. 进入「设置 / 开发者 / API」（不同版本菜单名可能略不同）
3. 生成一个 Long-term Access Token
4. 粘到 `.env` 的 `PIKPAK_LONG_TERM_TOKEN=` 后面

程序会直接用它做 `Authorization: Bearer xxx` 调 API，**不需要换 token、不需要刷新**。

**方式 B：OAuth refresh_token（备选）**

如果你是从 pikpakapi / pikpak-tui / alist 等工具导出的 refresh_token，填到 `PIKPAK_REFRESH_TOKEN=` 即可，程序会自动换短期 access_token 并在轮换时写回 `.pikpak_token.json`。

> 两种凭证不要同时填，脚本按 A → B 顺序取第一个非空的。

### 2) 115 cookies

1. 浏览器登录 https://115.com
2. F12 → Application → Cookies → `https://115.com`
3. 复制 `UID`、`CID`、`SEID`、`KID` 四个值，拼成：
   ```
   UID=1234567890; CID=xxxxx; SEID=xxxxx; KID=xxxxx
   ```

## 配置

```bash
cp .env.example .env
# 编辑 .env 填好上面两个凭证
```

## 运行

```bash
# 先 dry-run 看一遍会传哪些文件，不动 115
python pikpak_to_115.py --dry-run

# 正式同步
python pikpak_to_115.py
```

建议用 nohup / systemd 后台跑：

```bash
nohup python pikpak_to_115.py >> sync.log 2>&1 &
```

## 工作原理

```
PikPak API ──流式下载(1MB块)──> 本地 .part 文件 ──p115client(10MB分片,自动秒传)──> 115
```

- 每进一个 PikPak 目录，先把对应 115 目录的 `(name, size)` 列表拉下来建索引
- 命中索引 → 跳过
- 未命中 → 下载 → 上传 → 删本地 .part
- 下载链接过期、access token 过期、网络抖动都有自动重试

## 文件说明

| 文件 | 作用 |
|---|---|
| `pikpak_to_115.py` | 主程序 |
| `.env` | 你自己填的凭证（已在 .gitignore 应忽略） |
| `.pikpak_token.json` | 自动生成，存当前 access/refresh token，别删 |
| `/tmp/pikpak_sync/*.part` | 下载中的临时文件，传完自动删 |

## 常见问题

**Q: 115 目录里有同名但内容不同的文件会怎样？**
A: 本程序用「文件名+大小」双重判断。同名但大小不同 → 会重新上传一份（115 会自动加 `(1)` 后缀），不会覆盖旧文件。

**Q: PikPak 下载链接过期了怎么办？**
A: 本程序每次下载前都重新调 `GET /drive/v1/files/{id}` 拿最新 `web_content_link`，不存在过期问题。

**Q: 跑一半断电/进程被杀？**
A: `.part` 文件留在 TMP_DIR，下次启动同一文件会自动用 HTTP Range 从断点续传，不用重下。

**Q: 想只同步某种子目录？**
A: 改 `.env` 里 `PIKPAK_SOURCE_DIR=/你要的目录`。

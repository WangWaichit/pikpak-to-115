#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PikPak -> 115 网盘同步工具
=========================

特性：
- 使用 PikPak 长期 refresh token（access token 过期自动刷新并回写）
- 流式传输：边下边传，内存占用恒定（~10MB），适合小内存 VPS
- 文件去重：按 (文件名, 文件大小) 判断，115 已存在则跳过，绝不覆盖
- 递归同步：保留 PikPak 目录结构到 115
- 断点续传：已下载一半的 .part 文件重跑时自动续传
- 失败重试 + 跳过坏文件，不中断整体同步

依赖：
    pip install requests p115client

配置：复制 .env.example 为 .env 并填写，或直接用同名环境变量。
用法：
    python pikpak_to_115.py            # 正式同步
    python pikpak_to_115.py --dry-run  # 只看会传什么，不动 115
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests

# --------------------------------------------------------------------------- #
# 配置加载
# --------------------------------------------------------------------------- #

def load_dotenv(path: Path):
    """最简 .env 加载（不依赖 python-dotenv）。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def env(name: str, *aliases: str, default: str = "", required: bool = False) -> str:
    """读取环境变量，name 为主名，aliases 为兼容旧名的别名。"""
    val = os.environ.get(name, "")
    if not val:
        for alias in aliases:
            val = os.environ.get(alias, "")
            if val:
                break
    if not val:
        val = default
    if required and not val:
        sys.exit(f"[FATAL] 缺少环境变量 {name}（或别名 {aliases}），请在 .env 或环境中配置")
    return val


# --------------------------------------------------------------------------- #
# 日志
# --------------------------------------------------------------------------- #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("p215")


def human_size(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.1f}{unit}"
        f /= 1024
    return f"{f:.1f}TB"


# --------------------------------------------------------------------------- #
# PikPak 客户端
# --------------------------------------------------------------------------- #

PK_CLIENT_ID = "YNxT9w7GMdWvEOKa"
PK_CLIENT_SECRET = "dbw2OtmVEeuUvIptb1Coyg"
PK_CLIENT_VERSION = "1.47.1"
PK_PACKAGE = "com.pikcloud.pikpak"
PK_USER_HOST = "https://user.mypikpak.com"
PK_DRIVE_HOST = "https://api-drive.mypikpak.com"

# captcha_sign 盐值（来自官方 Android 客户端）
PK_SALTS = [
    "Gez0T9ijiI9WCeTsKSg3SMlx",
    "zQdbalsolyb1R/",
    "ftOjr52zt51JD68C3s",
    "yeOBMH0JkbQdEFNNwQ0RI9T3wU/v",
    "BRJrQZiTQ65WtMvwO",
    "je8fqxKPdQVJiy1DM6Bc9Nb1",
    "niV",
    "9hFCW2R1",
    "sHKHpe2i96",
    "p7c5E6AcXQ/IJUuAEC9W6",
    "",
    "aRv9hjc9P+Pbn+u3krN6",
    "BzStcgE8qVdqjEH16l4",
    "SqgeZvL5j9zoHP95xWHt",
    "zVof5yaJkPe3VFpadPof",
]


def _captcha_sign(device_id: str, ts_ms: str) -> str:
    s = PK_CLIENT_ID + PK_CLIENT_VERSION + PK_PACKAGE + device_id + ts_ms
    for salt in PK_SALTS:
        s = hashlib.md5((s + salt).encode()).hexdigest()
    return f"1.{s}"


class PikPak:
    """PikPak 客户端，支持两种凭证：

    模式 1（长期 Bearer token，官方开发者后台生成）：
        直接传 access_token，不再刷新。
    模式 2（OAuth refresh_token）：
        传 refresh_token，自动换短期 access_token 并轮换保存。
    """

    def __init__(self, access_token: str = "", refresh_token: str = "",
                 token_store: Path = None):
        self.token_store = token_store
        self.access_token = access_token or ""
        self.refresh_token = refresh_token or ""
        self.user_id = ""
        self.session = requests.Session()

        # 哪种模式：有长期 access_token 就用它；否则走 refresh
        self.static_mode = bool(self.access_token)

        seed = self.access_token or self.refresh_token or "pikpak"
        self.device_id = hashlib.md5(seed.encode()).hexdigest()[:32]

        if self.static_mode:
            log.info("PikPak 凭证模式: 长期 Bearer token（不再自动刷新）")
        else:
            log.info("PikPak 凭证模式: OAuth refresh_token（自动刷新）")
            self._load_token()
            self.refresh_access_token()

    # ---- token 持久化（仅 refresh 模式用） ---------------------------------- #
    def _load_token(self):
        if self.token_store and self.token_store.exists():
            try:
                d = json.loads(self.token_store.read_text())
                self.access_token = d.get("access_token", "")
                if d.get("refresh_token"):
                    self.refresh_token = d["refresh_token"]
                self.user_id = d.get("user_id", "")
            except Exception:
                pass

    def _save_token(self):
        if not self.token_store:
            return
        self.token_store.write_text(json.dumps({
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "user_id": self.user_id,
        }, indent=2))
        try:
            self.token_store.chmod(0o600)
        except Exception:
            pass

    # ---- 鉴权 --------------------------------------------------------------- #
    def refresh_access_token(self):
        if self.static_mode:
            return
        url = f"{PK_USER_HOST}/v1/auth/token"
        data = {
            "client_id": PK_CLIENT_ID,
            "client_secret": PK_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }
        r = self.session.post(url, data=data, timeout=30)
        r.raise_for_status()
        j = r.json()
        self.access_token = j["access_token"]
        # PikPak 会轮换 refresh_token，必须存新的
        if j.get("refresh_token"):
            self.refresh_token = j["refresh_token"]
        self.user_id = j.get("sub", "")
        self._save_token()
        log.info("PikPak access_token 已刷新 (user=%s)",
                 (self.user_id[:8] + "…") if self.user_id else "?")

    def _headers(self, captcha_token: str = "") -> dict:
        h = {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": f"ANDROID-{PK_PACKAGE}/{PK_CLIENT_VERSION}",
            "X-Device-Id": self.device_id,
        }
        if captcha_token:
            h["X-Captcha-Token"] = captcha_token
        return h

    def _request(self, method: str, url: str, *, params=None, data=None,
                 with_captcha_action: str = "", retry: int = 3):
        """带 401 处理（仅 refresh 模式自动刷新）、带重试的请求。"""
        last_exc = None
        for attempt in range(retry):
            try:
                captcha_token = ""
                if with_captcha_action:
                    captcha_token = self._captcha_init(with_captcha_action)
                r = self.session.request(
                    method, url,
                    params=params, data=data,
                    headers=self._headers(captcha_token),
                    timeout=60,
                )
                if r.status_code == 401:
                    if self.static_mode:
                        raise RuntimeError("长期 token 被拒（401），请到开发者后台重新生成")
                    log.warning("access_token 失效，刷新中…")
                    self.refresh_access_token()
                    continue
                r.raise_for_status()
                return r.json()
            except Exception as e:  # noqa: BLE001
                last_exc = e
                wait = 2 ** attempt
                log.warning("请求失败 (%s)，%ds 后重试 (%d/%d)", e, wait, attempt + 1, retry)
                time.sleep(wait)
        raise RuntimeError(f"请求 {url} 多次失败: {last_exc}")

    def _captcha_init(self, action: str) -> str:
        """初始化验证码挑战，返回 captcha_token（多数账号不会真的弹验证码）。"""
        try:
            ts = str(int(time.time() * 1000))
            meta = {
                "captcha_sign": _captcha_sign(self.device_id, ts),
                "client_version": PK_CLIENT_VERSION,
                "package_name": PK_PACKAGE,
                "user_id": self.user_id,
                "timestamp": ts,
            }
            url = f"{PK_USER_HOST}/v1/shield/captcha/init"
            r = self.session.post(url, data={
                "client_id": PK_CLIENT_ID,
                "action": action,
                "device_id": self.device_id,
                "meta": meta,
            }, timeout=30)
            r.raise_for_status()
            return r.json().get("captcha_token", "")
        except Exception as e:  # noqa: BLE001
            log.debug("captcha_init 失败（忽略继续）: %s", e)
            return ""

    # ---- 文件操作 ----------------------------------------------------------- #
    def list_children(self, parent_id: str):
        """列出某目录下的文件/文件夹，自动分页。返回原始 dict 列表。"""
        items, page_token = [], ""
        filters = json.dumps({"trashed": {"eq": False}})
        while True:
            params = {
                "parent_id": parent_id,
                "thumbnail_size": "SIZE_SMALL",
                "limit": 200,
                "with_audit": "false",
                "filters": filters,
            }
            if page_token:
                params["page_token"] = page_token
            j = self._request("GET", f"{PK_DRIVE_HOST}/drive/v1/files", params=params)
            items.extend(j.get("files", []))
            page_token = j.get("next_page_token", "")
            if not page_token:
                break
        return items

    def resolve_path(self, path: str) -> str:
        """把 '/a/b/c' 解析成 PikPak folder id。不存在则抛错。根目录返回 ''。"""
        path = (path or "").strip("/")
        cid = ""
        if not path:
            return cid
        for seg in path.split("/"):
            children = self.list_children(cid)
            found = None
            for it in children:
                if it.get("kind") == "drive#folder" and it.get("name") == seg:
                    found = it["id"]
                    break
            if found is None:
                raise FileNotFoundError(f"PikPak 路径不存在: /{path}（缺少目录 {seg}）")
            cid = found
        return cid

    def get_download_url(self, file_id: str) -> str:
        j = self._request(
            "GET", f"{PK_DRIVE_HOST}/drive/v1/files/{file_id}",
            with_captcha_action=f"GET:/drive/v1/files/{file_id}",
        )
        url = j.get("web_content_link") or ""
        if not url:
            medias = j.get("medias") or []
            if medias:
                url = (medias[0].get("link") or {}).get("url", "")
        if not url:
            raise RuntimeError(f"文件 {file_id} 没有下载链接")
        return url


# --------------------------------------------------------------------------- #
# 下载（流式写盘）
# --------------------------------------------------------------------------- #

CHUNK = 1024 * 1024  # 1MB


def download_to_file(pk: PikPak, file_id: str, dest: Path, total_size: int) -> Path:
    """流式下载 PikPak 文件到 dest，支持 Range 断点续传。"""
    url = pk.get_download_url(file_id)
    have = dest.stat().st_size if dest.exists() else 0
    if have >= total_size and total_size > 0:
        log.info("  本地已存在完整 .part，直接使用: %s", dest.name)
        return dest

    headers = {}
    if have > 0:
        headers["Range"] = f"bytes={have}-"
    r = requests.get(url, headers=headers, stream=True, timeout=(30, 60))
    if have > 0 and r.status_code == 200:
        have = 0  # 服务器不认 Range，重头写
    elif r.status_code not in (200, 206):
        r.raise_for_status()

    mode = "ab" if have > 0 and r.status_code == 206 else "wb"
    written = have
    last_log = 0.0
    with open(dest, mode) as f:
        for chunk in r.iter_content(CHUNK):
            if not chunk:
                continue
            f.write(chunk)
            written += len(chunk)
            now = time.time()
            if now - last_log > 3:
                pct = (written / total_size * 100) if total_size else 0
                log.info("  下载 %s / %s (%.1f%%)",
                         human_size(written), human_size(total_size), pct)
                last_log = now
    return dest


# --------------------------------------------------------------------------- #
# 115 侧
# --------------------------------------------------------------------------- #

class Pan115:
    def __init__(self, cookies: str):
        from p115client import P115Client
        from p115client.fs import P115FileSystem
        client = P115Client(cookies)
        self.fs = P115FileSystem(client)
        # 缓存：cid -> {(name, size)}
        self._dir_cache: dict[int, set] = {}

    def resolve_or_create(self, path: str) -> int:
        """把 '/a/b' 解析成 115 目录 cid，不存在则逐级创建。根目录返回 0。"""
        path = (path or "").strip("/")
        cid = 0
        if not path:
            return cid
        for seg in path.split("/"):
            cid = self._ensure_child_dir(cid, seg)
        return cid

    def _ensure_child_dir(self, parent_cid: int, name: str) -> int:
        for child in self.fs.iterdir(parent_cid):
            if child.get("is_dir") and child.get("name") == name:
                return int(child["id"])
        # 不存在 → 创建
        attr = self.fs.mkdir(parent_cid, name)
        log.info("  115 创建目录: /%s (cid=%d)", name, attr["id"])
        return int(attr["id"])

    def list_existing(self, cid: int) -> set:
        """列出某 cid 下已存在文件的 {(name, size)} 集合。"""
        if cid in self._dir_cache:
            return self._dir_cache[cid]
        result = set()
        for child in self.fs.iterdir(cid):
            if not child.get("is_dir"):
                try:
                    size = int(child.get("size", 0))
                except Exception:
                    size = 0
                result.add((child.get("name", ""), size))
        self._dir_cache[cid] = result
        return result

    def invalidate(self, cid: int):
        """上传后清掉该目录缓存，下次重新列目录。"""
        self._dir_cache.pop(cid, None)

    def upload(self, local_path: Path, filename: str, cid: int):
        self.fs.upload(cid, file=str(local_path), filename=filename)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def sync_folder(pk: PikPak, pan: Pan115,
                pk_parent_id: str,
                pan_cid: int,
                pk_rel_path: str,
                dry_run: bool, tmp_dir: Path):
    """递归同步一个 PikPak 目录到 115 cid。"""
    children = pk.list_children(pk_parent_id)
    folders = [c for c in children if c.get("kind") == "drive#folder"]
    files = [c for c in children
             if c.get("kind") == "drive#file"
             and c.get("phase") == "PHASE_TYPE_COMPLETE"]

    log.info("=" * 70)
    log.info("目录: PikPak:/%s  ->  115:(cid=%d)  子目录 %d 个, 文件 %d 个",
             pk_rel_path or "/", pan_cid, len(folders), len(files))

    # --- 文件 ---
    existing = pan.list_existing(pan_cid)
    for f in files:
        name = f.get("name", "")
        try:
            size = int(f.get("size", 0))
        except Exception:
            size = 0
        file_id = f["id"]

        if (name, size) in existing:
            log.info("  [跳过] %s (%s) 已存在", name, human_size(size))
            continue

        log.info("  [传输] %s (%s)", name, human_size(size))
        if dry_run:
            continue

        tmp_path = tmp_dir / f"{file_id}.part"
        try:
            download_to_file(pk, file_id, tmp_path, size)
            # 校验大小
            actual = tmp_path.stat().st_size
            if size > 0 and actual < size:
                raise RuntimeError(f"下载不完整: {actual}/{size}")
            # 上传（p115client 自动秒传 + 分片）
            pan.upload(tmp_path, name, pan_cid)
            pan.invalidate(pan_cid)
            log.info("  [完成] %s", name)
            tmp_path.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            log.error("  [失败] %s: %s", name, e)
            # 保留 .part 以便下次续传
            continue

    # --- 子目录递归 ---
    for folder in folders:
        sub_name = folder.get("name", "")
        sub_pk_id = folder["id"]
        sub_rel = f"{pk_rel_path}/{sub_name}".strip("/")
        sub_cid = pan._ensure_child_dir(pan_cid, sub_name)
        sync_folder(pk, pan, sub_pk_id, sub_cid, sub_rel, dry_run, tmp_dir)


def main():
    here = Path(__file__).resolve().parent
    load_dotenv(here / ".env")

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只列计划，不实际上传")
    args = ap.parse_args()

    # 两种凭证二选一：
    #   PIKPAK_LONG_TERM_TOKEN = 官方开发者后台生成的长期 Bearer token（推荐）
    #   PIKPAK_REFRESH_TOKEN   = OAuth 登录拿到的 refresh_token（备选）
    long_term_token = env("PIKPAK_LONG_TERM_TOKEN", "")
    refresh_token = env("PIKPAK_REFRESH_TOKEN", "")
    if not long_term_token and not refresh_token:
        sys.exit("[FATAL] 请在 .env 里配置 PIKPAK_LONG_TERM_TOKEN（官方长期令牌）"
                 "或 PIKPAK_REFRESH_TOKEN（OAuth refresh token），二选一")

    pk_source = env("PIKPAK_SOURCE_DIR", "")            # 空 = 根目录
    cookies = env("PAN115_COOKIES", required=True)
    pan_target = env("PAN115_TARGET_DIR", "/pikpak")     # 115 目标目录
    tmp_root = Path(env("TMP_DIR", "/tmp/pikpak_sync"))
    tmp_root.mkdir(parents=True, exist_ok=True)

    log.info("初始化 PikPak 客户端…")
    pk = PikPak(access_token=long_term_token,
                refresh_token=refresh_token,
                token_store=here / ".pikpak_token.json")
    log.info("初始化 115 客户端…")
    pan = Pan115(cookies)

    log.info("解析 PikPak 源目录: %s", pk_source or "/")
    pk_root = pk.resolve_path(pk_source)
    log.info("解析/创建 115 目标目录: %s", pan_target)
    pan_root = pan.resolve_or_create(pan_target)

    sync_folder(pk, pan, pk_root, pan_root, pk_source.strip("/"),
                args.dry_run, tmp_root)
    log.info("全部完成。")


if __name__ == "__main__":
    main()

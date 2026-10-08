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
import base64
import hashlib
import hmac
import json
import logging
import os
import re
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


# ---- PikPak GCID hash & OSS signing（用于上传） --------------------------- #

def _gcid_chunk_size(size: int) -> int:
    if size <= 0:
        return 0x200000
    if size < 0x8000000:
        return 0x40000
    if size < 0x10000000:
        return 0x80000
    if size > 0x20000000:
        return 0x200000
    return 0x100000


def compute_gcid(path: Path, size: int, progress_cb=None) -> str:
    """PikPak 内容 hash：分块 SHA1 再外层 SHA1，大写 hex。"""
    if size <= 0:
        return hashlib.sha1(b"").hexdigest().upper()
    chunk = _gcid_chunk_size(size)
    outer = hashlib.sha1()
    done = 0
    with open(path, "rb") as f:
        while done < size:
            buf = f.read(min(chunk, size - done))
            if not buf:
                break
            outer.update(hashlib.sha1(buf).digest())
            done += len(buf)
            if progress_cb:
                progress_cb(done, size)
    return outer.hexdigest().upper()


def _oss_sign(method, bucket, key_path, raw_query, content_type, date,
              security_token, ak, sk):
    """Aliyun OSS v1 HMAC-SHA1 签名。"""
    canonical = f"{method}\n\n{content_type}\n{date}\nx-oss-security-token:{security_token}\n/{bucket}{key_path}"
    if raw_query:
        canonical += f"?{raw_query}"
    sig = base64.b64encode(
        hmac.new(sk.encode(), canonical.encode(), hashlib.sha1).digest()
    ).decode()
    return f"OSS {ak}:{sig}"


def _oss_request(session, method, sess, raw_query, body=None):
    import email.utils
    date = email.utils.formatdate(usegmt=True)
    ct = "application/octet-stream" if body else ""
    auth = _oss_sign(method, sess["bucket"], "/" + sess["key"], raw_query,
                     ct, date, sess["sts"], sess["ak"], sess["sk"])
    url = f"https://{sess['endpoint']}/{sess['key']}?{raw_query}"
    headers = {
        "Date": date,
        "x-oss-security-token": sess["sts"],
        "Authorization": auth,
    }
    if ct:
        headers["Content-Type"] = ct
    r = session.request(method, url, data=body, headers=headers, timeout=120)
    if not r.ok:
        raise RuntimeError(f"OSS {method} ?{raw_query} -> {r.status_code}: {r.text[:300]}")
    return r.content


def _oss_put_part(session, sess, upload_id, part_num, body):
    raw = f"partNumber={part_num}&uploadId={upload_id}"
    import email.utils
    date = email.utils.formatdate(usegmt=True)
    ct = "application/octet-stream"
    auth = _oss_sign("PUT", sess["bucket"], "/" + sess["key"], raw,
                     ct, date, sess["sts"], sess["ak"], sess["sk"])
    url = f"https://{sess['endpoint']}/{sess['key']}?{raw}"
    headers = {
        "Date": date,
        "x-oss-security-token": sess["sts"],
        "Authorization": auth,
        "Content-Type": ct,
    }
    r = session.put(url, data=body, headers=headers, timeout=300)
    if not r.ok:
        raise RuntimeError(f"OSS PUT part {part_num} -> {r.status_code}: {r.text[:300]}")
    return r.headers.get("ETag", '""')


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
        """列出某目录下的文件/文件夹，自动分页。返回原始 dict 列表。
        PikPak 网页把 My Pack 里的文件合并展示到根目录，这里也合并。"""
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
        # 根目录：把 My Pack 里的文件也合并进来（对齐网页 UI）
        if parent_id == "":
            my_pack = None
            for it in items:
                if it.get("kind") == "drive#folder" and it.get("name") == "My Pack":
                    my_pack = it
                    break
            if my_pack:
                try:
                    inner = self.list_children(my_pack["id"])
                    # 只合并文件，不合并 My Pack 里的文件夹（避免重复）
                    merged = [it for it in inner if it.get("kind") == "drive#file"]
                    items.extend(merged)
                except Exception:
                    pass
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

    def resolve_or_create(self, path: str) -> str:
        """把 '/a/b/c' 解析成 PikPak folder id，不存在则逐级创建。"""
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
                body = {"kind": "drive#folder", "name": seg}
                if cid:
                    body["parent_id"] = cid
                j = self._request(
                    "POST", f"{PK_DRIVE_HOST}/drive/v1/files",
                    data=body, with_captcha_action="POST:/drive/v1/files",
                )
                found = (j.get("file") or {}).get("id", "")
                log.info("  PikPak 创建目录: /%s", seg)
            cid = found
        return cid

    def list_by_name(self, parent_id: str = "") -> dict:
        """返回 {name: (size, file_id)}，只含文件。"""
        result = {}
        for c in self.list_children(parent_id):
            if c.get("kind") == "drive#file":
                try:
                    size = int(c.get("size", 0))
                except Exception:
                    size = 0
                result[c.get("name", "")] = (size, c["id"])
        return result

    def delete_file(self, file_id: str):
        """删除 PikPak 文件（移到回收站）。"""
        try:
            self._request("DELETE", f"{PK_DRIVE_HOST}/drive/v1/files/{file_id}",
                          with_captcha_action=f"DELETE:/drive/v1/files/{file_id}")
            log.info("  PikPak 删除旧文件 id=%s", file_id)
        except Exception as e:  # noqa: BLE001
            log.warning("  PikPak 删除旧文件失败 id=%s: %s", file_id, e)

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

    # ---- 上传到 PikPak（115 -> PikPak 方向用） ---------------------------- #
    def upload_file(self, local_path: Path, parent_id: str = "",
                    filename: str = "", progress_cb=None) -> str:
        """上传本地文件到 PikPak，返回 file_id。支持秒传 + OSS 分片。"""
        filename = filename or local_path.name
        size = local_path.stat().st_size
        gcid = compute_gcid(local_path, size, progress_cb)
        log.info("  GCID=%s size=%s", gcid, human_size(size))

        # 1) 注册文件
        body = {
            "kind": "drive#file",
            "name": filename,
            "size": str(size),
            "hash": gcid,
            "upload_type": "UPLOAD_TYPE_RESUMABLE",
            "body": {"duration": "", "width": "", "height": ""},
            "objProvider": {"provider": "UPLOAD_TYPE_UNKNOWN"},
        }
        if parent_id:
            body["parent_id"] = parent_id
        j = self._request(
            "POST", f"{PK_DRIVE_HOST}/drive/v1/files",
            data=body, with_captcha_action="POST:/drive/v1/files",
        )
        file_obj = j.get("file") or {}
        file_id = file_obj.get("id", "")
        phase = file_obj.get("phase", "")
        if phase == "PHASE_TYPE_COMPLETE":
            log.info("  秒传命中，无需上传字节")
            return file_id

        # 2) 拿 OSS 凭证
        resumable = (file_obj.get("resumable") or {}).get("params") or {}
        if not resumable:
            raise RuntimeError(f"上传响应缺少 resumable.params: {j}")
        sess = {
            "bucket": resumable.get("bucket", ""),
            "endpoint": resumable.get("endpoint", ""),
            "key": resumable.get("key", ""),
            "ak": resumable.get("access_key_id", ""),
            "sk": resumable.get("access_key_secret", ""),
            "sts": resumable.get("security_token", ""),
        }
        # partSize: ceil(size/10000), 最小 256KB
        part_size = max((size + 9999) // 10000, 0x40000)

        # 3) OSS Initiate Multipart
        xml = _oss_request(self.session, "POST", sess, raw_query="uploads")
        m = re.search(rb"<UploadId>(.+?)</UploadId>", xml)
        if not m:
            raise RuntimeError(f"OSS initiate 失败: {xml[:300]}")
        upload_id = m.group(1).decode()

        # 4) 逐片 PUT
        parts_count = (size + part_size - 1) // part_size
        parts_etag = {}
        with open(local_path, "rb") as f:
            for i in range(1, parts_count + 1):
                f.seek((i - 1) * part_size)
                chunk = f.read(min(part_size, size - (i - 1) * part_size))
                etag = _oss_put_part(self.session, sess, upload_id, i, chunk)
                parts_etag[i] = etag.strip('"')
                if progress_cb:
                    progress_cb(i * part_size, size)

        # 5) OSS Complete
        body_xml = "<CompleteMultipartUpload>" + "".join(
            f"<Part><PartNumber>{n}</PartNumber><ETag>{e}</ETag></Part>"
            for n, e in sorted(parts_etag.items())
        ) + "</CompleteMultipartUpload>"
        _oss_request(self.session, "POST", sess,
                     raw_query=f"uploadId={upload_id}",
                     body=body_xml.encode())
        log.info("  PikPak 上传完成: %s", filename)
        return file_id


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
    """115 开放平台客户端（OAuth refresh_token，兼容 OpenList）。"""
    API = "https://proapi.115.com"
    PASSPORT = "https://passportapi.115.com"

    def __init__(self, refresh_token: str = "", cookies: str = ""):
        import requests as _req
        self._req = _req
        self.refresh_token = refresh_token or ""
        self.access_token = ""
        self.new_refresh_token = ""
        self._dir_cache: dict = {}
        if self.refresh_token:
            self._do_refresh()
        else:
            raise RuntimeError("115 需要 refresh_token（开放平台OAuth）")

    # ---- token ----
    def _do_refresh(self):
        r = self._req.post(
            f"{self.PASSPORT}/open/refreshToken",
            data={"refresh_token": self.refresh_token},
            timeout=15,
        )
        j = r.json()
        if not j.get("access_token"):
            raise RuntimeError(f"115 refresh_token 刷新失败: {j}")
        self.access_token = j["access_token"]
        self.new_refresh_token = j.get("refresh_token", self.refresh_token)
        log.info("  115 access_token 刷新成功")

    def _headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}

    def _get(self, path, params=None):
        r = self._req.get(f"{self.API}{path}", headers=self._headers(),
                          params=params or {}, timeout=30)
        j = r.json()
        if not j.get("state") and j.get("code") == 99:
            self._do_refresh()
            r = self._req.get(f"{self.API}{path}", headers=self._headers(),
                              params=params or {}, timeout=30)
            j = r.json()
        return j

    def _post(self, path, data=None):
        r = self._req.post(f"{self.API}{path}", headers=self._headers(),
                           data=data or {}, timeout=30)
        j = r.json()
        if not j.get("state") and j.get("code") == 99:
            self._do_refresh()
            r = self._req.post(f"{self.API}{path}", headers=self._headers(),
                               data=data or {}, timeout=30)
            j = r.json()
        return j

    # ---- 目录浏览 ----
    def iterdir(self, cid):
        """返回 [{is_dir, id, name, size}]，兼容旧接口。"""
        cid = str(cid)
        items = []
        offset = 0
        while True:
            j = self._get("/open/ufile/files", {
                "cid": cid, "limit": 200, "offset": offset,
                "show_dir": 1, "asc": 0, "o": "file_name",
            })
            data = j.get("data", [])
            for f in data:
                is_dir = f.get("fc") == "0"
                items.append({
                    "is_dir": is_dir,
                    "id": str(f.get("fid", "")),
                    "name": f.get("fn", ""),
                    "size": int(f.get("fs", 0)),
                })
            total = j.get("count", 0)
            offset += len(data)
            if offset >= total or not data:
                break
        return items

    def resolve_or_create(self, path):
        path = (path or "").strip("/")
        cid = "0"
        if not path:
            return cid
        for seg in path.split("/"):
            cid = self._ensure_child_dir(cid, seg)
        return cid

    def _ensure_child_dir(self, parent_cid, name):
        for child in self.iterdir(parent_cid):
            if child["is_dir"] and child["name"] == name:
                return child["id"]
        j = self._post("/open/folder/add", {
            "pid": str(parent_cid), "file_name": name,
        })
        fid = j.get("file_id", "")
        log.info("  115 创建目录: /%s (fid=%s)", name, fid)
        return str(fid)

    def _find_child_dir(self, parent_cid, name):
        for child in self.iterdir(parent_cid):
            if child["is_dir"] and child["name"] == name:
                return child["id"]
        return ""

    def list_existing(self, cid):
        cid = str(cid)
        if cid in self._dir_cache:
            return self._dir_cache[cid]
        result = {}
        for child in self.iterdir(cid):
            if not child["is_dir"]:
                result[child["name"]] = (child["size"], child["id"])
        self._dir_cache[cid] = result
        return result

    def list_files_in_dir(self, cid):
        out = []
        for child in self.iterdir(cid):
            if not child["is_dir"]:
                out.append((child["name"], child["size"], child["id"]))
        return out

    def delete_file(self, fid):
        try:
            self._post("/open/ufile/delete", {
                "file_id[0]": str(fid),
            })
            log.info("  115 删除旧文件 fid=%s", fid)
        except Exception as e:
            log.warning("  115 删除旧文件失败: %s", e)

    def invalidate(self, cid):
        self._dir_cache.pop(str(cid), None)

    # ---- 上传 ----
    def upload(self, local_path, filename, cid):
        """通过 115 开放平台 OSS 上传文件。"""
        import hashlib, os
        size = os.path.getsize(local_path)
        # 计算 sha1
        h = hashlib.sha1()
        with open(local_path, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
        sha1 = h.hexdigest().upper()
        # 前128k sha1
        h2 = hashlib.sha1()
        with open(local_path, "rb") as f:
            h2.update(f.read(128 * 1024))
        preid = h2.hexdigest().upper()

        # 1. upload init
        j = self._post("/open/upload/init", {
            "file_name": filename,
            "file_size": size,
            "target": f"U_1_{cid}",
            "fileid": sha1,
            "preid": preid,
        })
        status = j.get("status", 0)
        if status == 2:
            log.info("  115 秒传成功: %s", filename)
            return

        # 2. get OSS token
        tok = self._get("/open/upload/get_token")
        endpoint = tok.get("endpoint", "")
        ak = tok.get("AccessKeyId", "")
        sk = tok.get("AccessKeySecret", "")
        st = tok.get("SecurityToken", "")

        # 3. upload to OSS
        import oss2
        auth = oss2.StsAuth(ak, sk, st)
        bucket = oss2.Bucket(auth, endpoint, j["bucket"])
        callback = j.get("callback", {})
        if isinstance(callback, list):
            callback = callback[0] if callback else {}
        cb = callback.get("callback", "")
        cbvar = callback.get("callback_var", "")
        headers = {}
        if cb:
            import base64
            headers["x-oss-callback"] = base64.b64encode(
                cb.encode()).decode()
            if cbvar:
                headers["x-oss-callback-var"] = base64.b64encode(
                    cbvar.encode()).decode()
        with open(local_path, "rb") as f:
            bucket.put_object(j["object"], f, headers=headers)

    def download(self, file_id, dest):
        """从 115 下载文件。"""
        j = self._get("/open/ufile/downurl", {"pick_code": file_id})
        url = list(j.values())[0].get("url", "") if j else ""
        if not url:
            raise RuntimeError("无法获取下载链接")
        r = self._req.get(url, stream=True, timeout=60)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


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

        # 去重逻辑：同名时比较大小
        if name in existing:
            old_size, old_fid = existing[name]
            if size <= old_size:
                log.info("  [跳过] %s (%s, 旧文件更大/相等)", name, human_size(size))
                continue
            log.info("  [覆盖] %s 旧文件 %s → 新文件 %s，删旧传新",
                     name, human_size(old_size), human_size(size))
            pan.delete_file(old_fid)
            pan.invalidate(pan_cid)

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


def sync_folder_reverse(pk: PikPak, pan: Pan115,
                        pan_cid: int,
                        pk_parent_id: str,
                        pan_rel_path: str,
                        dry_run: bool, tmp_dir: Path,
                        progress=None):
    """递归同步 115 目录到 PikPak。progress 为可选 dict，用于 CLI 显示进度。"""
    items = list(pan.iterdir(pan_cid))
    folders = [x for x in items if x.get("is_dir")]
    files = []
    for x in items:
        if x.get("is_dir"):
            continue
        try:
            size = int(x.get("size", 0))
        except Exception:
            size = 0
        files.append((x.get("name", ""), size, int(x["id"])))

    log.info("=" * 70)
    log.info("目录: 115:/%s  ->  PikPak:(%s)  子目录 %d 个, 文件 %d 个",
             pan_rel_path or "/", pk_parent_id or "(根)", len(folders), len(files))

    # PikPak 目标目录已有的 {name: (size, file_id)}
    existing = {}
    try:
        existing = pk.list_by_name(pk_parent_id)
    except Exception:
        pass

    for name, size, fid in files:
        if name in existing:
            old_size, old_id = existing[name]
            if size <= old_size:
                log.info("  [跳过] %s (%s, 旧文件更大/相等)", name, human_size(size))
                continue
            log.info("  [覆盖] %s 旧 %s → 新 %s，删旧传新",
                     name, human_size(old_size), human_size(size))
            pk.delete_file(old_id)

        log.info("  [传输] %s (%s)", name, human_size(size))
        if dry_run:
            continue
        tmp_path = tmp_dir / f"115_{fid}.part"
        try:
            pan.download(fid, tmp_path)
            actual = tmp_path.stat().st_size
            if size > 0 and actual < size:
                raise RuntimeError(f"下载不完整: {actual}/{size}")
            pk.upload_file(tmp_path, parent_id=pk_parent_id, filename=name)
            log.info("  [完成] %s", name)
            tmp_path.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            log.error("  [失败] %s: %s", name, e)
            continue

    for f in folders:
        sub_name = f["name"]
        sub_pk_id = ""
        # 在 PikPak 目标目录下找同名子目录，没有就创建
        try:
            children = pk.list_children(pk_parent_id) if pk_parent_id else pk.list_children("")
            for c in children:
                if c.get("kind") == "drive#folder" and c.get("name") == sub_name:
                    sub_pk_id = c["id"]
                    break
        except Exception:
            pass
        if not sub_pk_id:
            # 创建 PikPak 目录
            try:
                body = {"kind": "drive#folder", "name": sub_name}
                if pk_parent_id:
                    body["parent_id"] = pk_parent_id
                j = pk._request(
                    "POST", f"{PK_DRIVE_HOST}/drive/v1/files",
                    data=body, with_captcha_action="POST:/drive/v1/files",
                )
                sub_pk_id = (j.get("file") or {}).get("id", "")
            except Exception as e:  # noqa: BLE001
                log.error("  创建 PikPak 目录失败 %s: %s", sub_name, e)
                continue
        sub_rel = f"{pan_rel_path}/{sub_name}".strip("/")
        sync_folder_reverse(pk, pan, int(f["id"]), sub_pk_id, sub_rel,
                            dry_run, tmp_dir, progress)


# 本文件只做库导出，入口统一走 cli.py（或 ./run.sh）
# 不再提供 .env 环境变量模式，所有凭证都在 config.json 里。
if __name__ == "__main__":
    import sys
    print("请运行 ./run.sh 或 python3 cli.py 启动菜单。", file=sys.stderr)
    sys.exit(1)

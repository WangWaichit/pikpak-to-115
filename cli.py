#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PikPak -> 115 交互式 CLI
========================

启动后:
1. 第一次会引导你填 PikPak 长期令牌 + 115 cookies，存到 config.json
2. 之后进入主循环，输入 menu / pikpak 召出目录选择
3. 在 PikPak 目录树里选源，在 115 目录树里选目标，回车即同步
"""

import json
import sys
from pathlib import Path

from pikpak_to_115 import (
    PikPak, Pan115, sync_folder, load_dotenv,
    env, human_size, log,
)

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    try:
        CONFIG_PATH.chmod(0o600)
    except Exception:
        pass


def ask(prompt: str, default: str = "", required: bool = False, hidden: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            if hidden:
                import getpass
                val = getpass.getpass(prompt + suffix + ": ").strip()
            else:
                val = input(prompt + suffix + ": ").strip()
        except EOFError:
            return default
        if not val:
            val = default
        if val or not required:
            return val
        print("  ! 这一项必填")


def setup_wizard(cfg: dict) -> dict:
    print("\n===== 首次配置 =====")
    print("(直接回车用上次的值)")
    cfg["pikpak_token"] = ask(
        "PikPak 长期访问令牌 (Long-term Access Token)",
        default=cfg.get("pikpak_token", ""), required=True)
    cfg["pan115_cookies"] = ask(
        "115 cookies (UID=..;CID=..;SEID=..;KID=..)",
        default=cfg.get("pan115_cookies", ""), required=True)
    cfg["pan115_target"] = ask(
        "115 默认目标目录", default=cfg.get("pan115_target", "/pikpak"))
    cfg["pikpak_source"] = ask(
        "PikPak 默认源目录 (留空=根目录)", default=cfg.get("pikpak_source", ""))
    save_config(cfg)
    print(f"配置已保存到 {CONFIG_PATH}\n")
    return cfg


# --------------------------------------------------------------------------- #
# 目录浏览器（通用，PikPak 和 115 共用一套交互）
# --------------------------------------------------------------------------- #

class DirEntry:
    __slots__ = ["name", "id", "is_dir", "size"]
    def __init__(self, name, id, is_dir=True, size=0):
        self.name = name
        self.id = id
        self.is_dir = is_dir
        self.size = size


def browse_pikpak(pk: PikPak, start_path: str = "") -> str:
    """交互式浏览 PikPak，返回选中的目录路径（如 /a/b）。"""
    # 先定位到起始路径
    cid = pk.resolve_path(start_path)
    cur = start_path.strip("/")
    while True:
        children = pk.list_children(cid)
        folders = [c for c in children if c.get("kind") == "drive#folder"]
        files = [c for c in children
                 if c.get("kind") == "drive#file"
                 and c.get("phase") == "PHASE_TYPE_COMPLETE"]
        print(f"\n--- PikPak 当前: /{cur or ''} ---")
        print(f"    ({len(folders)} 个目录, {len(files)} 个文件)")
        for i, f in enumerate(folders, 1):
            print(f"  [{i}] 📁 {f['name']}/")
        print(f"  [..]  返回上一级")
        print(f"  [.]  👉 选中【当前目录 /{cur or ''}】作为源")
        print(f"  [q]  取消")
        choice = input("请选择: ").strip()
        if choice in ("q", "Q", "quit", "exit"):
            return ""
        if choice == "..":
            if cur:
                cur = "/".join(cur.split("/")[:-1])
                cid = pk.resolve_path(cur)
            continue
        if choice == "." or choice == "":
            return "/" + cur
        if choice.isdigit() and 1 <= int(choice) <= len(folders):
            picked = folders[int(choice) - 1]
            cur = f"{cur}/{picked['name']}".strip("/")
            cid = picked["id"]
            continue
        print("  ? 无效输入")


def browse_pan115(pan: Pan115, start_path: str = "") -> str:
    """交互式浏览 115，返回选中的目录路径。"""
    # 解析起点
    cid = 0
    cur = start_path.strip("/")
    if cur:
        for seg in cur.split("/"):
            cid = pan._ensure_child_dir(cid, seg)

    while True:
        items = list(pan.fs.iterdir(cid))
        dirs = [x for x in items if x.get("is_dir")]
        files = [x for x in items if not x.get("is_dir")]
        print(f"\n--- 115 当前: /{cur or ''} ---")
        print(f"    ({len(dirs)} 个目录, {len(files)} 个文件)")
        for i, d in enumerate(dirs, 1):
            print(f"  [{i}] 📁 {d['name']}/")
        print(f"  [..]  返回上一级")
        print(f"  [.]  👉 选中【当前目录 /{cur or ''}】作为目标")
        print(f"  [q]  取消")
        choice = input("请选择: ").strip()
        if choice in ("q", "Q", "quit", "exit"):
            return ""
        if choice == "..":
            if cur:
                cur = "/".join(cur.split("/")[:-1])
                # 重新解析
                cid = 0
                if cur:
                    for seg in cur.split("/"):
                        cid = pan._ensure_child_dir(cid, seg)
            continue
        if choice == "." or choice == "":
            return "/" + cur
        if choice.isdigit() and 1 <= int(choice) <= len(dirs):
            picked = dirs[int(choice) - 1]
            cur = f"{cur}/{picked['name']}".strip("/")
            cid = int(picked["id"])
            continue
        print("  ? 无效输入")


# --------------------------------------------------------------------------- #
# 主循环
# --------------------------------------------------------------------------- #

def show_help():
    print("""
可用命令:
  menu / pikpak   召出目录选择菜单（选源 -> 选目标 -> 同步）
  sync            用上次记录的源/目标直接同步
  dryrun          用上次记录的源/目标预览
  config          重新配置凭证
  status          显示当前配置
  help            显示本帮助
  quit / exit     退出
""")


def main():
    here = HERE
    load_dotenv(here / ".env")
    # 环境变量优先（命令行传的）
    cfg = load_config()
    if env("PIKPAK_LONG_TERM_TOKEN"):
        cfg["pikpak_token"] = env("PIKPAK_LONG_TERM_TOKEN")
    if env("PAN115_COOKIES"):
        cfg["pan115_cookies"] = env("PAN115_COOKIES")

    if not cfg.get("pikpak_token") or not cfg.get("pan115_cookies"):
        cfg = setup_wizard(cfg)

    print("\n连接 PikPak 和 115 ...")
    pk = PikPak(access_token=cfg["pikpak_token"],
                token_store=here / ".pikpak_token.json")
    pan = Pan115(cfg["pan115_cookies"])
    print("连接成功。\n")

    last_pk = cfg.get("pikpak_source", "")
    last_pan = cfg.get("pan115_target", "/pikpak")

    show_help()
    while True:
        try:
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break
        if not cmd:
            continue

        if cmd in ("quit", "exit", "q"):
            break
        elif cmd in ("help", "h", "?"):
            show_help()
        elif cmd == "config":
            cfg = setup_wizard(cfg)
        elif cmd == "status":
            print(f"  PikPak 源: {last_pk or '(根目录)'}")
            print(f"  115 目标: {last_pan}")
        elif cmd in ("menu", "pikpak", "m"):
            pk_path = browse_pikpak(pk, last_pk)
            if not pk_path:
                print("已取消。")
                continue
            pan_path = browse_pan115(pan, last_pan)
            if not pan_path:
                print("已取消。")
                continue
            print(f"\n✅ 源: PikPak{pk_path}")
            print(f"✅ 目标: 115{pan_path}")
            ok = input("开始同步? [Y/n]: ").strip().lower()
            if ok in ("n", "no"):
                continue
            last_pk, last_pan = pk_path.strip("/"), pan_path.strip("/")
            cfg["pikpak_source"], cfg["pan115_target"] = last_pk, last_pan
            save_config(cfg)
            _do_sync(pk, pan, last_pk, last_pan, dry_run=False)
        elif cmd == "sync":
            _do_sync(pk, pan, last_pk, last_pan, dry_run=False)
        elif cmd == "dryrun":
            _do_sync(pk, pan, last_pk, last_pan, dry_run=True)
        else:
            print(f"  ? 未知命令: {cmd}（输入 help 查看）")


def _do_sync(pk, pan, pk_source, pan_target, dry_run):
    try:
        pk_root = pk.resolve_path(pk_source)
        pan_root = pan.resolve_or_create(pan_target)
    except Exception as e:  # noqa: BLE001
        print(f"路径解析失败: {e}")
        return
    tmp_root = (here / ".tmp_sync")
    tmp_root.mkdir(exist_ok=True)
    sync_folder(pk, pan, pk_root, pan_root, pk_source.strip("/"),
                dry_run=dry_run, tmp_dir=tmp_root)


if __name__ == "__main__":
    main()

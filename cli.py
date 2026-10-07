#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PikPak <-> 115 交互式菜单
"""

import json
import threading
import time
from pathlib import Path

from pikpak_to_115 import (
    PikPak, Pan115, sync_folder, sync_folder_reverse,
    load_dotenv, human_size,
)

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
TMP_DIR = HERE / ".tmp_sync"
TMP_DIR.mkdir(exist_ok=True)


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


def ask(prompt: str, default: str = "", required: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            val = input(prompt + suffix + ": ").strip()
        except (EOFError, KeyboardInterrupt):
            return default
        if not val:
            val = default
        if val or not required:
            return val
        print("  ! 这一项必填")


def setup_wizard(cfg: dict) -> dict:
    print("\n===== 配置 =====")
    cfg["pikpak_token"] = ask("PikPak 长期访问令牌 (eyJ...)",
                              default=cfg.get("pikpak_token", ""), required=True)
    cfg["pan115_cookies"] = ask("115 cookies (UID=..;CID=..;SEID=..;KID=..)",
                                 default=cfg.get("pan115_cookies", ""), required=True)
    save_config(cfg)
    print(f"配置已保存到 {CONFIG_PATH}\n")
    return cfg


# --------------------------------------------------------------------------- #
# 后台任务 + 进度
# --------------------------------------------------------------------------- #

PROGRESS = {
    "running": False,
    "direction": "",      # "pikpak->115" / "115->pikpak"
    "source": "",
    "target": "",
    "started_at": 0,
    "current_file": "",
    "done_files": 0,
    "total_files": 0,
    "done_bytes": 0,
    "total_bytes": 0,
    "error": "",
}


def ask_target_mode(src_path: str, dst_path: str) -> str:
    """选完源和目标后，问是直接传还是新建同名子文件夹。返回最终目标路径，空串=取消。"""
    src_name = src_path.strip("/").split("/")[-1] or "root"
    new_dir = (dst_path.rstrip("/") + "/" + src_name) if dst_path else "/" + src_name
    print(f"""
  源目录名: {src_name}
  已选父目录: {dst_path or '/'}
  [1] 直接传到 {dst_path or '/'}（内容直接合并进去，同名按大小覆盖）
  [2] 在 {dst_path or '/'} 下新建「{src_name}」再传（{new_dir}）
  [0] 取消
""")
    c = input("  请选择 [0/1/2]: ").strip()
    if c == "1":
        return dst_path
    if c == "2":
        return new_dir
    return ""


def show_progress():
    print("\n----- 复制进度 -----")
    if not PROGRESS["running"] and not PROGRESS["error"]:
        print("  当前没有进行中的任务。")
        return
    if PROGRESS["error"]:
        print(f"  状态: 失败 — {PROGRESS['error']}")
    elif PROGRESS["running"]:
        print("  状态: 传输中")
    else:
        print("  状态: 已完成")
    print(f"  方向: {PROGRESS['direction']}")
    print(f"  源:   {PROGRESS['source']}")
    print(f"  目标: {PROGRESS['target']}")
    if PROGRESS["total_files"]:
        pct = PROGRESS["done_files"] / PROGRESS["total_files"] * 100
        print(f"  文件: {PROGRESS['done_files']}/{PROGRESS['total_files']} ({pct:.1f}%)")
    if PROGRESS["total_bytes"]:
        pct = PROGRESS["done_bytes"] / PROGRESS["total_bytes"] * 100
        print(f"  字节: {human_size(PROGRESS['done_bytes'])}/{human_size(PROGRESS['total_bytes'])} ({pct:.1f}%)")
    if PROGRESS["current_file"]:
        print(f"  当前: {PROGRESS['current_file']}")
    if PROGRESS["started_at"]:
        print(f"  已运行: {int(time.time() - PROGRESS['started_at'])} 秒")
    print("---------------------\n")


def run_task(direction: str, pk: PikPak, pan: Pan115,
             src_path: str, dst_path: str):
    """在后台线程跑同步任务。"""
    PROGRESS.update(running=True, error="", direction=direction,
                    source=src_path or "/", target=dst_path,
                    started_at=time.time(), current_file="",
                    done_files=0, total_files=0,
                    done_bytes=0, total_bytes=0)
    try:
        if direction == "pikpak->115":
            pk_root = pk.resolve_path(src_path)
            pan_root = pan.resolve_or_create(dst_path)
            # 先数一下总文件数（粗略：只数第一层）
            children = pk.list_children(pk_root)
            files = [c for c in children if c.get("kind") == "drive#file"
                     and c.get("phase") == "PHASE_TYPE_COMPLETE"]
            PROGRESS["total_files"] = len(files)
            for f in files:
                PROGRESS["current_file"] = f.get("name", "")
                try:
                    PROGRESS["total_bytes"] += int(f.get("size", 0))
                except Exception:
                    pass
            sync_folder(pk, pan, pk_root, pan_root,
                        src_path.strip("/"), dry_run=False, tmp_dir=TMP_DIR)
            PROGRESS["done_files"] = PROGRESS["total_files"]
        else:  # 115 -> pikpak
            pan_cid = pan.resolve_or_create(src_path)
            pk_root_id = pk.resolve_path(dst_path)
            items = list(pan.fs.iterdir(pan_cid))
            files = [x for x in items if not x.get("is_dir")]
            PROGRESS["total_files"] = len(files)
            for f in files:
                PROGRESS["current_file"] = f.get("name", "")
                try:
                    PROGRESS["total_bytes"] += int(f.get("size", 0))
                except Exception:
                    pass
            sync_folder_reverse(pk, pan, pan_cid, pk_root_id,
                                src_path.strip("/"), dry_run=False, tmp_dir=TMP_DIR)
            PROGRESS["done_files"] = PROGRESS["total_files"]
        PROGRESS["current_file"] = ""
    except Exception as e:  # noqa: BLE001
        PROGRESS["error"] = str(e)
    finally:
        PROGRESS["running"] = False


# --------------------------------------------------------------------------- #
# 目录浏览
# --------------------------------------------------------------------------- #

def browse_pikpak(pk: PikPak, start_path: str = "") -> str:
    """返回选中的 PikPak 路径，或空串表示返回主菜单。"""
    cid = pk.resolve_path(start_path) if start_path else ""
    cur = start_path.strip("/")
    while True:
        children = pk.list_children(cid)
        folders = [c for c in children if c.get("kind") == "drive#folder"]
        files = [c for c in children
                 if c.get("kind") == "drive#file"
                 and c.get("phase") == "PHASE_TYPE_COMPLETE"]
        print(f"\n--- PikPak: /{cur or ''}  ({len(folders)} 目录, {len(files)} 文件) ---")
        for i, f in enumerate(folders, 1):
            print(f"  [{i}] 📁 {f['name']}/")
        print(f"  [..] 返回上一级目录")
        print(f"  [.] 👉 选中当前目录作为源")
        print(f"  [0] 返回主菜单")
        choice = input("请选择: ").strip()
        if choice == "0":
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
    cid = 0
    cur = start_path.strip("/")
    if cur:
        for seg in cur.split("/"):
            cid = pan._ensure_child_dir(cid, seg)
    while True:
        items = list(pan.fs.iterdir(cid))
        dirs = [x for x in items if x.get("is_dir")]
        files = [x for x in items if not x.get("is_dir")]
        print(f"\n--- 115: /{cur or ''}  ({len(dirs)} 目录, {len(files)} 文件) ---")
        for i, d in enumerate(dirs, 1):
            print(f"  [{i}] 📁 {d['name']}/")
        print(f"  [..] 返回上一级目录")
        print(f"  [.] 👉 选中当前目录")
        print(f"  [0] 返回主菜单")
        choice = input("请选择: ").strip()
        if choice == "0":
            return ""
        if choice == "..":
            if cur:
                cur = "/".join(cur.split("/")[:-1])
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
# 主菜单
# --------------------------------------------------------------------------- #

MAIN_MENU = """
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
==========================="""


def test_pan115(pan: Pan115) -> bool:
    print("\n--- 测试 115 cookies ---")
    try:
        items = list(pan.fs.iterdir(0))
        dirs = [x for x in items if x.get("is_dir")]
        files = [x for x in items if not x.get("is_dir")]
        print(f"  ✅ 连接成功，根目录有 {len(dirs)} 个文件夹, {len(files)} 个文件")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ 连接失败: {e}")
        return False


def test_pikpak(pk: PikPak) -> bool:
    print("\n--- 测试 PikPak token ---")
    try:
        j = pk._request("GET", "https://api-drive.mypikpak.com/drive/v1/about")
        used = j.get("used", "?")
        total = j.get("total", "?")
        try:
            used_s = human_size(int(used))
            total_s = human_size(int(total))
        except Exception:
            used_s, total_s = str(used), str(total)
        print(f"  ✅ 连接成功，已用 {used_s} / 共 {total_s}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ 连接失败: {e}")
        return False


def test_both(pk: PikPak, pan: Pan115):
    r1 = test_pan115(pan)
    r2 = test_pikpak(pk)
    print()
    if r1 and r2:
        print("  ✅ 双侧连接稳定，可以开始同步。")
    else:
        print("  ⚠️ 有一侧连接失败，请先修复再同步。")
    input("\n按回车继续...")


def test_pan115(pan: Pan115) -> bool:
    print("\n--- 测试 115 cookies ---")
    try:
        # 列根目录一个文件就够
        items = list(pan.fs.iterdir(0))
        print(f"  ✅ 连接成功，根目录有 {len(items)} 个条目")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ 连接失败: {e}")
        return False


def test_pikpak(pk: PikPak) -> bool:
    print("\n--- 测试 PikPak token ---")
    try:
        items = pk.list_children("")
        print(f"  ✅ 连接成功，根目录有 {len(items)} 个条目")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ 连接失败: {e}")
        return False


def main():
    global pk, pan
    load_dotenv(HERE / ".env")
    cfg = load_config()

    # 环境变量覆盖
    import os
    if os.environ.get("PIKPAK_LONG_TERM_TOKEN"):
        cfg["pikpak_token"] = os.environ["PIKPAK_LONG_TERM_TOKEN"]
    if os.environ.get("PAN115_COOKIES"):
        cfg["pan115_cookies"] = os.environ["PAN115_COOKIES"]

    if not cfg.get("pikpak_token") or not cfg.get("pan115_cookies"):
        cfg = setup_wizard(cfg)

    print("\n连接 PikPak 和 115 ...")
    pk = PikPak(access_token=cfg["pikpak_token"],
                token_store=HERE / ".pikpak_token.json")
    pan = Pan115(cfg["pan115_cookies"])
    print("连接成功。\n")

    while True:
        print(MAIN_MENU)
        try:
            choice = input("请选择 [1-10]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        if choice == "1":
            # 列出 115 目录（浏览后自动返回主菜单）
            browse_pan115(pan, cfg.get("last_115", "/"))
        elif choice == "2":
            browse_pikpak(pk, cfg.get("last_pk", ""))
        elif choice == "3":
            if PROGRESS["running"]:
                print("  ! 已有任务在跑，先看进度或等它结束。")
                continue
            print("\n--- 选择源：115 目录 ---")
            src = browse_pan115(pan, cfg.get("last_115", "/"))
            if not src:
                continue
            print("\n--- 选择目标：PikPak 目录 ---")
            dst = browse_pikpak(pk, cfg.get("last_pk", ""))
            if not dst:
                continue
            final_dst = ask_target_mode(src, dst)
            if not final_dst:
                print("  已取消。")
                continue
            print(f"\n  源:   115:{src}")
            print(f"  目标: PikPak:{final_dst or '(根目录)'}")
            ok = input("  开始复制? [Y/n]: ").strip().lower()
            if ok in ("n", "no"):
                continue
            cfg["last_115"], cfg["last_pk"] = src, final_dst
            save_config(cfg)
            t = threading.Thread(target=run_task,
                                 args=("115->pikpak", pk, pan, src, final_dst),
                                 daemon=True)
            t.start()
            print("  已在后台开始。回主菜单选 5 看进度。")
        elif choice == "4":
            if PROGRESS["running"]:
                print("  ! 已有任务在跑，先看进度或等它结束。")
                continue
            print("\n--- 选择源：PikPak 目录 ---")
            src = browse_pikpak(pk, cfg.get("last_pk", ""))
            if not src:
                continue
            print("\n--- 选择目标：115 目录 ---")
            dst = browse_pan115(pan, cfg.get("last_115", "/"))
            if not dst:
                continue
            final_dst = ask_target_mode(src, dst)
            if not final_dst:
                print("  已取消。")
                continue
            print(f"\n  源:   PikPak:{src}")
            print(f"  目标: 115:{final_dst}")
            ok = input("  开始复制? [Y/n]: ").strip().lower()
            if ok in ("n", "no"):
                continue
            cfg["last_pk"], cfg["last_115"] = src, final_dst
            save_config(cfg)
            t = threading.Thread(target=run_task,
                                 args=("pikpak->115", pk, pan, src, final_dst),
                                 daemon=True)
            t.start()
            print("  已在后台开始。回主菜单选 5 看进度。")
        elif choice == "5":
            show_progress()
        elif choice == "6":
            cfg = setup_wizard(cfg)
            # 重连
            pk = PikPak(access_token=cfg["pikpak_token"],
                        token_store=HERE / ".pikpak_token.json")
            pan = Pan115(cfg["pan115_cookies"])
            print("已用新配置重连。")
        elif choice == "7":
            test_pan115(pan)
            input("\n按回车继续...")
        elif choice == "8":
            test_pikpak(pk)
            input("\n按回车继续...")
        elif choice == "9":
            test_both(pk, pan)
        elif choice == "10":
            print("bye")
            break
        else:
            print("  ? 请输入 1-10")


if __name__ == "__main__":
    main()

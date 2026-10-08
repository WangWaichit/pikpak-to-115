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
PROGRESS_FILE = HERE / "progress.json"
TMP_DIR = HERE / ".tmp_sync"
TMP_DIR.mkdir(exist_ok=True)


def flush_progress():
    """把 PROGRESS 写到磁盘，供 ./run.sh status 读取。"""
    try:
        PROGRESS["updated_at"] = time.time()
        PROGRESS_FILE.write_text(json.dumps(PROGRESS, ensure_ascii=False, indent=2))
    except Exception:
        pass


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
    import sys
    # 始终从 /dev/tty 读，避免 wget|bash 管道 stdin 是管道
    try:
        tty = open("/dev/tty", "r")
    except Exception:
        tty = sys.stdin
    while True:
        try:
            sys.stdout.write(prompt + suffix + ": ")
            sys.stdout.flush()
            val = tty.readline().rstrip("\n").strip()
        except (EOFError, KeyboardInterrupt):
            return default
        if not val:
            val = default
        if val or not required:
            return val
        print("  ! 这一项必填")


def config_115(cfg: dict) -> dict:
    """单独配置 115 凭证。"""
    print("\n--- 115 网盘凭证 ---")
    print("  1. Cookies (UID=..;CID=..;SEID=..;KID=..)")
    print("  2. Refresh Token (OAuth 回调: https://api.oplist.org.cn/115cloud/callback)")
    v = ask("选择 [1/2]  [q 取消]", default=cfg.get("pan115_mode", "1")).strip().lower()
    if v in ("q", "quit"):
        print("  已取消。")
        return cfg
    if v not in ("1", "2"):
        print("  ? 请输入 1 或 2")
        return cfg
    cfg["pan115_mode"] = v
    if v == "1":
        c = ask("115 cookies (UID=..;CID=..;SEID=..;KID=..)  [b 返回]",
                default=cfg.get("pan115_cookies", ""), required=True)
        if c.strip().lower() in ("b", "back"):
            return cfg
        cfg["pan115_cookies"] = c
        cfg["pan115_refresh"] = ""
    else:
        c = ask("115 refresh_token  [b 返回]",
                default=cfg.get("pan115_refresh", ""), required=True)
        if c.strip().lower() in ("b", "back"):
            return cfg
        cfg["pan115_refresh"] = c
        cfg["pan115_cookies"] = ""
        app_id = ask("115 开放平台 app_id (OpenList 默认 0 即可)",
                     default=str(cfg.get("pan115_app_id", 0) or "0"))
        cfg["pan115_app_id"] = int(app_id or 0)
    save_config(cfg)
    print(f"  ✅ 115 配置已保存到 {CONFIG_PATH}\n")
    return cfg


def config_pikpak(cfg: dict) -> dict:
    """单独配置 PikPak 凭证。"""
    print("\n--- PikPak 凭证 ---")
    print("  1. 长期 Long-term Access Token (eyJ...，推荐)")
    print("  2. OAuth refresh_token")
    v = ask("选择 [1/2]  [q 取消]",
            default=cfg.get("pikpak_mode", "1")).strip().lower()
    if v in ("q", "quit"):
        print("  已取消。")
        return cfg
    if v not in ("1", "2"):
        print("  ? 请输入 1 或 2")
        return cfg
    cfg["pikpak_mode"] = v
    if v == "1":
        c = ask("PikPak 长期 Access Token (eyJ...)  [b 返回]",
                default=cfg.get("pikpak_token", ""), required=True)
        if c.strip().lower() in ("b", "back"):
            return cfg
        cfg["pikpak_token"] = c
        cfg["pikpak_refresh"] = ""
    else:
        c = ask("PikPak refresh_token  [b 返回]",
                default=cfg.get("pikpak_refresh", ""), required=True)
        if c.strip().lower() in ("b", "back"):
            return cfg
        cfg["pikpak_refresh"] = c
        cfg["pikpak_token"] = ""
    save_config(cfg)
    print(f"  ✅ PikPak 配置已保存到 {CONFIG_PATH}\n")
    return cfg


def setup_wizard(cfg: dict) -> dict:
    """首次启动时一次性配置两边。"""
    print("\n===== 首次配置 =====")
    cfg = config_115(cfg)
    cfg = config_pikpak(cfg)
    return cfg


def menu_reconfig(cfg: dict) -> dict:
    """菜单 7：二级选择，单独改 115 或 PikPak。"""
    while True:
        print("\n===== 重新配置 =====")
        print("  1. 仅配置 115 网盘凭证")
        print("  2. 仅配置 PikPak 凭证")
        print("  b. 返回主菜单")
        v = ask("请选择 [1/2/b]").strip().lower()
        if v in ("b", "back", ""):
            return cfg
        if v == "1":
            cfg = config_115(cfg)
        elif v == "2":
            cfg = config_pikpak(cfg)
        else:
            print("  ? 请输入 1 / 2 / b")


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


def ask_target_mode(src_path: str, dst_parent: str) -> str:
    """选完源和目标父目录后，问新建文件夹的名字。返回最终目标路径，空串=取消。"""
    src_name = src_path.strip("/").split("/")[-1] or "root"
    print(f"""
  源目录: {src_path or '/'}
  源目录名: 「{src_name}」
  目标父目录: {dst_parent or '/'}
  [1] 直接复制过去：在 {dst_parent or '/'} 下建「{src_name}」（保持原名）
  [2] 新建自定义文件夹：你输入一个新名字，把文件传进去
  [0] 取消
""")
    c = input("  请选择 [0/1/2]: ").strip()
    if c == "0":
        return ""
    if c == "1":
        new_name = src_name
    elif c == "2":
        new_name = input("  请输入新文件夹名: ").strip()
        if not new_name:
            print("  ? 名字不能为空")
            return ""
    else:
        print("  ? 无效输入")
        return ""
    return (dst_parent.rstrip("/") + "/" + new_name) if dst_parent else "/" + new_name


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
    flush_progress()
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
            pk_root_id = pk.resolve_or_create(dst_path)
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
        flush_progress()


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
            found = pan._find_child_dir(cid, seg)
            if found < 0:
                cid = 0
                cur = ""
                break
            cid = found
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
                        found = pan._find_child_dir(cid, seg)
                        if found < 0:
                            cid = 0
                            cur = ""
                            break
                        cid = found
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
  1. 安装/更新程序
  2. 列出 115 目录
  3. 列出 PikPak 目录
  4. 拷贝 115 目录文件到 PikPak 目录
  5. 拷贝 PikPak 目录文件到 115 目录
  6. 查看复制进度
  7. 重新配置文件
  8. 测试 115 cookies 连通性
  9. 测试 PikPak token 连通性
  10. 测试网盘是否连接（双侧）
  11. 卸载程序
  12. 退出
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

    # 判断是否已配置：只要 PikPak 或 115 任意一个凭证字段非空，就跳过向导
    def _has_pikpak():
        return bool(cfg.get("pikpak_token") or cfg.get("pikpak_refresh"))
    def _has_p115():
        return bool(cfg.get("pan115_cookies") or cfg.get("pan115_refresh"))
    if not (_has_pikpak() and _has_p115()):
        cfg = setup_wizard(cfg)

    # 凭证无效也能进菜单，只是连通/传输会失败
    pk = None
    pan = None
    try:
        print("\n初始化 PikPak 客户端 ...")
        if cfg.get("pikpak_mode") == "2":
            pk = PikPak(refresh_token=cfg.get("pikpak_refresh", ""),
                        token_store=HERE / ".pikpak_token.json")
        else:
            pk = PikPak(access_token=cfg.get("pikpak_token", ""),
                        token_store=HERE / ".pikpak_token.json")
        print("  PikPak OK")
    except Exception as e:  # noqa: BLE001
        print(f"  PikPak 初始化失败: {e}")
        print("  菜单仍可用，但涉及 PikPak 的操作会报错。")
    try:
        print("初始化 115 客户端 ...")
        if cfg.get("pan115_mode") == "2":
            pan = Pan115(refresh_token=cfg.get("pan115_refresh", ""),
                         app_id=int(cfg.get("pan115_app_id", 0) or 0))
        else:
            pan = Pan115(cfg.get("pan115_cookies", ""))
        print("  115 OK")
    except Exception as e:  # noqa: BLE001
        print(f"  115 初始化失败: {e}")
        print("  菜单仍可用，但涉及 115 的操作会报错。")
    print()

    while True:
        pk_icon = "✅" if pk is not None else "❌"
        p115_icon = "✅" if pan is not None else "❌"
        print(f"[状态] PikPak:{pk_icon} | 115:{p115_icon}")
        print(MAIN_MENU)
        try:
            choice = input("请选择 [1-12]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        if choice == "1":
            # 安装/更新程序
            import subprocess
            print("\n--- 拉取最新代码并重装依赖 ---")
            try:
                subprocess.run(["git", "pull", "--ff-only"], cwd=HERE, check=False)
                subprocess.run([
                    "python3", "-m", "pip", "install",
                    "--break-system-packages", "-q", "requests", "p115client"
                ], check=False)
                print("  ✅ 已是最新。建议退出重进 ./run.sh 加载新代码。")
            except Exception as e:  # noqa: BLE001
                print(f"  ! 更新失败: {e}")
            input("\n按回车继续...")
        elif choice == "2":
            if pan is None:
                print("  ! 115 未连接，请先选菜单 7 重新配置。")
                continue
            browse_pan115(pan, cfg.get("last_115", "/"))
        elif choice == "3":
            if pk is None:
                print("  ! PikPak 未连接，请先选菜单 7 重新配置。")
                continue
            browse_pikpak(pk, cfg.get("last_pk", ""))
        elif choice == "4":
            if pan is None or pk is None:
                print("  ! 115/PikPak 未连接，请先选菜单 7 重新配置。")
                continue
            if PROGRESS["running"]:
                print("  ! 已有任务在跑，先看进度或等它结束。")
                continue
            print("\n--- 选择源：115 目录 ---")
            src = browse_pan115(pan, cfg.get("last_115", "/"))
            if not src:
                continue
            print("\n--- 选择目标父目录（PikPak）---")
            dst = browse_pikpak(pk, cfg.get("last_pk", ""))
            if not dst:
                continue
            final_dst = ask_target_mode(src, dst)
            if not final_dst:
                print("  已取消。")
                continue
            print(f"\n  源:   115:{src}")
            print(f"  目标: PikPak:{final_dst}")
            ok = input("  开始复制? [Y/n]: ").strip().lower()
            if ok in ("n", "no"):
                continue
            cfg["last_115"], cfg["last_pk"] = src, final_dst
            save_config(cfg)
            t = threading.Thread(target=run_task,
                                 args=("115->pikpak", pk, pan, src, final_dst),
                                 daemon=True)
            t.start()
            print("  已在后台开始。回主菜单选 6 看进度。")
        elif choice == "5":
            if pan is None or pk is None:
                print("  ! 115/PikPak 未连接，请先选菜单 7 重新配置。")
                continue
            if PROGRESS["running"]:
                print("  ! 已有任务在跑，先看进度或等它结束。")
                continue
            print("\n--- 选择源：PikPak 目录 ---")
            src = browse_pikpak(pk, cfg.get("last_pk", ""))
            if not src:
                continue
            print("\n--- 选择目标父目录（115）---")
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
            print("  已在后台开始。回主菜单选 6 看进度。")
        elif choice == "6":
            show_progress()
        elif choice == "7":
            cfg = menu_reconfig(cfg)
            try:
                if cfg.get("pikpak_mode") == "2":
                    pk = PikPak(refresh_token=cfg.get("pikpak_refresh", ""),
                                token_store=HERE / ".pikpak_token.json")
                else:
                    pk = PikPak(access_token=cfg.get("pikpak_token", ""),
                                token_store=HERE / ".pikpak_token.json")
                print("  PikPak 重连 OK")
            except Exception as e:  # noqa: BLE001
                pk = None
                print(f"  PikPak 重连失败: {e}")
            try:
                if cfg.get("pan115_mode") == "2":
                    pan = Pan115(refresh_token=cfg.get("pan115_refresh", ""),
                                 app_id=int(cfg.get("pan115_app_id", 0) or 0))
                else:
                    pan = Pan115(cfg.get("pan115_cookies", ""))
                print("  115 重连 OK")
            except Exception as e:  # noqa: BLE001
                pan = None
                print(f"  115 重连失败: {e}")
        elif choice == "8":
            if pan is None:
                print("  ! 115 未连接。")
            else:
                test_pan115(pan)
            input("\n按回车继续...")
        elif choice == "9":
            if pk is None:
                print("  ! PikPak 未连接。")
            else:
                test_pikpak(pk)
            input("\n按回车继续...")
        elif choice == "10":
            if pan is None or pk is None:
                print("  ! 至少有一侧未连接，先选菜单 7 重新配置。")
            else:
                test_both(pk, pan)
        elif choice == "11":
            # 卸载：删除 VPS 上所有相关文件和目录
            print("\n--- 卸载（彻底删除）---")
            print("将执行：")
            print("  1. 停止并禁用 systemd 服务")
            print("  2. 删除 /etc/systemd/system/pikpak-to-115.service")
            print("  3. 删除 /usr/local/bin/pikpak 软链")
            print("  4. 从 /root/.bashrc 删除 alias p")
            print(f"  5. 删除项目目录 {HERE}（含凭证、配置、日志）")
            print("  6. systemctl daemon-reload")
            ok = input("  ⚠️  确认卸载? 输入 YES 继续: ").strip()
            if ok == "YES":
                import shutil
                subprocess.run(["systemctl", "stop", "pikpak-to-115"], check=False)
                subprocess.run(["systemctl", "disable", "pikpak-to-115"], check=False)
                for f in ["/etc/systemd/system/pikpak-to-115.service",
                          "/usr/local/bin/pikpak"]:
                    try:
                        Path(f).unlink()
                    except Exception:
                        pass
                # 清 .bashrc 里的 alias p
                bashrc = Path("/root/.bashrc")
                if bashrc.exists():
                    lines = [l for l in bashrc.read_text().splitlines()
                             if "alias p=" not in l or "pikpak-to-115" not in l]
                    bashrc.write_text("\n".join(lines) + "\n")
                subprocess.run(["systemctl", "daemon-reload"], check=False)
                # 删项目目录
                try:
                    shutil.rmtree(HERE)
                except Exception as e:
                    print(f"  ! 删项目目录失败: {e}")
                print("\n  ✅ 卸载完成。所有相关文件已删除。")
                print("  你可以退出 SSH 重连，p 命令不再可用。")
                # 直接退出，因为当前目录已删
                import os
                os._exit(0)
            else:
                print("  已取消。")
            input("\n按回车继续...")
        elif choice == "12":
            print("bye")
            break
        else:
            print("  ? 请输入 1-12")


if __name__ == "__main__":
    main()

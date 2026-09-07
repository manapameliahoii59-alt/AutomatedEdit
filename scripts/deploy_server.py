#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AutomatedEdit 服务端一键自动部署脚本
功能：自动打包本地 server/app 增量代码，通过 SSH/SFTP 上传至腾讯云宝塔服务器并重启 Python 项目。
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import tarfile
import time
from pathlib import Path
from typing import Dict, List, Tuple
import urllib.request
import urllib.error

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import paramiko
except ImportError:
    print("[提示] 正在安装远程连接依赖库 paramiko...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
    import paramiko


REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_APP_DIR = REPO_ROOT / "server" / "app"
DEPLOY_ENV_FILE = REPO_ROOT / ".deploy.env"
DEPLOY_ENV_EXAMPLE = REPO_ROOT / ".deploy.env.example"

DEFAULT_CONFIG = {
    "DEPLOY_HOST": "129.204.86.63",
    "DEPLOY_PORT": "22",
    "DEPLOY_USER": "root",
    "DEPLOY_PASSWORD": "",
    "DEPLOY_REMOTE_DIR": "/www/wwwroot/automated-edit-api",
    "DEPLOY_RESTART_CMD": "",
    "DEPLOY_HEALTH_URL": "http://129.204.86.63:7172/admin",
}

EXCLUDE_PATTERNS = {
    "__pycache__",
    ".pytest_cache",
    ".DS_Store",
    ".git",
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
}


def print_step(step: str, title: str):
    print(f"\n[{step}] {title}")


def print_ok(msg: str):
    print(f"  [OK] {msg}")


def print_warn(msg: str):
    print(f"  [!]  {msg}")


def print_err(msg: str):
    print(f"  [ERR] {msg}")


def load_config() -> Dict[str, str]:
    config = dict(DEFAULT_CONFIG)
    if not DEPLOY_ENV_FILE.exists():
        if DEPLOY_ENV_EXAMPLE.exists():
            import shutil
            shutil.copy(DEPLOY_ENV_EXAMPLE, DEPLOY_ENV_FILE)
            print_warn(f"未检测到 .deploy.env，已自动从模版创建：{DEPLOY_ENV_FILE}")
            print_warn("请在 .deploy.env 中配置您的服务器 DEPLOY_PASSWORD 后重新运行。")

    if DEPLOY_ENV_FILE.exists():
        with open(DEPLOY_ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip().strip('"').strip("'")

    return config


def collect_app_files() -> List[Tuple[Path, str]]:
    """递归收集 server/app 目录下所有有效文件（排除缓存文件）。"""
    files: List[Tuple[Path, str]] = []
    if not LOCAL_APP_DIR.exists():
        raise FileNotFoundError(f"本地代码目录不存在：{LOCAL_APP_DIR}")

    for root, dirs, filenames in os.walk(LOCAL_APP_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_PATTERNS]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in EXCLUDE_EXTENSIONS or fname in EXCLUDE_PATTERNS:
                continue
            full_path = Path(root) / fname
            rel_path = full_path.relative_to(LOCAL_APP_DIR)
            arc_name = f"app/{rel_path.as_posix()}"
            files.append((full_path, arc_name))

    return sorted(files, key=lambda x: x[1])


def create_tar_archive(files: List[Tuple[Path, str]]) -> io.BytesIO:
    """在内存中打包 tar.gz。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for full_path, arc_name in files:
            tar.add(str(full_path), arcname=arc_name)
    buf.seek(0)
    return buf


def smart_restart_script(project_dir: str) -> str:
    """生成宝塔环境智能重启命令。"""
    return f"""
# 1. 优先使用宝塔 Python 项目管理器专属控制机制
if [ -f "/www/server/python_project/vhost/scripts/automated-edit-api_cmd.sh" ]; then
    echo "[baota] 检测到宝塔 Python 项目脚本，正在平滑重启..."
    PID_FILE="/www/server/python_project/vhost/pids/automated-edit-api.pid"
    if [ -f "$PID_FILE" ]; then
        OLD_PID=$(cat "$PID_FILE")
        if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
            kill -9 "$OLD_PID" 2>/dev/null || true
        fi
    fi
    fuser -k 7172/tcp 2>/dev/null || true
    sleep 1
    /bin/bash /www/server/python_project/vhost/scripts/automated-edit-api_cmd.sh
    sleep 2
    echo "[baota] 宝塔启动指令已下发！"
    exit 0
fi

# 2. 尝试查找 systemctl 中对应的 Python 项目服务
SRV=$(systemctl list-unit-files --type=service 2>/dev/null | grep -E 'automated.*api|automated_edit' | awk '{{print $1}}' | head -n 1)
if [ -n "$SRV" ]; then
    echo "[systemctl] 发现服务 $SRV，正在执行重启..."
    systemctl restart "$SRV"
    exit 0
fi

# 3. 尝试 supervisorctl 重启
if command -v supervisorctl >/dev/null 2>&1; then
    SUP=$(supervisorctl status 2>/dev/null | grep -E 'automated.*api|automated_edit' | awk '{{print $1}}' | head -n 1)
    if [ -n "$SUP" ]; then
        echo "[supervisor] 发现进程 $SUP，正在执行重启..."
        supervisorctl restart "$SUP"
        exit 0
    fi
fi

# 4. 兜底重启
fuser -k 7172/tcp 2>/dev/null || true
sleep 1
cd {project_dir} && nohup ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 7172 &>> /www/wwwlogs/python/automated-edit-api/error.log &
"""


def health_check(url: str, retries: int = 5, delay: float = 2.0) -> bool:
    """轮询健康检查端点。"""
    print(f"  正在请求接口探活：{url} (最多重试 {retries} 次)...")
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if 200 <= resp.status < 400:
                    print_ok(f"探活成功！HTTP 状态码: {resp.status} (第 {attempt} 次检测)")
                    return True
        except urllib.error.HTTPError as e:
            if e.code in (200, 301, 302, 401, 403):
                # 302 重定向到登录页或 401/403 均说明服务已正常响应
                print_ok(f"探活成功！HTTP 状态码: {e.code} (服务已恢复响应)")
                return True
            print_warn(f"第 {attempt} 次检测：HTTP {e.code}")
        except Exception as e:
            print_warn(f"第 {attempt} 次检测中：{e}")
        time.sleep(delay)
    return False


def run_probe(cfg: Dict[str, str], password: str):
    """服务器诊断探查模式。"""
    print_step("PROBE", f"正在连接服务器 {cfg['DEPLOY_HOST']} 进行环境诊断...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=cfg["DEPLOY_HOST"],
        port=int(cfg["DEPLOY_PORT"]),
        username=cfg["DEPLOY_USER"],
        password=password,
        timeout=15,
    )
    print_ok("SSH 登录成功！\n")

    cmds = [
        ("操作系统信息", "uname -a && cat /etc/os-release | grep PRETTY_NAME"),
        ("项目目录检查", f"ls -ld {cfg['DEPLOY_REMOTE_DIR']} && ls -la {cfg['DEPLOY_REMOTE_DIR']}"),
        ("Python/Uvicorn 进程状态", "ps aux | grep -E 'python|uvicorn' | grep -v grep | head -n 10"),
        ("Systemd 托管项目", "systemctl list-units --type=service 2>/dev/null | grep -E 'automated|python' || true"),
        ("Supervisor 托管状态", "command -v supervisorctl >/dev/null && supervisorctl status || echo '未安装 supervisor'"),
    ]

    for title, cmd in cmds:
        print(f"\033[1;33m--- {title} ---\033[0m")
        _stdin, stdout, stderr = client.exec_command(cmd)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        if out:
            print(out)
        if err:
            print(f"[stderr] {err}")
        print()

    client.close()


def main():
    parser = argparse.ArgumentParser(description="AutomatedEdit 服务端一键自动部署工具")
    parser.add_argument("--dry-run", action="store_true", help="仅列出将要打包上传的文件清单，不实际连接与传输")
    parser.add_argument("--probe", action="store_true", help="诊断测试：连接服务器探查项目进程与服务名")
    args = parser.parse_args()

    cfg = load_config()

    # 1. 扫描文件
    print_step("1/4", f"正在扫描本地代码目录：{LOCAL_APP_DIR}")
    files = collect_app_files()
    total_size = sum(f[0].stat().st_size for f in files)
    print_ok(f"共扫描到 {len(files)} 个待部署文件，总原始大小: {total_size / 1024:.1f} KB")

    if args.dry_run:
        print("\n待同步文件清单预览：")
        for _f, arc in files:
            print(f"  -> {arc}")
        print("\n[Dry-run] 演练完成，未做实际改动。")
        return

    # 获取密码
    password = cfg.get("DEPLOY_PASSWORD", "").strip()
    if not password:
        password = input(f"请输入服务器 {cfg['DEPLOY_USER']}@{cfg['DEPLOY_HOST']} 的 SSH 密码: ").strip()
        if not password:
            print_err("未输入密码，部署已终止。")
            sys.exit(1)

    if args.probe:
        run_probe(cfg, password)
        return

    # 2. 打包
    print_step("2/4", "正在打包代码为内存压缩流 (tar.gz)...")
    tar_buf = create_tar_archive(files)
    pkg_size = tar_buf.getbuffer().nbytes
    print_ok(f"压缩打包完成，传输包体积仅为: {pkg_size / 1024:.1f} KB")

    # 3. 连接与传输
    print_step("3/4", f"正在通过 SSH 连接腾讯云服务器 {cfg['DEPLOY_HOST']}:{cfg['DEPLOY_PORT']}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    t_start = time.perf_counter()
    try:
        client.connect(
            hostname=cfg["DEPLOY_HOST"],
            port=int(cfg["DEPLOY_PORT"]),
            username=cfg["DEPLOY_USER"],
            password=password,
            timeout=15,
        )
        print_ok(f"成功登录服务器（用户: {cfg['DEPLOY_USER']}）！")
    except Exception as e:
        print_err(f"连接服务器失败：{e}")
        print_warn("请检查：1. 腾讯云安全组是否放行 22 端口；2. 密码是否正确。")
        sys.exit(1)

    remote_tmp_tar = "/tmp/ae_app_update.tar.gz"
    remote_dir = cfg["DEPLOY_REMOTE_DIR"].rstrip("/")

    print("  正在通过 SFTP 上传压缩包...")
    sftp = client.open_sftp()
    sftp.putfo(tar_buf, remote_tmp_tar)
    sftp.close()
    print_ok(f"文件已上传至远端临时文件：{remote_tmp_tar}")

    print(f"  正在解压并覆盖至：{remote_dir}/app/...")
    unpack_cmd = f"mkdir -p {remote_dir} && tar -xzf {remote_tmp_tar} -C {remote_dir}/ && rm -f {remote_tmp_tar}"
    _in, out, err = client.exec_command(unpack_cmd)
    if out.channel.recv_exit_status() != 0:
        print_err(f"解压失败：{err.read().decode()}")
        client.close()
        sys.exit(1)
    print_ok("代码覆盖完成！")

    # 4. 重启服务
    print_step("4/4", "正在触发宝塔 Python 项目重启...")
    custom_cmd = cfg.get("DEPLOY_RESTART_CMD", "").strip()
    if custom_cmd:
        restart_cmd = custom_cmd
        print(f"  执行自定义重启命令：{restart_cmd}")
    else:
        restart_cmd = smart_restart_script(remote_dir)
        print("  执行智能检测重启...")

    _in, out, err = client.exec_command(restart_cmd)
    ret_code = out.channel.recv_exit_status()
    output_msg = out.read().decode("utf-8", errors="replace").strip()
    if output_msg:
        for line in output_msg.splitlines():
            print(f"  \033[90m> {line}\033[0m")
    if ret_code == 0:
        print_ok("重启指令下发成功！")
    else:
        print_warn(f"重启返回码: {ret_code}，详情: {err.read().decode()}")

    client.close()

    # 5. 探活检测
    health_url = cfg.get("DEPLOY_HEALTH_URL", "").strip()
    if health_url:
        print("\n正在验证服务恢复状态...")
        ok = health_check(health_url)
        if not ok:
            print_warn("探活未能在预定时间内收到成功响应，请检查宝塔后台项目运行状态。")

    t_cost = time.perf_counter() - t_start
    print(f"\n========================================")
    print(f"[SUCCESS] 部署流程全部完成！总耗时: {t_cost:.2f} 秒")
    print(f"========================================\n")


if __name__ == "__main__":
    main()

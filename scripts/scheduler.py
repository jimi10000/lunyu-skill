#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scheduler.py — 注册「每天自动生成日报」定时任务

为 report.py 提供跨平台定时调度：
- Windows: 用 schtasks 创建计划任务，每天指定时间运行 daily_report.sh
- Linux/macOS: 用 cron 添加 crontab 条目

用法:
    # 注册每天 18:00 自动生成日报
    python scheduler.py install --time 18:00 --project C:/path/to/project --author "你"

    # 查看已注册的任务
    python scheduler.py status

    # 卸载定时任务
    python scheduler.py uninstall

    # 立即试跑一次（不注册）
    python scheduler.py run-once --project C:/path/to/project --author "你"

环境变量:
    无（脚本零凭据）

退出码: 0=成功 / 1=失败
"""
import argparse
import os
import platform
import subprocess
import sys

TASK_NAME = "lunyu_daily_report"


def find_skill_dir():
    """定位 lunyu 技能根目录（本脚本的上一级）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_windows():
    return platform.system() == "Windows"


def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, errors="ignore")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def run_input(cmd, input_text):
    """带 stdin 的 run()。crontab 必须这样写: 经 shell 的 echo 不解释 \n,
    repr 出来的字面量会把整个 crontab 压成一行坏条目。"""
    try:
        r = subprocess.run(cmd, input=input_text, capture_output=True, text=True, timeout=15)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def get_report_py():
    return os.path.join(find_skill_dir(), "scripts", "report.py")


def get_daily_script():
    return os.path.join(find_skill_dir(), "scripts", "daily_report.sh")


def build_windows_cmd(project, author):
    """Windows 上直接调 python report.py daily，绕开 bash 解析问题。"""
    report_py = get_report_py()
    python_exe = sys.executable
    return (f'"{python_exe}" "{report_py}" daily '
            f'--project "{os.path.basename(project)}" --author "{author}" '
            f'--body "（自动生成日报，请补充今日完成事项）"')


def cmd_install(args):
    report_py = get_report_py()
    if not os.path.isfile(report_py):
        print(f"错误: 未找到 report.py: {report_py}")
        return 1
    hour, minute = args.time.split(":")
    project = os.path.abspath(args.project)

    if is_windows():
        # schtasks /create /tn 名称 /tr 命令 /sc daily /st HH:MM
        # 直接调 python report.py，不经过 bash（避免 WSL 解析问题）
        cmd = build_windows_cmd(project, args.author)
        # 计划任务默认工作目录是 System32, 而 report.py 按 CWD 相对路径读写 .lunyu/,
        # 不先 cd 过去日报会写错位置
        tr_value = f'cmd /c cd /d "{project}" && {cmd}'
        # schtasks 的 /tr 参数里的引号需要转义
        schtasks_cmd = tr_value.replace('"', '\\"')
        rc, out = run(["schtasks", "/create", "/tn", TASK_NAME, "/tr", schtasks_cmd,
                       "/sc", "daily", "/st", f"{hour}:{minute}", "/f"])
        if rc != 0:
            print(f"注册失败: {out}")
            return 1
        print(f"已注册 Windows 计划任务 [{TASK_NAME}] 每天 {args.time} 运行")
        print(f"  项目: {project}")
        print(f"  命令: {tr_value}")
    else:
        # Linux/macOS: crontab (路径含空格也要能跑, 全部加引号)
        script = get_daily_script()
        cron_line = f'{minute} {hour} * * * cd "{project}" && bash "{script}" "{project}" "{args.author}" >/dev/null 2>&1'
        rc, out = run(["crontab", "-l"])
        existing = out if rc == 0 else ""
        if TASK_NAME in existing:
            print("已存在同名 cron 任务，先卸载再装")
            cmd_uninstall(None)
            rc, out = run(["crontab", "-l"])
            existing = out if rc == 0 else ""
        new_cron = (existing.rstrip() + "\n" if existing else "") + cron_line + "\n"
        rc2, out2 = run_input(["crontab", "-"], new_cron)
        if rc2 != 0:
            print(f"写入 crontab 失败: {out2}")
            return 1
        print(f"已注册 cron 任务 [{TASK_NAME}] 每天 {args.time} 运行")
        print(f"  项目: {project}")

    return 0


def cmd_uninstall(args):
    if is_windows():
        rc, out = run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"])
        if rc != 0 and "does not exist" not in out and "找不到" not in out:
            print(f"卸载失败: {out}")
            return 1
        print(f"已卸载 Windows 计划任务 [{TASK_NAME}]")
    else:
        rc, out = run(["crontab", "-l"])
        if rc != 0:
            print("无 crontab 或读取失败，无需卸载")
            return 0
        lines = [l for l in out.splitlines() if TASK_NAME not in l]
        new_cron = "\n".join(lines) + ("\n" if lines else "")
        rc2, out2 = run_input(["crontab", "-"], new_cron)
        if rc2 != 0:
            print(f"卸载失败: {out2}")
            return 1
        print(f"已卸载 cron 任务 [{TASK_NAME}]")
    return 0


def cmd_status(args):
    if is_windows():
        rc, out = run(["schtasks", "/query", "/tn", TASK_NAME])
        if rc == 0:
            print(f"计划任务 [{TASK_NAME}] 已注册")
            for line in out.splitlines():
                if "lunyu" in line.lower() or "daily" in line.lower():
                    print(" ", line.strip())
            return 0
        print("未注册")
        return 0
    else:
        rc, out = run(["crontab", "-l"])
        if rc == 0 and TASK_NAME in out:
            print(f"cron 任务 [{TASK_NAME}] 已注册")
            for line in out.splitlines():
                if TASK_NAME in line:
                    print(" ", line.strip())
            return 0
        print("未注册")
        return 0


def get_bash_path():
    """Windows 上返回 Git Bash 完整路径，macOS/Linux 返回 bash。"""
    if not is_windows():
        return "bash"
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Git\bin\bash.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    # 兜底：试试 PATH 里的 bash（可能是 WSL，不理想但能跑）
    return "bash"


def cmd_run_once(args):
    project = os.path.abspath(args.project)
    if is_windows():
        # Windows 直接调 python report.py（shell=True 避免引号解析问题）；
        # cwd 与计划任务对齐, 都在项目目录里跑, 否则 .lunyu/ 读写位置不一致
        import subprocess as sp
        r = sp.run(build_windows_cmd(project, args.author), shell=True, cwd=project,
                   capture_output=True, text=True, timeout=120, errors="ignore")
        print(r.stdout + r.stderr)
        return r.returncode
    else:
        script = get_daily_script()
        rc, out = run(["bash", script, project, args.author])
        print(out)
        return rc


def main():
    ap = argparse.ArgumentParser(description="注册/卸载/查看 每日自动日报定时任务")
    sub = ap.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("install", help="注册定时任务")
    i.add_argument("--time", default="18:00", help="每天运行时间 HH:MM")
    i.add_argument("--project", required=True, help="项目根目录")
    i.add_argument("--author", default="", help="作者")
    i.set_defaults(func=cmd_install)

    u = sub.add_parser("uninstall", help="卸载定时任务")
    u.set_defaults(func=cmd_uninstall)

    s = sub.add_parser("status", help="查看定时任务状态")
    s.set_defaults(func=cmd_status)

    r = sub.add_parser("run-once", help="立即试跑一次")
    r.add_argument("--project", required=True, help="项目根目录")
    r.add_argument("--author", default="", help="作者")
    r.set_defaults(func=cmd_run_once)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
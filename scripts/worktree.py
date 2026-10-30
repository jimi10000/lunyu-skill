#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作区隔离 - 君子不立于危墙之下

论语出处：《论语·季氏》「危而不持，颠而不扶」——
放到工程里：多个需求共用一份工作区，改到一半被另一个需求冲掉，
就是典型的「危墙」。Git worktree 让你在同一份 .git 上开多个独立目录，
各改各的，互不污染。

什么时候必须用:
- 两个需求同时推进（一个改到一半，另一个急活插进来）
- **多个 AI / 多个会话同时改同一个仓库**（互相覆盖的头号解药）
- 想在不碰当前工作区的前提下看看别的分支长什么样

命令:
    create <分支名> [--from <基准分支>] [--dir <路径>]   新建隔离工作区
    list                                              列出全部工作区
    path <分支名>                                      打印工作区路径（给脚本用）
    remove <分支名> [--force]                          移除工作区
    prune                                             清理已被手工删除的残留记录

退出码:
    0 = 成功
    1 = 失败（分支已存在 / 不是 git 仓库 / 工作区有未提交改动不让删）
    2 = 参数错误
"""
import argparse
import os
import subprocess
import sys

DEFAULT_BASE = "main"


def find_root(start=None):
    cur = os.path.abspath(start or os.getcwd())
    probe = cur
    while True:
        if os.path.isdir(os.path.join(probe, ".git")):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            return cur
        probe = parent


def git(root, args):
    """执行 git，返回 (returncode, stdout.strip(), stderr.strip())。"""
    try:
        proc = subprocess.run(["git"] + args, cwd=root, capture_output=True, text=True)
    except FileNotFoundError:
        return 127, "", "git 不在 PATH 里"
    except OSError as e:
        return 1, "", str(e)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def is_git_repo(root):
    rc, out, _ = git(root, ["rev-parse", "--is-inside-work-tree"])
    return rc == 0 and out == "true"


def worktrees(root):
    """解析 git worktree list --porcelain，返回 [(路径, 分支, 是否主工作区)]。"""
    rc, out, err = git(root, ["worktree", "list", "--porcelain"])
    if rc != 0:
        return []
    items = []
    path = None
    branch = None
    bare = False
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.startswith("branch "):
            branch = line[len("branch "):].strip()
            if branch.startswith("refs/heads/"):
                branch = branch[len("refs/heads/"):]
        elif line == "bare":
            bare = True
        elif line == "detached":
            branch = "(detached)"
        elif line == "" and path:
            items.append((path, branch or "", bare))
            path, branch, bare = None, None, False
    if path:
        items.append((path, branch or "", bare))
    return items


def default_dir(root, branch):
    """默认放在仓库同级目录，避免把 worktree 塞进工作区里（会被 git 看到）。"""
    parent = os.path.dirname(root)
    safe = branch.replace("/", "-").replace("\\", "-")
    return os.path.join(parent, "%s-%s" % (os.path.basename(root), safe))


def branch_exists(root, branch):
    rc, _, _ = git(root, ["rev-parse", "--verify", "refs/heads/%s" % branch])
    return rc == 0


def cmd_create(args):
    root = os.path.abspath(args.root or find_root())
    if not is_git_repo(root):
        print("错误: 不是 git 仓库: %s" % root, file=sys.stderr)
        return 1
    branch = args.branch
    if branch_exists(root, branch):
        print("错误: 分支已存在: %s（已存在就用它，别重复建）" % branch, file=sys.stderr)
        return 1

    base = args.base
    if base:
        rc, _, err = git(root, ["rev-parse", "--verify", "refs/heads/%s" % base])
        if rc != 0:
            print("错误: 基准分支不存在: %s" % base, file=sys.stderr)
            return 1
    else:
        # 没指定基准就用当前分支
        rc, cur, _ = git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
        base = cur if rc == 0 and cur else DEFAULT_BASE

    path = os.path.abspath(args.dir or default_dir(root, branch))
    if os.path.exists(path):
        print("错误: 目标目录已存在: %s（换个 --dir）" % path, file=sys.stderr)
        return 1

    rc, out, err = git(root, ["worktree", "add", "-b", branch, path, base])
    if rc != 0:
        print("错误: 创建失败: %s" % (err or out), file=sys.stderr)
        return 1

    print("=" * 60)
    print("隔离工作区已就绪")
    print("=" * 60)
    print("  分支: %s（基于 %s）" % (branch, base))
    print("  路径: %s" % path)
    print("")
    print("  进去干活: cd %s" % path)
    print("  干完移除: python scripts/worktree.py remove %s" % branch)
    print("")
    print("  提醒: 这个目录和主工作区共用同一份 .git，提交是互通的，")
    print("        但工作区文件完全独立——改它不会动到主工作区。")
    return 0


def cmd_list(args):
    root = os.path.abspath(args.root or find_root())
    if not is_git_repo(root):
        print("错误: 不是 git 仓库: %s" % root, file=sys.stderr)
        return 1
    items = worktrees(root)
    if not items:
        print("没有隔离工作区")
        return 0
    print("=" * 60)
    print("隔离工作区（共 %d 个）" % len(items))
    print("=" * 60)
    for path, branch, bare in items:
        tag = "主工作区" if bare is False and os.path.abspath(path) == root else "隔离"
        print("  [%s] %s" % (tag, path))
        print("        分支: %s" % (branch or "(无)"))
        if os.path.isdir(path):
            rc, dirty, _ = git(path, ["status", "--porcelain"])
            n = len([l for l in dirty.splitlines() if l.strip()]) if rc == 0 else -1
            if n > 0:
                print("        状态: 有 %d 处未提交改动" % n)
            elif n == 0:
                print("        状态: 干净")
        else:
            print("        状态: 目录不存在（跑 prune 清理）")
    return 0


def cmd_path(args):
    root = os.path.abspath(args.root or find_root())
    for path, branch, _ in worktrees(root):
        if branch == args.branch:
            print(path)
            return 0
    print("错误: 没有分支 %s 的隔离工作区" % args.branch, file=sys.stderr)
    return 1


def cmd_remove(args):
    root = os.path.abspath(args.root or find_root())
    target = None
    for path, branch, _ in worktrees(root):
        if branch == args.branch:
            target = path
            break
    if not target:
        print("错误: 没有分支 %s 的隔离工作区" % args.branch, file=sys.stderr)
        return 1
    if os.path.abspath(target) == root:
        print("错误: 这是主工作区，不能用 remove 删（用 git 自己管理）", file=sys.stderr)
        return 1

    if not args.force and os.path.isdir(target):
        rc, dirty, _ = git(target, ["status", "--porcelain"])
        n = len([l for l in dirty.splitlines() if l.strip()]) if rc == 0 else 0
        if n > 0:
            print("错误: 工作区有 %d 处未提交改动，删了就没了。\n"
                  "  先提交或确认不要，再跑 remove --force" % n, file=sys.stderr)
            return 1

    rc, out, err = git(root, ["worktree", "remove", target] +
                       (["--force"] if args.force else []))
    if rc != 0:
        print("错误: 移除失败: %s" % (err or out), file=sys.stderr)
        return 1
    print("已移除隔离工作区: %s" % target)
    if args.drop_branch:
        rc2, _, err2 = git(root, ["branch", "-D", args.branch])
        print("分支已删除: %s" % args.branch if rc2 == 0
              else "分支删除失败: %s" % err2)
    return 0


def cmd_prune(args):
    root = os.path.abspath(args.root or find_root())
    rc, out, err = git(root, ["worktree", "prune"])
    if rc != 0:
        print("错误: prune 失败: %s" % (err or out), file=sys.stderr)
        return 1
    print("已清理失效的工作区记录")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="工作区隔离 - 多需求/多 AI 并行互不污染（git worktree 封装）")
    ap.add_argument("--root", help="仓库根目录（默认向上找 .git）")
    sub = ap.add_subparsers(dest="cmd")

    c = sub.add_parser("create", help="新建隔离工作区")
    c.add_argument("branch", help="分支名（会被新建）")
    c.add_argument("--from", dest="base", help="基准分支（默认当前分支）")
    c.add_argument("--dir", help="工作区路径（默认仓库同级目录）")
    c.set_defaults(func=cmd_create)

    l = sub.add_parser("list", help="列出隔离工作区")
    l.set_defaults(func=cmd_list)

    p = sub.add_parser("path", help="打印工作区路径")
    p.add_argument("branch")
    p.set_defaults(func=cmd_path)

    r = sub.add_parser("remove", help="移除隔离工作区")
    r.add_argument("branch")
    r.add_argument("--force", action="store_true", help="有未提交改动也删")
    r.add_argument("--drop-branch", action="store_true", help="同时删除分支")
    r.set_defaults(func=cmd_remove)

    pr = sub.add_parser("prune", help="清理失效记录")
    pr.set_defaults(func=cmd_prune)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

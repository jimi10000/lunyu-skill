#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""失控自检 - 过则勿惮改（循环与反复失败的检测、报告、原因分析）

论语出处：《论语·学而》「过则勿惮改」——错了不要怕改，
但前提是**先承认自己错了、说清楚错在哪**。放到 AI 执行里：
同一个动作重复三遍、同一个错误撞三次，不是「更努力一点就能过」，
是走错路了。这时候继续重试只会烧 token、改坏代码、还把用户蒙在鼓里。

本脚本解决三件事：
  1. 检测  —— 从执行轨迹里认出「循环 / 反复失败 / 无进展空转」
  2. 报告  —— 主动输出一份给人看的诊断报告（不是闷头继续跑）
  3. 归因  —— 按证据给出「最可能的原因」+ 每条原因的验证方法，不编造

检测规则（默认阈值，可用参数调）：
  repeat_cmd     同一命令/动作连续出现 >= 3 次
  repeat_error   同一错误签名出现 >= 3 次（跨命令也算）
  fail_streak    连续失败 >= 3 次
  no_progress    最近 >= 6 步没有任何成功记录
  budget         本次任务累计动作数超过预算（默认 40）

退出码：
  0 = 未检测到失控（可以继续）
  1 = 检测到失控，**必须停下来报告**（供门禁 / CI 使用）
  2 = 参数错误
  3 = 轨迹文件损坏（不猜、不静默吞）

命令：
  log      记录一步动作（action / status / error / signature）
  check    检测是否失控，输出结论与证据
  report   生成完整诊断报告（现象 / 证据 / 原因分析 / 建议 / 待确认）
  reset    清空轨迹
  budget   查看或设置动作预算

用法示例：
  python scripts/loop_guard.py log --action "跑单测" --status fail \
      --error "ModuleNotFoundError: foo" --signature "pytest tests/"
  python scripts/loop_guard.py check
  python scripts/loop_guard.py report --out .lunyu/失控报告.md
  python scripts/loop_guard.py budget --max 30
  python scripts/loop_guard.py reset --yes

零外部依赖，纯标准库。轨迹落 .lunyu/loop_guard.json（不进技能包）。
"""
import argparse
import json
import os
import sys
import hashlib
from datetime import datetime

TRACE_FILE = "loop_guard.json"
DEFAULT_BUDGET = 40
DEFAULT_REPEAT = 3
DEFAULT_FAIL_STREAK = 3
DEFAULT_NO_PROGRESS = 6
MAX_TRACE = 200  # 只留最近 200 步，防止无限膨胀


# ── 归因知识库：每类原因带「证据特征 / 验证方法 / 建议动作」─────────
# 只给「可能原因 + 怎么验证」，不下断言。验证方法是可执行的，不是空话。
CAUSES = [
    {
        "code": "ENV_DRIFT",
        "name": "环境漂移 / 依赖缺失",
        "signals": ["ModuleNotFoundError", "command not found", "No such file",
                    "ImportError", "cannot find module", "找不到", "不是内部或外部命令"],
        "why": "报错集中在「东西不存在」，同一条命令重试多少次都不会变出来。",
        "verify": "跑 python scripts/env_check.py verify，对比 .lunyu/env.lock 看工具链/依赖是否漂移",
        "action": "先修环境再重跑原命令；别在代码里打补丁绕过缺依赖",
    },
    {
        "code": "WRONG_PATH",
        "name": "路径 / 目标定位错了",
        "signals": ["FileNotFoundError", "No such file or directory", "404",
                    "not a git repository", "path", "路径"],
        "why": "反复对同一个不存在的位置操作，说明目标本身找错了。",
        "verify": "跑 python scripts/locate.py --keyword <目标名> 正向定位，确认真实路径",
        "action": "停止对旧路径重试，用定位结果重设目标；同时记进 HANDOVER",
    },
    {
        "code": "STALE_CONTEXT",
        "name": "上下文失效 / 前提已变",
        "signals": ["Connection was reset", "timeout", "timed out", "401", "403",
                    "permission denied", "Connection refused", "EOF"],
        "why": "外部依赖（网络/权限/凭据/服务）变了，沿用旧前提的每次重试都是白费。",
        "verify": "手工复现一次最小请求；检查凭据/网络/服务状态是否和开始时一致",
        "action": "换通道或明确告知用户外部阻塞；不要靠重试碰运气",
    },
    {
        "code": "WRONG_HYPOTHESIS",
        "name": "根因假设错了，一直在改错的地方",
        "signals": ["AssertionError", "FAILED", "assert", "still failing", "expected"],
        "why": "同一处代码反复改、测试仍以同样方式失败 = 改的不是真正的原因。",
        "verify": "读完整失败栈定位第一行自己代码；跑 python scripts/impact.py --file <文件> 看谁在调用",
        "action": "回到失败证据重新立假设，必要时把已否决假设写进 HANDOVER 防止又绕回去",
    },
    {
        "code": "NO_ACCEPTANCE",
        "name": "没有明确验收点，不知道什么算做完",
        "signals": ["再试", "换个方式", "retry", "again", "继续"],
        "why": "动作在换花样但没有可判定的完成标准，容易变成无限微调。",
        "verify": "检查 python scripts/plan.py list 里当前任务的验收点是否为空",
        "action": "用 plan.py set-acceptance 补一条可判定的验收点，再决定继续还是停",
    },
    {
        "code": "SCOPE_CREEP",
        "name": "任务没拆开，一把梭导致反复回滚",
        "signals": ["conflict", "merge", "revert", "回滚", "覆盖"],
        "why": "多个改动互相踩，单独看每步都对，合起来就冲突。",
        "verify": "看轨迹里是否在多个不相关文件间来回跳；检查 git status 改动面",
        "action": "用 plan.py 拆成小任务、worktree.py 隔离，一次只推一个",
    },
    {
        "code": "UNKNOWN",
        "name": "证据不足，无法归因",
        "signals": [],
        "why": "轨迹里没有可识别的错误特征，或错误文本太短不足以判断。",
        "verify": "补齐最近 3 步的完整错误文本（--error 传原文，不要只写「失败了」）",
        "action": "如实报告「原因未确定」，列出已排除项，请用户补充信息；**不要编一个原因**",
    },
]


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


def store_path(root):
    d = os.path.join(root, ".lunyu")
    return d, os.path.join(d, TRACE_FILE)


def read_state(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
            raise ValueError("结构不对")
        data.setdefault("budget", DEFAULT_BUDGET)
        return data
    except FileNotFoundError:
        return {"budget": DEFAULT_BUDGET, "steps": []}
    except (OSError, ValueError) as e:
        print("错误：轨迹文件损坏，不猜测、不静默跳过：%s" % e, file=sys.stderr)
        print("处理：确认后跑 reset --yes 清空，或手工修复 %s" % path, file=sys.stderr)
        sys.exit(3)


def write_state(path, state):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def err_signature(error):
    """错误签名：先归一化剥掉易变部分，再哈希，让同一错误能聚合。

    报错里常带时间戳、行号、临时路径、内存地址、耗时——这些每次都不同，
    直接哈希会把「同一个错误」拆成 N 个签名，检测就失效了。
    """
    import re
    if not error:
        return ""
    s = error.strip().lower()
    s = re.sub(r"\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}(?:\.\d+)?z?", " ", s)  # 时间戳
    s = re.sub(r"\b0x[0-9a-f]{4,}\b", " ", s)                                   # 内存地址
    s = re.sub(r"\b[0-9a-f]{16,}\b", " ", s)                                     # 长哈希/id
    s = re.sub(r"(?:[a-z]:)?[/\\][^\s:,)]+[/\\][^\s:,)]+", " ", s)               # 绝对路径
    s = re.sub(r"\btmp[^\s/\\]*|/tmp[^\s]*", " ", s)                             # 临时目录
    s = re.sub(r"\bline \d+|\:\d+\:\d+|\b\d+(?:\.\d+)?(?:ms|s|秒)\b", " ", s)   # 行号/耗时
    s = re.sub(r"\d+", " ", s)                                                    # 其余数字
    s = re.sub(r"\s+", " ", s).strip()
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:8] if s else ""


def cmd_signature(action, signature):
    return (signature or action or "").strip()


# ── 检测 ────────────────────────────────────────────────────────
def detect(steps, repeat=DEFAULT_REPEAT, fail_streak=DEFAULT_FAIL_STREAK,
           no_progress=DEFAULT_NO_PROGRESS, budget=DEFAULT_BUDGET):
    findings = []
    recent = steps[-max(no_progress, fail_streak, repeat):]

    # 1. 同一命令重复
    tail = steps[-repeat:] if repeat > 0 else []
    if len(tail) == repeat:
        keys = [s.get("cmd_sig", "") for s in tail]
        if keys[0] and len(set(keys)) == 1:
            findings.append({
                "type": "repeat_cmd", "label": "同一动作连续重复 %d 次" % repeat,
                "evidence": [s.get("action", "") for s in tail],
                "severity": "stop",
            })

    # 2. 同一错误重复（跨命令）
    esig = [s.get("err_sig", "") for s in steps if s.get("err_sig")]
    if esig:
        top = max(set(esig), key=esig.count)
        n = esig.count(top)
        if n >= repeat:
            samples = [s.get("error", "") for s in steps if s.get("err_sig") == top][:3]
            findings.append({
                "type": "repeat_error", "label": "同一错误出现 %d 次" % n,
                "evidence": samples, "severity": "stop",
            })

    # 3. 连续失败
    streak, best = 0, 0
    for s in steps:
        streak = streak + 1 if s.get("status") == "fail" else 0
        best = max(best, streak)
    if best >= fail_streak:
        findings.append({
            "type": "fail_streak", "label": "连续失败 %d 次" % best,
            "evidence": [s.get("action", "") for s in steps[-best:]],
            "severity": "stop",
        })

    # 4. 无进展空转
    window = steps[-no_progress:]
    if len(window) >= no_progress and not any(s.get("status") == "ok" for s in window):
        findings.append({
            "type": "no_progress", "label": "最近 %d 步没有任何成功记录" % no_progress,
            "evidence": [s.get("action", "") for s in window], "severity": "stop",
        })

    # 5. 超预算
    if len(steps) >= budget:
        findings.append({
            "type": "budget", "label": "累计 %d 步，已达预算 %d" % (len(steps), budget),
            "evidence": ["共 %d 步，成功 %d 步" % (
                len(steps), sum(1 for s in steps if s.get("status") == "ok"))],
            "severity": "stop",
        })
    return findings


def rank_causes(steps, findings):
    """按错误文本里的信号词给原因打分。没有信号就诚实地回 UNKNOWN。"""
    text = " ".join((s.get("error") or "") + " " + (s.get("action") or "")
                    for s in steps).lower()
    scored = []
    for c in CAUSES:
        if not c["signals"]:
            continue
        hits = [sig for sig in c["signals"] if sig.lower() in text]
        if hits:
            scored.append((len(hits), c, hits))
    scored.sort(key=lambda x: -x[0])
    out = [{
        "code": c["code"], "name": c["name"], "why": c["why"],
        "verify": c["verify"], "action": c["action"],
        "matched_signals": hits, "confidence": "有信号词命中（仍需验证，不是结论）",
    } for _, c, hits in scored[:3]]
    if not out:
        u = next(c for c in CAUSES if c["code"] == "UNKNOWN")
        out = [{
            "code": u["code"], "name": u["name"], "why": u["why"],
            "verify": u["verify"], "action": u["action"],
            "matched_signals": [], "confidence": "证据不足，未归因",
        }]
    return out


def build_report(state, findings, causes):
    steps = state.get("steps", [])
    lines = ["# 失控诊断报告（主动上报）", "",
             "> 生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "> 本报告的用途是**停下来向人报告**，不是给自己继续重试找理由。", "",
             "## 一、现象（检测到什么）", ""]
    if findings:
        for f in findings:
            lines.append("- **%s**（%s）" % (f["label"], f["type"]))
    else:
        lines.append("- 未检测到失控信号")
    lines += ["", "## 二、证据（不是感觉，是轨迹）", ""]
    if not steps:
        lines.append("- 轨迹为空，无法举证")
    else:
        lines.append("| # | 动作 | 结果 | 错误摘要 |")
        lines.append("|---|---|---|---|")
        for i, s in enumerate(steps[-10:], 1):
            e = (s.get("error") or "").replace("|", "\\|")[:80]
            lines.append("| %d | %s | %s | %s |" % (
                i, (s.get("action") or "").replace("|", "\\|"),
                s.get("status", ""), e))
    lines += ["", "## 三、可能原因（附验证方法，未验证不下结论）", ""]
    for i, c in enumerate(causes, 1):
        lines += ["**%d. %s**（%s）" % (i, c["name"], c["code"]),
                  "- 判断依据：%s" % c["why"],
                  "- 命中信号：%s" % (", ".join(c["matched_signals"]) or "无"),
                  "- 可信度：%s" % c["confidence"],
                  "- 怎么验证：%s" % c["verify"],
                  "- 建议动作：%s" % c["action"], ""]
    lines += ["## 四、必须停下来", "",
              "- 已停止继续重试。**重试同一动作不会改变结果**。",
              "- 不把「还在调」包装成「已完成」；没跑过的验证明确写未验证。", "",
              "## 五、建议下一步（按优先级）", ""]
    for c in causes[:2]:
        lines.append("1. 先验证「%s」：%s" % (c["name"], c["verify"]))
    lines += ["2. 若验证不成立，划掉该假设，补新证据再立假设；已否决的写进 HANDOVER 防止绕回去。",
              "3. 环境/网络/权限类阻塞：直接如实上报，等用户决策，不自己硬扛。", "",
              "## 六、需要用户确认", "",
              "- [ ] 上述原因哪条成立（或补充我没看到的上下文）",
              "- [ ] 是继续修、换方案，还是先搁置",
              "- [ ] 有没有外部条件（凭据/网络/目标环境）需要你来提供", ""]
    return "\n".join(lines)


# ── 子命令 ──────────────────────────────────────────────────────
def cmd_log(args):
    _, path = store_path(find_root(args.root))
    state = read_state(path)
    step = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "action": args.action,
        "status": args.status,
        "error": args.error or "",
        "cmd_sig": cmd_signature(args.action, args.signature),
        "err_sig": err_signature(args.error or ""),
    }
    state["steps"].append(step)
    state["steps"] = state["steps"][-MAX_TRACE:]
    write_state(path, state)
    print("已记录：%s [%s]（累计 %d 步）" % (args.action, args.status, len(state["steps"])))
    return 0


def cmd_check(args):
    _, path = store_path(find_root(args.root))
    state = read_state(path)
    findings = detect(state.get("steps", []), args.repeat, args.fail_streak,
                      args.no_progress, state.get("budget", DEFAULT_BUDGET))
    causes = rank_causes(state.get("steps", []), findings)
    if args.json:
        print(json.dumps({"stuck": bool(findings), "findings": findings,
                          "causes": causes, "steps": len(state.get("steps", []))},
                         ensure_ascii=False, indent=2))
    elif not findings:
        print("未检测到失控信号（共 %d 步），可以继续。" % len(state.get("steps", [])))
    else:
        print("⛔ 检测到失控，必须停止重试并向用户报告：")
        for f in findings:
            print("  - %s" % f["label"])
        print("\n可能原因（需验证，不是结论）：")
        for c in causes:
            print("  - %s：%s" % (c["name"], c["verify"]))
        print("\n生成完整报告：python scripts/loop_guard.py report --out .lunyu/失控报告.md")
    return 1 if findings else 0


def cmd_report(args):
    _, path = store_path(find_root(args.root))
    state = read_state(path)
    findings = detect(state.get("steps", []), args.repeat, args.fail_streak,
                      args.no_progress, state.get("budget", DEFAULT_BUDGET))
    causes = rank_causes(state.get("steps", []), findings)
    text = build_report(state, findings, causes)
    if args.out:
        out = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        print("报告已写入：%s" % out)
    else:
        print(text)
    return 0


def cmd_reset(args):
    _, path = store_path(find_root(args.root))
    if not args.yes:
        print("需要确认：加 --yes 才清空轨迹（防止误删证据）")
        return 2
    write_state(path, {"budget": DEFAULT_BUDGET, "steps": []})
    print("轨迹已清空，预算复位为 %d" % DEFAULT_BUDGET)
    return 0


def cmd_budget(args):
    _, path = store_path(find_root(args.root))
    state = read_state(path)
    if args.max is not None:
        if args.max < 1:
            print("预算必须 >= 1", file=sys.stderr)
            return 2
        state["budget"] = args.max
        write_state(path, state)
    print("动作预算：%d（已用 %d 步）" % (
        state.get("budget", DEFAULT_BUDGET), len(state.get("steps", []))))
    return 0


def add_common(p):
    p.add_argument("--root", help="项目根目录（默认自动向上找 .git）")


def main(argv=None):
    ap = argparse.ArgumentParser(description="失控自检：循环/反复失败的检测、主动报告与原因分析")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("log", help="记录一步动作")
    add_common(p)
    p.add_argument("--action", required=True, help="动作描述")
    p.add_argument("--status", choices=["ok", "fail"], required=True)
    p.add_argument("--error", default="", help="完整错误原文（别只写「失败了」）")
    p.add_argument("--signature", default="", help="命令签名：同一命令的不同措辞也算同一个")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("check", help="检测是否失控（退出码 1 = 必须停）")
    add_common(p)
    p.add_argument("--repeat", type=int, default=DEFAULT_REPEAT)
    p.add_argument("--fail-streak", type=int, default=DEFAULT_FAIL_STREAK)
    p.add_argument("--no-progress", type=int, default=DEFAULT_NO_PROGRESS)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("report", help="生成完整诊断报告")
    add_common(p)
    p.add_argument("--out", help="输出 md 路径（不传则打印到屏幕）")
    p.add_argument("--repeat", type=int, default=DEFAULT_REPEAT)
    p.add_argument("--fail-streak", type=int, default=DEFAULT_FAIL_STREAK)
    p.add_argument("--no-progress", type=int, default=DEFAULT_NO_PROGRESS)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("reset", help="清空轨迹")
    add_common(p)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_reset)

    p = sub.add_parser("budget", help="查看/设置动作预算")
    add_common(p)
    p.add_argument("--max", type=int, default=None)
    p.set_defaults(func=cmd_budget)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

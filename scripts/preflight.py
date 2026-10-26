#!/usr/bin/env python3
"""提交前自检 - 质量左移门禁

在 commit 前拦掉最廉价可查的问题: 硬编码密钥、大文件、调试残留、.gitignore 缺失。
可选的 lint / type / test 执行。

用法:
  python preflight.py                 # 扫描当前项目
  python preflight.py --run           # 扫描 + 跑 lint/type/test
  python preflight.py --path <dir>    # 指定目录
  python preflight.py --json          # 机器可读输出
  python preflight.py install-hook    # 安装 git pre-commit 钩子(让自检自动跑)
  python preflight.py uninstall-hook  # 卸载钩子并恢复原有备份

退出码: 0 通过 / 1 阻断(发现密钥等) / 2 仅警告
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "target", "vendor", ".next", ".nuxt", "coverage",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".lunyu", ".idea", ".vscode",
    "Pods", ".gradle", ".terraform",
}
SKIP_EXT = {
    ".lock", ".min.js", ".min.css", ".map", ".png", ".jpg", ".jpeg", ".gif",
    ".webp", ".ico", ".svg", ".woff", ".woff2", ".ttf", ".eot", ".pdf",
    ".zip", ".tar", ".gz", ".7z", ".mp4", ".mp3", ".wav", ".so", ".dll",
    ".dylib", ".exe", ".class", ".jar", ".pyc", ".wasm", ".bin",
}
# 允许显式豁免
ALLOW_MARK = ("allowlist secret", "preflight-ignore", "noqa: secret")

SECRET_PATTERNS = [
    ("AWS Access Key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Private Key Block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----")),
    ("GitHub Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}")),
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    ("Stripe Live Key", re.compile(r"\bsk_live_[0-9a-zA-Z]{24,}\b")),
    ("阿里云 AK", re.compile(r"\bLTAI[0-9A-Za-z]{12,}\b")),
    ("腾讯云 SecretId", re.compile(r"\bAKID[0-9A-Za-z]{13,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("硬编码凭证赋值", re.compile(
        r"""(?i)\b(?:api[_-]?key|apikey|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|pwd|private[_-]?key)\s*[:=]\s*['"]([^'"\s]{8,})['"]"""
    )),
]
# 明显是占位符的值不算
PLACEHOLDER = re.compile(
    r"(?i)^(x{4,}|\*{4,}|\.{3,}|your[_-]|changeme|placeholder|example|dummy|test|todo|<.*>|\$\{.*\}|%.*%|none|null|true|false)$"
)

DEBUG_PATTERNS = {
    ".js": [r"\bconsole\.(log|debug|dir)\(", r"\bdebugger\b"],
    ".jsx": [r"\bconsole\.(log|debug)\(", r"\bdebugger\b"],
    ".ts": [r"\bconsole\.(log|debug)\(", r"\bdebugger\b"],
    ".tsx": [r"\bconsole\.(log|debug)\(", r"\bdebugger\b"],
    ".vue": [r"\bconsole\.(log|debug)\(", r"\bdebugger\b"],
    ".py": [r"^\s*print\(", r"\bpdb\.set_trace\(", r"^\s*breakpoint\("],
    ".java": [r"System\.out\.print", r"\.printStackTrace\("],
    ".kt": [r"\bprintln\(", r"\.printStackTrace\("],
    ".go": [r"fmt\.Print", r"\blog\.Print"],
    ".rs": [r"\bdbg!\(", r"\bprintln!\("],
    ".php": [r"\bvar_dump\(", r"\bprint_r\("],
}
CODE_EXT = set(DEBUG_PATTERNS) | {".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".rb", ".swift", ".m", ".mm", ".scala", ".sh"}

LARGE_FILE_MB = 1.0

GITIGNORE_MUST = {
    ".env": "环境变量文件含密钥",
    "node_modules": "依赖目录",
    ".venv": "虚拟环境",
    "__pycache__": "Python 缓存",
    "dist": "构建产物",
    "build": "构建产物",
    "*.log": "日志文件",
 }

# 依赖清单 -> 生态; 能解析几个算几个, 解析不了就跳过
DEP_MANIFESTS = {
    "requirements.txt": "pip",
    "pyproject.toml": "pip",
    "package.json": "npm",
    "pom.xml": "maven",
    "build.gradle": "gradle",
}
# 生态 -> 期望存在的 lockfile
LOCKFILES = {
    "pip": ["requirements.lock", "poetry.lock", "Pipfile.lock"],
    "npm": ["package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
}
LOCKFILE_HINT = {
    "pip": "requirements.lock / poetry.lock / Pipfile.lock",
    "npm": "package-lock.json / yarn.lock / pnpm-lock.yaml",
}
# 无固定版本的写法
UNPINNED_VERSIONS = {"", "*", "latest", "release", "+", "x"}
# 已知高风险包(小样本: typosquatting 特征 + 已废弃/曾被接管的包)
RISKY_PACKAGES = {
    "requsts": "疑似 typosquatting(正确名为 requests)",
    "urlib3": "疑似 typosquatting(正确名为 urllib3)",
    "beautifulsoup": "疑似 typosquatting(正确名为 beautifulsoup4)",
    "lodahs": "疑似 typosquatting(正确名为 lodash)",
    "crossenv": "疑似 typosquatting(正确名为 cross-env)",
    "http-proxy.js": "疑似 typosquatting(正确名为 http-proxy)",
    "request": "已废弃(2020 起停止维护), 建议迁移到 axios/undici",
    "node-uuid": "已废弃, 建议迁移到 uuid",
    "event-stream": "曾发生供应链投毒事件(event-stream 3.3.6)",
    "eslint-scope": "曾发生供应链投毒事件(eslint-scope 3.7.2)",
}
SBOM_DIR = ".lunyu"
SBOM_FILE = "sbom.json"


class Report:
    def __init__(self):
        self.blockers = []
        self.warnings = []
        self.infos = []

    def block(self, msg):
        self.blockers.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def info(self, msg):
        self.infos.append(msg)


def walk_files(root, max_files=20000):
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in SKIP_EXT or fn.endswith(".min.js") or fn.endswith(".min.css"):
                continue
            p = os.path.join(dirpath, fn)
            yield p
            count += 1
            if count >= max_files:
                return


def rel(p, root):
    try:
        return os.path.relpath(p, root).replace("\\", "/")
    except ValueError:
        return p


def scan_secrets(root, rep):
    hits = 0
    for p in walk_files(root):
        ext = os.path.splitext(p)[1].lower()
        if ext not in CODE_EXT and ext not in ("", ".env", ".yaml", ".yml", ".json", ".toml", ".ini", ".conf", ".cfg", ".properties", ".xml"):
            continue
        try:
            if os.path.getsize(p) > 2 * 1024 * 1024:
                continue
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    if len(line) > 2000:
                        continue
                    low = line.lower()
                    if any(m in low for m in ALLOW_MARK):
                        continue
                    for name, pat in SECRET_PATTERNS:
                        m = pat.search(line)
                        if not m:
                            continue
                        val = m.group(1) if m.groups() else m.group(0)
                        if m.groups() and PLACEHOLDER.match(val.strip()):
                            continue
                        rep.block(f"疑似{name}: {rel(p, root)}:{lineno}")
                        hits += 1
                        break
        except (OSError, UnicodeError):
            continue
    if hits:
        rep.info("确认是误报可在该行加 `# allowlist secret` 注释")
    return hits


def scan_large_files(root, rep):
    for p in walk_files(root):
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        if size > LARGE_FILE_MB * 1024 * 1024:
            rep.warn(f"大文件 {size / 1048576:.1f}MB: {rel(p, root)}")


def scan_debug(root, rep):
    found = {}
    for p in walk_files(root):
        ext = os.path.splitext(p)[1].lower()
        pats = DEBUG_PATTERNS.get(ext)
        if not pats:
            continue
        name = rel(p, root)
        # 测试与脚本里 print 是正常的
        if any(seg in name for seg in ("test", "spec", "__main__", "scripts/", "examples/", "bench")):
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    for pat in pats:
                        if re.search(pat, line):
                            found.setdefault(name, []).append(lineno)
                            break
        except (OSError, UnicodeError):
            continue
    total = sum(len(v) for v in found.values())
    if total:
        top = sorted(found.items(), key=lambda kv: -len(kv[1]))[:5]
        detail = "; ".join(f"{k}({len(v)})" for k, v in top)
        rep.warn(f"调试残留 {total} 处: {detail}")
    return total


def scan_gitignore(root, rep):
    gi = os.path.join(root, ".gitignore")
    if not os.path.exists(gi):
        rep.warn("缺少 .gitignore, 密钥/依赖/产物可能被误提交")
        return
    with open(gi, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    missing = [f"{k} ({v})" for k, v in GITIGNORE_MUST.items() if k not in content]
    if missing:
        rep.warn(".gitignore 缺关键条目: " + ", ".join(missing))


def detect_project(root):
    """返回 (类型, lint命令, type命令, test命令)"""
    def has(*names):
        return any(os.path.exists(os.path.join(root, n)) for n in names)

    if has("package.json"):
        cmds = []
        pkg = os.path.join(root, "package.json")
        scripts = {}
        try:
            with open(pkg, "r", encoding="utf-8") as f:
                scripts = json.load(f).get("scripts", {})
        except (OSError, ValueError):
            pass
        lint = "npm run lint" if "lint" in scripts else None
        typ = "npm run typecheck" if "typecheck" in scripts else ("npx tsc --noEmit" if has("tsconfig.json") else None)
        test = "npm test" if "test" in scripts else None
        return "Node", lint, typ, test
    if has("pyproject.toml", "setup.py", "requirements.txt"):
        lint = "ruff check ." if has("ruff.toml", ".ruff.toml") or _pyproject_has(root, "ruff") else None
        typ = "mypy ." if _pyproject_has(root, "mypy") else None
        test = "pytest -q" if has("tests", "test") or _pyproject_has(root, "pytest") else None
        return "Python", lint, typ, test
    if has("go.mod"):
        return "Go", "gofmt -l .", "go vet ./...", "go test ./..."
    if has("Cargo.toml"):
        return "Rust", "cargo clippy -- -D warnings", None, "cargo test"
    if has("pom.xml"):
        return "Maven", None, None, "mvn -q test"
    if has("build.gradle", "build.gradle.kts"):
        return "Gradle", None, None, "./gradlew test"
    return None, None, None, None


def _pyproject_has(root, key):
    p = os.path.join(root, "pyproject.toml")
    if not os.path.exists(p):
        return False
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            return key in f.read()
    except OSError:
        return False


def run_cmd(cmd, root, timeout=180):
    try:
        r = subprocess.run(cmd, cwd=root, shell=True, capture_output=True,
                           text=True, timeout=timeout, errors="ignore")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"超时(>{timeout}s)"
    except OSError as e:
        return 127, str(e)


def run_gates(root, rep, lang, lint, typ, test):
    for label, cmd in (("lint", lint), ("type", typ), ("test", test)):
        if not cmd:
            rep.info(f"{label}: 未检测到配置, 跳过")
            continue
        rc, out = run_cmd(cmd, root)
        tail = "\n".join(out.strip().splitlines()[-8:])
        if rc == 0:
            rep.info(f"{label}: 通过 ({cmd})")
        elif rc == 127:
            rep.info(f"{label}: 命令不可用, 跳过 ({cmd})")
        elif rc == 124:
            rep.warn(f"{label}: 超时 ({cmd})")
        else:
            rep.block(f"{label} 失败 (exit {rc}): {cmd}\n{tail}")


# ---------------------------------------------------------------- 依赖扫描 / SBOM

def _split_spec(s):
    """把 'requests[security]>=2.0' 拆成 (名, 版本约束)"""
    s = s.strip()
    m = re.match(r"^([A-Za-z0-9._+-]+)\s*(?:\[[^\]]*\])?\s*(.*)$", s)
    if not m:
        return s, ""
    return m.group(1).strip(), m.group(2).strip().strip(",")


def _parse_requirements(text):
    """解析 requirements.txt"""
    deps = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        if "@" in line:  # 直接引用 / VCS 安装, 视为已锁定
            name, ver = _split_spec(line.split("@", 1)[0])
            deps.append((name, ver or "@ref"))
            continue
        deps.append(_split_spec(line))
    return deps


def _parse_pyproject(text):
    """极简 TOML 解析: 只取 [project].dependencies 与 [tool.poetry.dependencies]"""
    deps = []
    section = ""
    in_array = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not in_array:
            if line.startswith("["):
                section = line.strip("[]").strip()
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip().strip("\"'")
            val = val.strip()
            if section == "project" and (key == "dependencies" or key.startswith("optional-dependencies")):
                if val.startswith("["):
                    if not val.rstrip().endswith("]"):
                        in_array = True
                    for s in re.findall(r"""["']([^"']+)["']""", val):
                        deps.append(_split_spec(s))
            elif section.startswith("tool.poetry.dependencies") and key != "python":
                spec = re.findall(r"""["']([^"']*)["']""", val)
                deps.append((key, spec[0] if spec else ""))
        else:
            if line.startswith("]"):
                in_array = False
                continue
            m = re.match(r"""^["']([^"']+)["']""", line)
            if m:
                deps.append(_split_spec(m.group(1)))
    return deps


def _parse_package_json(text):
    """解析 package.json 的 dependencies / devDependencies / optionalDependencies"""
    data = json.loads(text)
    deps = []
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        for name, ver in (data.get(key) or {}).items():
            deps.append((name, str(ver)))
    return deps


def _parse_pom(text):
    """解析 pom.xml 的 <dependency> 块"""
    deps = []
    for block in re.findall(r"<dependency\b.*?</dependency>", text, re.S):
        a = re.search(r"<artifactId>\s*(.*?)\s*</artifactId>", block, re.S)
        if not a:
            continue
        v = re.search(r"<version>\s*(.*?)\s*</version>", block, re.S)
        deps.append((a.group(1), v.group(1) if v else ""))
    return deps


def _parse_gradle(text):
    """解析 build.gradle 的单串坐标写法: implementation 'group:name:version'"""
    deps = []
    pat = re.compile(
        r"""^\s*(?:implementation|api|compile|compileOnly|runtimeOnly|testImplementation|kapt)\s*\(?\s*["']([^"']+)["']""",
        re.M,
    )
    for coord in pat.findall(text):
        parts = [p for p in coord.split(":") if p]
        if not parts:
            continue
        name = parts[1] if len(parts) >= 2 else parts[0]
        ver = parts[2] if len(parts) >= 3 else ""
        deps.append((name, ver))
    return deps


def _parse_manifest(filename, eco, text):
    """返回 (依赖列表, 错误信息); 语法坏掉时返回错误信息由调用方决定是否阻断"""
    try:
        if filename == "requirements.txt":
            return _parse_requirements(text), None
        if filename == "pyproject.toml":
            # 有 tomllib(3.11+) 时先做一次严格校验, 坏语法直接暴露
            try:
                import tomllib  # noqa
                tomllib.loads(text)
            except ImportError:
                pass
            except ValueError as e:
                return [], f"TOML 语法错误: {e}"
            return _parse_pyproject(text), None
        if filename == "package.json":
            return _parse_package_json(text), None
        if filename == "pom.xml":
            import xml.etree.ElementTree as ET
            ET.fromstring(text)
            return _parse_pom(text), None
        if filename == "build.gradle":
            return _parse_gradle(text), None
    except ValueError as e:
        return [], str(e)
    except Exception as e:  # 兜底: 解析失败不算崩溃, 交由上层处理
        return [], str(e)
    return [], None


def is_unpinned(version, eco):
    """版本是否未固定(不可复现构建)"""
    v = (version or "").strip()
    if v.lower() in UNPINNED_VERSIONS:
        return True
    if eco == "pip":
        return "==" not in v
    if eco == "npm":
        return any(c in v for c in "^~><") or "||" in v or " " in v
    if eco in ("maven", "gradle"):
        return v.startswith("[") or v.startswith("(")
    return False


def write_sbom(root, data):
    """SBOM 落盘 .lunyu/sbom.json, 目录不存在则创建"""
    d = os.path.join(root, SBOM_DIR)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, SBOM_FILE)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return p


def scan_deps(root, rep):
    """依赖扫描: 无固定版本 / 缺 lockfile / 已知高风险包, 并生成 SBOM

    无依赖清单时优雅跳过(返回 None); 清单语法坏掉才阻断。
    """
    manifests = []
    for fn, eco in DEP_MANIFESTS.items():
        p = os.path.join(root, fn)
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            continue
        deps, err = _parse_manifest(fn, eco, text)
        if err:
            rep.block(f"依赖清单解析失败, 请修复后提交: {fn} ({err})")
            continue
        manifests.append((fn, eco, deps))

    if not manifests:
        rep.info("未发现依赖清单, 跳过依赖扫描")
        return None

    records = []
    unpinned = []
    risky = []
    for fn, eco, deps in manifests:
        for name, ver in deps:
            issues = []
            if is_unpinned(ver, eco):
                issues.append(f"未固定版本({ver or '空'})")
                unpinned.append(f"{name}@{ver or '空'}")
            reason = RISKY_PACKAGES.get(name.strip().lower())
            if reason:
                issues.append(f"高风险包: {reason}")
                risky.append(f"{name}: {reason}")
            records.append({
                "name": name, "version": ver or "", "ecosystem": eco,
                "source": fn, "issues": issues,
            })

    # 有清单却没 lockfile -> 构建不可复现
    for eco in sorted({eco for _, eco, _ in manifests}):
        locks = LOCKFILES.get(eco)
        if not locks:
            continue
        if not any(os.path.exists(os.path.join(root, l)) for l in locks):
            rep.warn(f"缺少 lockfile({eco}): 发现依赖清单但没有 {LOCKFILE_HINT[eco]}, 构建不可复现")

    if unpinned:
        show = ", ".join(unpinned[:5]) + (" ..." if len(unpinned) > 5 else "")
        rep.warn(f"依赖未固定版本 {len(unpinned)} 项: {show}")
    for item in risky:
        rep.warn(f"已知高风险依赖 {item}")

    sbom = {
        "generated_by": "lunyu-preflight",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "root": root,
        "manifests": [{"file": fn, "ecosystem": eco, "count": len(deps)} for fn, eco, deps in manifests],
        "lockfiles": {eco: [l for l in LOCKFILES.get(eco, []) if os.path.exists(os.path.join(root, l))]
                      for eco in sorted({eco for _, eco, _ in manifests})},
        "dependencies": records,
        "summary": {"total": len(records), "unpinned": len(unpinned), "risky": len(risky)},
    }
    sbom_path = write_sbom(root, sbom)
    rep.info(f"SBOM 已生成: {rel(sbom_path, root)} (依赖 {len(records)} 项)")
    return sbom


# ---------------------------------------------------------------- pre-commit 钩子

HOOK_NAME = "pre-commit"
HOOK_BACKUP = "pre-commit.lunyu.bak"
HOOK_MARKER = "lunyu-pre-commit-hook"


def git_out(root, args):
    """执行 git 命令, 返回 (returncode, stdout.strip())"""
    try:
        r = subprocess.run(["git"] + list(args), cwd=root, capture_output=True,
                           text=True, timeout=20, errors="ignore")
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""
    return r.returncode, (r.stdout or "").strip()


def resolve_hooks_dir(root):
    """定位 hooks 目录: 复用 core.hooksPath, 否则回落到 .git/hooks

    返回 (仓库根目录, hooks目录), 非 git 仓库返回 (None, None)
    """
    rc, out = git_out(root, ["rev-parse", "--show-toplevel"])
    if rc != 0 or not out:
        return None, None
    top = os.path.abspath(out)
    rc2, hp = git_out(root, ["config", "--get", "core.hooksPath"])
    if rc2 == 0 and hp:
        hooks = hp if os.path.isabs(hp) else os.path.join(top, hp)
        return top, os.path.abspath(hooks)
    rc3, gd = git_out(root, ["rev-parse", "--git-dir"])
    gitdir = gd if (rc3 == 0 and gd) else ".git"
    if not os.path.isabs(gitdir):
        gitdir = os.path.join(top, gitdir)
    return top, os.path.abspath(os.path.join(gitdir, "hooks"))


def _python_exe():
    """钩子里的解释器路径; Windows 下转成正斜杠便于 sh 解析"""
    return _sh(sys.executable or "python")


def _preflight_path():
    return _sh(os.path.abspath(__file__))


def _sh(p):
    """Windows 路径转成正斜杠, 避免在 sh 里被当成转义"""
    return p.replace("\\", "/")


def _hook_body(repo, py_exe, preflight_py):
    """POSIX shell 钩子: Git for Windows 自带 sh, 同一份脚本两边都能跑"""
    repo = _sh(repo)
    return (
        "#!/bin/sh\n"
        f"# {HOOK_MARKER} 由 preflight.py install-hook 生成\n"
        f"# 卸载: \"{py_exe}\" \"{preflight_py}\" uninstall-hook --path {repo}\n"
        "# 临时绕过: git commit --no-verify\n"
        f"PY=\"{py_exe}\"\n"
        f"PF=\"{preflight_py}\"\n"
        f"ROOT=\"{repo}\"\n"
        "if [ ! -f \"$PF\" ]; then\n"
        "  echo '[lunyu] 找不到 preflight.py, 跳过自检'\n"
        "  exit 0\n"
        "fi\n"
        "\"$PY\" \"$PF\" --path \"$ROOT\"\n"
        "rc=$?\n"
        "if [ \"$rc\" -eq 1 ]; then\n"
        "  echo '[lunyu] preflight 阻断提交, 修复后再提交; 紧急情况用 git commit --no-verify'\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n"
    )


def _chmod_x(path):
    try:
        os.chmod(path, 0o755)
    except OSError:
        pass


def install_hook(root):
    """安装 pre-commit 钩子; 已存在同名钩子先备份。返回 (是否成功, 中文说明行)"""
    repo, hooks = resolve_hooks_dir(root)
    if not hooks:
        return False, [
            f"不是 git 仓库: {root}",
            "提示: 先执行 git init, 或用 --path 指向仓库根目录",
        ]
    target = repo or root
    os.makedirs(hooks, exist_ok=True)
    hook = os.path.join(hooks, HOOK_NAME)
    backup = os.path.join(hooks, HOOK_BACKUP)
    lines = []

    if os.path.exists(hook):
        try:
            with open(hook, "r", encoding="utf-8", errors="ignore") as f:
                old = f.read()
        except OSError:
            old = ""
        if HOOK_MARKER in old:
            lines.append("已存在 lunyu 钩子, 覆盖更新")
        else:
            shutil.copyfile(hook, backup)
            lines.append(f"已有 pre-commit 钩子, 已备份为 {HOOK_BACKUP} (卸载时可自动恢复)")

    body = _hook_body(target, _python_exe(), _preflight_path())
    with open(hook, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    _chmod_x(hook)

    lines.append(f"已安装 pre-commit 钩子: {hook}")
    lines.append(f"hooks 目录(已复用 core.hooksPath): {hooks}")
    lines.append("之后每次 git commit 会自动跑 preflight; 阻断(exit 1)时提交被拒")
    lines.append(f"卸载: python {_preflight_path()} uninstall-hook --path {target}")
    return True, lines


def uninstall_hook(root):
    """卸载 lunyu 写入的钩子, 有备份则恢复。返回 (是否成功, 中文说明行)"""
    repo, hooks = resolve_hooks_dir(root)
    if not hooks:
        return False, [f"不是 git 仓库: {root}"]
    hook = os.path.join(hooks, HOOK_NAME)
    backup = os.path.join(hooks, HOOK_BACKUP)
    lines = []

    if os.path.exists(hook):
        try:
            with open(hook, "r", encoding="utf-8", errors="ignore") as f:
                old = f.read()
        except OSError:
            old = ""
        if HOOK_MARKER not in old:
            return True, [
                f"现有 {HOOK_NAME} 不是 lunyu 写入的, 未做改动: {hook}",
                "如确需删除请手动处理",
            ]
        os.remove(hook)
        lines.append(f"已删除 lunyu 钩子: {hook}")
    else:
        lines.append(f"未发现 {HOOK_NAME} 钩子, 无需删除")

    if os.path.exists(backup):
        shutil.move(backup, hook)
        lines.append(f"已恢复原有钩子备份: {HOOK_BACKUP} -> {HOOK_NAME}")
    lines.append("自检不再自动执行, 可手动运行: python preflight.py")
    return True, lines


def main():
    ap = argparse.ArgumentParser(description="提交前自检")
    ap.add_argument("--path", default=".", help="项目目录")
    ap.add_argument("--run", action="store_true", help="执行 lint/type/test")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    ap.add_argument("--skip-secrets", action="store_true")
    ap.add_argument("--skip-deps", action="store_true", help="跳过依赖扫描")
    # 子命令可选: 不传时仍是完整扫描, 保证旧用法不变
    sub = ap.add_subparsers(dest="command", metavar="{install-hook,uninstall-hook}")
    for name, helptext in (("install-hook", "安装 git pre-commit 钩子, 让自检自动跑"),
                           ("uninstall-hook", "卸载 git pre-commit 钩子并恢复备份")):
        sp = sub.add_parser(name, help=helptext)
        # SUPPRESS: 子命令未显式传时不覆盖全局已解析的值
        sp.add_argument("--path", default=argparse.SUPPRESS, help="仓库目录")
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="JSON 输出")
    args = ap.parse_args()

    root = os.path.abspath(args.path)
    if not os.path.isdir(root):
        print(f"目录不存在: {root}")
        sys.exit(1)

    if args.command in ("install-hook", "uninstall-hook"):
        ok, lines = (install_hook(root) if args.command == "install-hook"
                     else uninstall_hook(root))
        if getattr(args, "json", False):
            print(json.dumps({"command": args.command, "ok": ok, "messages": lines},
                             ensure_ascii=False, indent=2))
        else:
            print("=" * 60)
            print(f"{args.command}  {root}")
            print("=" * 60)
            for line in lines:
                print(f"  - {line}")
        sys.exit(0 if ok else 1)

    rep = Report()
    if not args.skip_secrets:
        scan_secrets(root, rep)
    scan_large_files(root, rep)
    scan_debug(root, rep)
    scan_gitignore(root, rep)
    if not args.skip_deps:
        scan_deps(root, rep)

    lang, lint, typ, test = detect_project(root)
    if lang:
        rep.info(f"识别项目类型: {lang}")
    else:
        rep.info("未识别项目类型, 仅做通用扫描")
    if args.run and lang:
        run_gates(root, rep, lang, lint, typ, test)

    code = 0
    if rep.blockers:
        code = 1
    elif rep.warnings:
        code = 2

    if args.json:
        print(json.dumps({
            "root": root, "lang": lang, "exit_code": code,
            "blockers": rep.blockers, "warnings": rep.warnings, "infos": rep.infos,
        }, ensure_ascii=False, indent=2))
        sys.exit(code)

    print("=" * 60)
    print(f"提交前自检  {root}")
    print("=" * 60)
    if rep.blockers:
        print(f"\n[阻断] {len(rep.blockers)} 项 —— 必须处理才能提交")
        for m in rep.blockers:
            print(f"  X {m}")
    if rep.warnings:
        print(f"\n[警告] {len(rep.warnings)} 项")
        for m in rep.warnings:
            print(f"  ! {m}")
    if rep.infos:
        print("\n[信息]")
        for m in rep.infos:
            print(f"  - {m}")
    print()
    if code == 0:
        print("结论: 通过, 可以提交")
    elif code == 1:
        print("结论: 阻断, 修完再提交")
    else:
        print("结论: 通过(有警告), 建议处理")
    sys.exit(code)


if __name__ == "__main__":
    main()

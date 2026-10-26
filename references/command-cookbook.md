# 脚本命令手册

> 自 SKILL.md 下沉：各脚本的完整命令示例与输出说明。按需加载。

## flow.py（判通道）

```bash
python scripts/flow.py            # 读 git diff 自动判通道
python scripts/flow.py --staged   # 只看已暂存
```

---

## logkit.py（Step 5 分类日志）

### 5.1 分类日志（必做，非可选）

**只要不是一次性脚本，就必须接入分类日志系统。** 日志是事后排错的唯一证据，事后再补等于没有。

```bash
python scripts/logkit.py init --lang python --dest ./src/logkit   # 或 --lang ts / both
```

生成的系统解决四件事：

| 能力 | 解决什么问题 |
|---|---|
| **按问题域分类**（payment/db/auth/third...） | 排错只看 `payment.log`，不被全量日志淹没 |
| **trace_id 全链路串联** | 一次请求跨 10 个模块，grep 一个 id 全串起来 |
| **严格分级** DEBUG/INFO/WARN/ERROR/FATAL | 「所有异常都 error」和「所有事都 info」都等于没分级 |
| **结构化字段 + 耗时埋点** | `log.info("msg", order_id=x, cost_ms=12)` 可聚合可查 |

**分级铁律**：

- `INFO` 记**业务事实**（谁做了什么、结果如何），不记「进入函数」
- `WARN` 记**可恢复异常**、降级、慢操作、业务规则拒绝
- `ERROR` 记**需人介入的故障**，且**必须带异常栈**
- 用户输错密码 → WARN，不是 ERROR。这是最高频的误用

**错误日志三要素**（缺一条这条日志就白记）：
1. 异常栈（Python `exc_info=True` / TS 传 `err` 对象）
2. 上下文快照（关键入参、ID、状态）
3. trace_id（能反查整条链路）

分类表、脱敏、接日志平台的细节见生成后的 `logkit/README.md`。


---

## preflight.py（Step 6 提交前扫描）

### 6.1 提交前先扫（左移，成本最低的一道）

**在 commit 之前跑，不要等 CR 或上线：**

```bash
python scripts/preflight.py          # 扫密钥/大文件/调试残留/.gitignore
python scripts/preflight.py --run    # 额外跑 lint + 类型检查 + 单测
```

退出码：`0` 通过 / `1` 阻断（发现密钥等，禁止提交）/ `2` 仅有警告。

它拦的是人眼在 CR 里根本看不出来的东西：

- **硬编码密钥**：AWS/GitHub/Stripe/阿里云/腾讯云 Key、私钥块、JWT、`password = "xxx"` 赋值（占位符如 `your_key_here` 自动放行，不误报）
- **调试残留**：`console.log` / `print` / `debugger` / `printStackTrace`
- **大文件**：>1MB 的意外文件（依赖没被 ignore、模型文件误入）
- **.gitignore 缺项**：`.env` / `node_modules` / `dist` 未忽略 = 密钥随时会泄露
- **依赖风险**（`scan_deps`）：无固定版本（`*`/`latest`/pip 无 `==`）、无 lockfile、已知高风险包 → 警告；同时生成 SBOM 落盘 `.lunyu/sbom.json`

**别靠人记着跑——装成钩子**（君子成人之美：让正确的事容易做，错误的事做不成）：

```bash
python scripts/preflight.py install-hook      # 写入 .git/hooks/pre-commit
python scripts/preflight.py uninstall-hook    # 卸载并恢复原钩子
```

已有同名钩子会先备份成 `pre-commit.lunyu.bak` 再写入，**不会覆盖别人的钩子**。
要求「提交前先跑」却只能手动跑，是典型口号——装一次钩子，这条要求才真的生效。

---

## bug_ledger.py（Step 6 / 7 / 9 缺陷台账）

### 6.4 缺陷登记

自测发现问题**立刻登记**，别记在脑子里：

```bash
python scripts/bug_ledger.py add --title "标题" --priority P1 \
  --repro "复现步骤" --expected "期望行为" --related-pr "PR-123"
```

分级：**P0** 阻断核心流程/线上故障/数据损坏/安全漏洞，立即修；**P1** 主要功能异常，本迭代必修；**P2** 次要异常/交互瑕疵，排后续；**P3** 优化建议。

状态流转：`新建 → 修复中 → 自测通过 → CR验证 → 关闭`，回归失败则重开。完整规范见 `references/bug-triage.md`。

**不迁怒，不贰过**——关闭缺陷必须留下**防复发证据**，否则同一个坑会摔第二次：

```bash
python scripts/bug_ledger.py update --id BUG-0001 --status 关闭 \
  --root-cause "循环未判空数组" --regression "tests/test_x.py::test_empty"
```

关闭时若缺 `root_cause`（或仍是「未定」）或缺 `regression`，**脚本直接拒绝关闭（退出码 1）**。
确实无法复现的用 `--force` 豁免，但要写明理由。**修完就算完了，等于没修。**

---

## release_note.py（Step 8 版本归档）

## Step 8 · 温故知新：合并 + 版本归档 + Tag

一条命令生成存档记录、CHANGELOG 条目和 tag/合并/回滚命令：

```bash
python scripts/release_note.py tag --version 1.2.0 --branch main --baseline dev \
  --summary "变更摘要" --changes "条目1" "条目2"
```

脚本自动：校验 SemVer、拒绝重复版本、关联本次已关闭缺陷、检查工作区脏读、生成 CHANGELOG、给出回滚预案。

**构建产物摘要必须入库**（交付铁律：安装包 + md5，纯文字不算交付）：

```bash
python scripts/release_note.py tag --version 1.2.0 --branch main \
  --summary "变更摘要" --artifact ./dist/app.apk --artifact ./dist/app.zip
```

`--artifact` 自动算 **sha256** 存进版本记录；回滚预案（命令/影响范围/校验方式）**落盘**，
不再只在终端打印。`show <version>` 可原样回显——**回滚后能验证产物是否一致**。

版本号：MAJOR（不兼容）.MINOR（新功能）.PATCH（修复）。正式 tag 加 `v` 前缀：`v1.2.0`。

回滚预案必须含：回滚命令、影响范围、校验方式（怎么确认真回滚成功）。

**交付物**：版本存档记录 + CHANGELOG 更新 + tag/合并/回滚命令

---

## patrol.py（主动巡检）

```bash
python scripts/patrol.py                    # 全量巡检
python scripts/patrol.py --json             # 机器可读，适合挂 CI
python scripts/patrol.py --due-days 7       # 缺陷超期阈值
```

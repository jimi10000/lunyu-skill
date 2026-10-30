# 论语 · 企业级研发流水线

> **一句话定位**：把企业研发流程（需求→方案→编码→自测→评审→归档→复盘）压缩成一套 AI 可执行的 12 步流水线，每一步都有脚本和交付物模板，让 AI 不只是「写个函数」，而是「陪你走完一个完整迭代」。

> 📌 **第一次接触本项目？** 先看 [`项目介绍.md`](项目介绍.md) —— 一页讲清「这是什么、解决什么、怎么用」。本文件是面向开发者/贡献者的完整说明。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.4.0-blue.svg)](CHANGELOG.md)
[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-Compatible-green)](https://skills.sh)

---

## 触发场景

以下场景最适合直接使用本技能：

- 你要**写代码 / 开发功能 / 重构 / 搭项目**，希望按正规流程走一遍（需求澄清→技术方案→编码→自测→CR→归档）
- 你要处理 **bug / 缺陷 / 事故**，需要登记台账、根因分析、防复发闭环
- 你要**发版本 / 打 tag / 写 CHANGELOG / 回滚**，需要版本归档与回滚预案
- 你要**日报 / 周报 / 项目总结**，希望自动汇总 `.lunyu/` 里的台账、存档、CHANGELOG
- 你希望 AI **踩过的坑能沉淀复用**（经验库）、**没人催也主动巡检**（自驱体检）

**不适用**：一行修复、纯代码解释问答、只读代码、用户明确说不需要流程的一次性脚本（此时应走快速通道或直接跳过）。

## 30 秒上手

```bash
# 1. 接到需求先判通道（别把 30 行脚本走成 12 步）
python scripts/flow.py

# 2. 写代码时接入分类日志（非一次性脚本必做）
python scripts/logkit.py init --lang python --dest ./src/logkit

# 3. 提交前扫密钥/调试残留（可装成 pre-commit 钩子）
python scripts/preflight.py

# 4. 自测发现缺陷立刻登记（P0-P3 + 根因防复发）
python scripts/bug_ledger.py add --title "空数组越界" --priority P1

# 5. 发版：一条命令生成存档+CHANGELOG+tag/回滚
python scripts/release_note.py tag --version 1.0.0 --summary "首个版本"

# 6. 每天下班前自动出日报
python scripts/report.py daily --project "我的项目" --body "完成发布链路"
```

> 完整命令见下文「脚本一览」与 `references/command-cookbook.md`。

## 前后对比

> 📊 占位：此处放一张「无流程 vs 有流程」对比图（如：散落的需求/代码/文档 vs 统一 `.lunyu/` 台账 + 可追溯版本链）。待补充。

| 维度 | 没有 lunyu | 有 lunyu |
|---|---|---|
| 需求 | 口头对齐，做完发现理解偏了 | 需求确认单 + In/Out Scope + 验收标准 |
| 方案 | 直接开写，为什么选这个说不清 | 技术方案含设计取舍 + ADR 决策留痕 |
| 编码 | 凭印象写，API 对不上真实工程 | 源码优先 + TDD 红绿重构 + 分类日志 |
| 自测 | 「应该能跑」 | 实际运行 + 密钥扫描 + 缺陷台账 |
| 发版 | 版本号乱跳，回滚靠猜 | 存档 + CHANGELOG + tag/回滚预案 |
| 复盘 | 踩过的坑再踩一次 | 经验库沉淀 + 巡检复用 |

## 为什么做这个

市面上大多数 AI 编码助手只做「写代码」这一步。**没人管需求澄清、范围评审、方案取舍、缺陷台账、版本归档**。

论语把正规企业研发流程压缩成 12 步，每一步都有可执行的脚本和交付物模板，让 AI 不是「帮你写个函数」，而是「陪你走完一个完整迭代」。

### 五条底层准则

| 论语 | 工程含义 |
|---|---|
| **君子有所不为** | 先划红线，违规的不接 |
| **叩其两端而竭焉** | 需求两头都问清，禁止脑补 |
| **名不正则言不顺** | 范围不划清，后面全是扯皮 |
| **工欲善其事，必先利其器** | 方案定清楚再动手 |
| **三人行，必有我师** | 先看别人怎么做的，不重复造轮子 |
| **文质彬彬，然后君子** | 可靠与可维护并重，糙码和炫技都不可取 |
| **学而时习之** | 写完就测，测完再算完 |
| **见贤思齐，见不贤而内自省** | 评审既挑别人的刺，也照自己的镜子 |
| **温故而知新** | 版本可追溯，才能回得去、看得清 |
| **人无远虑，必有近忧** | 风险前置，别等炸了才想 |
| **吾日三省吾身** | 每轮必复盘，失误要落成规矩 |
| **无可无不可** | 收尾按需选路，不硬套模板 |

## 安装

```bash
# 方式一：直接复制到 WorkBuddy skills 目录
cp -r lunyu ~/.workbuddy/skills/

# 方式二：通过 WorkBuddy 技能市场安装（待上架）
# 方式三：npx skills add <your-repo>/lunyu
```

## 快速上手

### 1. 接到编码需求时

```bash
# 第一步：判通道（别把 30 行脚本走成 12 步）
python scripts/flow.py
```

```
通道判定: 【快速通道】
依据    : 小改动 1 文件 5 行
```

### 2. 写代码时接分类日志

```bash
python scripts/logkit.py init --lang python --dest ./src/logkit
```

```python
from logkit import setup, get_logger, trace
setup(level="INFO")
log = get_logger("payment")
with trace():
    log.info("退款成功", order_id="A1", amount=99.5)
```

### 3. 提交前扫密钥

```bash
python scripts/preflight.py
```

### 4. 提交代码时

```bash
python scripts/bug_ledger.py add --title "空数组越界" --priority P1
python scripts/release_note.py tag --version 1.0.0 --summary "首个版本"
```

### 5. 自动化打包测试发包（一条龙）

```bash
# ① 打包（生成 APK + md5）
./scripts/build_apk.sh --dir ./android --module :app --build-type release --arch arm64-v8a

# ② 模拟器冒烟测试（安装/启动/截图/抓崩溃）
./scripts/vm_test.sh app-release.apk com.example.app ./test_out

# ③ 双端发布（GitHub + Gitee Release/附件/update.json）
export GITHUB_USER=your-name GITHUB_TOKEN=ghp_xxx GITHUB_REPO=my-app
export GITEE_USER=your-name GITEE_TOKEN=xxx GITEE_REPO=my-app
python scripts/release.py --apk app-release.apk --version v1.0.0 \
    --name "我的应用 v1.0.0" --desc "发布说明" --update-json update.json \
    --platform github --platform gitee

# ④ 带 APK 附件发邮件（交付铁律）
export SMTP_SENDER=you@qq.com SMTP_AUTH=授权码 SMTP_RECEIVER=you@qq.com
python scripts/send_mail.py app-release.apk "交付 v1.0.0" body.txt
```

### 6. 日报 / 周报 / 项目总结（好记性不如烂笔头）

```bash
# 日报（默认今天）
python scripts/report.py daily --project "风火轮" --body "完成发布链路" --body "修复 P1"

# 周报（默认本周）
python scripts/report.py weekly --project "风火轮" --body "本周完成双端发布"

# 项目总结（项目/大版本收尾时）
python scripts/report.py summary --project "风火轮 v3.0.77" --body "核心成果"

# 查看历史报告
python scripts/report.py list
```

脚本自动汇总 `.lunyu/` 里的缺陷台账、版本存档、CHANGELOG，生成 Markdown 存到 `.lunyu/reports/`。

### 7. 已安装用户自更新 / 升级

**zip 安装包解压安装的用户（目录里没有 `.git`）同样可以一键升级**：

```bash
python scripts/self_update.py            # 检查并升级
python scripts/self_update.py --check    # 只看有没有新版，不改文件
python scripts/self_update.py --yes      # 非交互直接升级（适合脚本/CI）
bash scripts/self_update.sh              # bash 用户入口（有 Python 时自动委托 .py）
```

- 对比本地与远端版本号，有新版才下载覆盖
- 保留 `.lunyu/` 用户数据（缺陷台账、报告都在里面）
- 清理远端已删除的旧文件（`--no-prune` 可关闭）
- 多源回退（GitHub raw / CDN / API），可用 `LUNYU_MIRROR` 指向镜像站
- 远端不比本地新就不动，**不会降级**

## 目录结构

```
lunyu/
├── SKILL.md                        # 技能入口（12步流水线 + 十二则心法）
├── LICENSE                         # MIT
├── README.md                       # 本文件
├── CHANGELOG.md                    # 版本历史
├── CONTRIBUTING.md                 # 贡献指南
├── references/                     # 详细参考文档（按需加载）
│   ├── git-release.md              # 分支模型/Conventional Commits/SemVer/回滚
│   ├── bug-triage.md               # P0-P3分级/状态流转/根因归类
│   ├── review-checklist.md         # 九维度CR清单（含安全/性能/工艺）+ 意见写法
│   ├── deliverable-templates.md    # 17个交付物骨架模板
│   ├── logging-observability.md    # 分类日志规范 + 可观测性
│   ├── quality-gates.md            # 质量门禁金字塔 + 事故复盘
│   ├── code-craft.md               # 代码工艺：语言最佳实践/代码异味/重构手法/安全与性能反模式
│   ├── receiving-review.md         # 收到CR意见：先验证再回应，禁止表演性同意
│   └── parallel-performance.md     # 并行协作隔离 + 性能先测量后优化
└── scripts/                       # 可执行脚本（纯标准库，零依赖）
    ├── flow.py                     # 判通道：按改动规模+敏感路径
    ├── logkit.py                   # 生成分类日志系统到目标项目
    ├── preflight.py                # 提交前扫密钥/大文件/调试残留
    ├── bug_ledger.py               # 缺陷台账 P0-P3 + 门禁校验
    ├── release_note.py                # 版本存档 + CHANGELOG + tag/回滚
    ├── report.py                        # 日报/周报/项目总结自动生成
    ├── scheduler.py                # 注册「每天自动生成日报」定时任务（schtasks/cron）
    ├── daily_report.sh             # 定时任务入口：生成今日日报
    ├── github-publish.sh           # 一键建 GitHub 仓库并推送（PAT）
    ├── build_apk.sh               # 自动化 Gradle 打包 APK + 输出 md5
    ├── vm_test.sh                   # Android 模拟器自动化冒烟测试
    ├── send_mail.py                   # 带附件邮件发送（SMTP，凭据走环境变量）
    ├── release.py                    # 双端发布 GitHub+Gitee Release/附件/update.json
    ├── lessons.py                      # 经验库（自学习：踩坑沉淀+检索复用）
    ├── patrol.py                       # 主动巡检（自驱力：不等指令自己体检）
    ├── self_update.py                  # 自更新（跨平台，zip 安装也能升）
    ├── self_update.sh                  # 自更新入口（委托 .py / bash 兜底）
    ├── pack.py / pack_check.py         # 合规打包 + 清单双向校验
    ├── check_version.py / bump.py      # 版本四处一致性校验 / 一次改齐
    ├── env_check.py                    # 环境锁：snapshot/verify 校验工具链漂移
    ├── impact.py                       # 影响面分析：改存量代码前看谁在用它
    ├── handover.py                     # 交接文档 HANDOVER.md（跨会话/多AI交接）
    ├── codecraft.py                    # 代码工艺体检：重复块/长函数/嵌套/死代码
    ├── evolve.py                       # 智能自进化：经验回流成技能规则
    ├── verify.py                       # 完成前验证：跑测试出证据，未验证不许交付
    ├── plan.py                         # 拆成带验收点的小任务 + 检查点
    ├── locate.py                       # 陌生代码库定位：实现/入口/路由/配置
    ├── worktree.py                     # 隔离工作区（多AI并行互不污染）
    └── adr.py                          # ADR 架构决策记录
└── tests/                         # 单元测试（unittest 零依赖，444 个用例）
    ├── run_tests.py               # 测试运行入口
    ├── test_flow.py               # flow.py 通道判定
    ├── test_logkit.py             # logkit.py 模板生成
    ├── test_preflight.py          # 密钥/大文件/调试/.gitignore 扫描
    ├── test_bug_ledger.py         # 缺陷台账 CRUD + 门禁
    ├── test_release_note.py       # 版本存档 + CHANGELOG
    ├── test_report.py             # 日报/周报/总结生成
    ├── test_scheduler.py          # 定时任务注册
    ├── test_send_mail.py          # SMTP 邮件
    ├── test_release.py            # 双端发布
    ├── test_shell_scripts.py      # shell 脚本完整性
    ├── test_env_check.py          # 环境锁漂移判定
    ├── test_impact.py             # 影响面分析分桶
    ├── test_handover.py           # 交接文档生成与读取
    ├── test_codecraft.py          # 代码工艺四项检查
    ├── test_verify.py             # 完成前验证与证据留存
    ├── test_plan.py               # 任务拆解与验收点门禁
    ├── test_locate.py             # 代码定位四种模式
    └── test_worktree.py           # 隔离工作区增删查
```

## 脚本一览

| 脚本 | 作用 | 退出码 |
|---|---|---|
| `flow.py` | 判通道：快速 / 标准 / 完整 | 0=无改动 |
| `logkit.py` | 生成分类日志系统 | 0=成功 |
| `preflight.py` | 扫密钥/大文件/调试残留/.gitignore | 0=通过 / 1=阻断 / 2=警告 |
| `bug_ledger.py` | 缺陷台账 add/list/show/update/stats/export | `stats` 有未关闭 P0/P1 返回 1 |
| `release_note.py` | 版本存档 tag/list/show/rollback | 有未关闭 P0/P1 返回 2 |
| `github-publish.sh` | 一键建 GitHub 仓库并推送（需 PAT） | 0=成功 |
| `build_apk.sh` | 自动化 Gradle 打包 APK + 输出 md5 | 0=成功 |
| `vm_test.sh` | Android 模拟器安装/启动/截图/抓崩溃 | 0=通过 / 1=失败 |
| `send_mail.py` | 带附件邮件发送（SMTP） | 0=成功 / 1=失败 |
| `release.py` | 双端发布 GitHub+Gitee Release/附件/update.json | 0=成功 / 1=失败 |
| `report.py` | 项目总结/日报/周报自动生成 | 0=成功 |
| `scheduler.py` | 注册/卸载/查看每日自动日报定时任务（schtasks/cron） | 0=成功 / 1=失败 |
| `daily_report.sh` | 定时任务入口：生成今日日报 | 0=成功 |
| `lessons.py` | 经验库：踩坑沉淀 + 检索复用（命中加权，越用越准） | 0=成功 |
| `patrol.py` | 主动巡检：不等指令自己体检项目，输出待办清单 | 0=无阻断 / 1=有阻断 |
| `self_update.py` | 自更新技能包（跨平台，zip 安装也能升，保留 .lunyu，清理旧文件） | 0=已最新/成功 / 1=失败 / 2=有新版本(--check) |
| `self_update.sh` | 自更新入口（有 Python 时委托 .py，无 Python 走 bash 兜底） | 0=已最新/成功 / 1=失败 |
| `pack.py` | 合规打包 zip（排除仓库开发目录），打包前跑清单+版本校验 | 0=成功 / 1=校验未过 |
| `pack_check.py` | 打包清单双向校验：正文引用的必须进包、包内文件必须有归属 | 0=通过 / 1=有阻断 |
| `check_version.py` | 版本四处一致性（SKILL.md/metadata/CHANGELOG/README 徽章） | 0=一致 / 1=不一致 |
| `bump.py` | 一次改齐四处版本号，据提交信息推下一版 | 0=成功 |
| `env_check.py` | 环境锁：snapshot 记基线 / verify 查漂移（换机器先跑） | verify: 0=一致 / 1=漂移或无基线 |
| `impact.py` | 影响面分析：查符号被谁调用、有无测试覆盖、配置与跨仓库引用 | 0=成功 / 1=目标不存在 |
| `handover.py` | 生成 HANDOVER.md（状态/已完成/下一步/未决决策/已知坑），`--read` 供新会话读 | 0=成功 / 1=读取时无文档 |
| `codecraft.py` | 代码工艺体检：重复块/过长函数/嵌套过深/死代码/坏习惯 | 0=成功，`--strict` 有问题返回 1 |
| `verify.py` | **完成前验证**：自动探测并实际跑测试/preflight/构建，出证据，未验证不许交付 | 0=通过 / 1=有失败或未验证 |
| `plan.py` | 拆成带验收点的小任务，逐步打勾 | `gate` 有未完成返回 1 |
| `locate.py` | 陌生代码库定位：找实现/入口点/路由/配置项 | 0=找到或明确没找到 / 1=目录不存在 |
| `worktree.py` | 隔离工作区（git worktree 封装），多需求多 AI 并行 | 0=成功 / 1=失败 |

## 自学习与自驱力

流水线负责"把事做对"，这两项负责"下次做得更快"和"没人催也动起来"。

### 自学习：经验库（告诸往而知来者）

```bash
# 首次使用：导入内置种子经验（12 条通用工程教训），别从空库起步
python scripts/lessons.py seed

# 沉淀
python scripts/lessons.py add --scene "车机静态广播不分发"   --solution "动态注册兜底" --tags "android,车机,广播" --kind 踩坑

# 复用（接到新需求先查）
python scripts/lessons.py search "车机广播"
```

**命中即加权**：每次检索命中会累加 `hits`，用得越多的经验自动排越靠前，库会自己"学"出什么最常用。

### 自驱力：主动巡检（君子求诸己）

```bash
python scripts/patrol.py          # 不等指令，自己体检项目
python scripts/patrol.py --json   # 可挂 CI
```

检查未关闭 P0/P1（阻断）、缺陷超期、日报缺失、CHANGELOG 落后、经验久未沉淀、未提交改动。
退出码 `0=无阻断 / 1=有阻断`。

## 单元测试

所有 Python 脚本都有 `unittest` 单元测试（零第三方依赖），运行：

```bash
cd lunyu
python tests/run_tests.py          # 或
python -m unittest discover -s tests -v
```

覆盖：通道判定、日志模板生成、密钥扫描、缺陷台账、版本存档、日报/周报/总结、
定时任务、SMTP 邮件、双端发布、shell 脚本完整性，共 444 个用例。

> 🔒 **安全提示**：所有脚本的凭据（GitHub PAT、Gitee token、SMTP 授权码）一律通过**环境变量**或**命令行参数**传入，脚本内零硬编码。请通过环境变量 `GITHUB_USER` / `GITHUB_TOKEN` / `GITHUB_REPO` / `GITEE_USER` / `GITEE_TOKEN` / `GITEE_REPO` / `SMTP_SENDER` / `SMTP_AUTH` / `SMTP_RECEIVER` 配置你的账号信息，不要把真实账号硬编码进脚本。

## 三通道机制

**不是所有需求都走 12 步。** `flow.py` 按改动规模自动分通道：

| 通道 | 触发条件 | 走几步 |
|---|---|---|
| **快速** | ≤2 文件且 ≤50 行；或纯文档/纯测试 | 5 步 |
| **标准** | 中等改动 | 8 步 |
| **完整** | ≥8 文件 / ≥300 行 / **触及敏感路径** | 全 12 步 |

敏感路径强制完整通道：`auth/ login/ oauth/ token/ payment/ billing/ migration/ schema/ .env/ config/ Dockerfile/ CI配置/ 依赖清单/ crypto/ *.sql`

## 与外部工具的关系

论语是**流程编排层**，不替代技术实现；也不依赖任何外部技能——包内资产自足，单独安装即可跑完整流水线，离线可用。

| 外部工具 | 关系 |
|---|---|
| CodeQL / Semgrep 等扫描器 | 互补：lunyu 做提交前扫密钥与门禁编排，深度审计交给用户环境里的专业扫描器 |
| pytest / JUnit 等测试框架 | 互补：lunyu 定测试金字塔与覆盖率口径，执行交给框架 |
| 设计工具链 | 不同领域，不在 lunyu 流程范畴 |

## 贡献

欢迎提交 Issue 和 PR。详细指南见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可

[MIT](LICENSE) © 2026

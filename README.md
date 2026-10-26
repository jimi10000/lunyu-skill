# 论语 · 企业级研发流水线

> 以《论语》为工程价值观内核的企业级研发流水线。需求评审 → 方案设计 → 开源预研 → 编码 → 自测 → CR → 版本归档 → 风险评估 → 复盘。内置分类日志系统、密钥扫描、缺陷工单台账、发布回滚。

> 📌 **第一次接触本项目？** 先看 [`项目介绍.md`](项目介绍.md) —— 一页讲清「这是什么、解决什么、怎么用」。本文件是面向开发者/贡献者的完整说明。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](CHANGELOG.md)
[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-Compatible-green)](https://skills.sh)

---

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
│   ├── review-checklist.md         # 七维度CR清单 + 意见写法
│   ├── deliverable-templates.md    # 10个交付物骨架模板
│   ├── logging-observability.md    # 分类日志规范 + 可观测性
│   └── quality-gates.md            # 质量门禁金字塔 + 事故复盘
└── scripts/                       # 可执行脚本（纯标准库，零依赖）
    ├── flow.py                     # 判通道：按改动规模+敏感路径
    ├── logkit.py                   # 生成分类日志系统到目标项目
    ├── preflight.py                # 提交前扫密钥/大文件/调试残留
    ├── bug_ledger.py               # 缺陷台账 P0-P3 + 门禁校验
    ├── release_note.py                # 版本存档 + CHANGELOG + tag/回滚
    ├── github-publish.sh           # 一键建 GitHub 仓库并推送（PAT）
    ├── build_apk.sh               # 自动化 Gradle 打包 APK + 输出 md5
    ├── vm_test.sh                   # Android 模拟器自动化冒烟测试
    ├── send_mail.py                   # 带附件邮件发送（SMTP，凭据走环境变量）
    └── release.py                    # 双端发布 GitHub+Gitee Release/附件/update.json
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

> 🔒 **安全提示**：所有脚本的凭据（GitHub PAT、Gitee token、SMTP 授权码）一律通过**环境变量**或**命令行参数**传入，脚本内零硬编码。请通过环境变量 `GITHUB_USER` / `GITHUB_TOKEN` / `GITHUB_REPO` / `GITEE_USER` / `GITEE_TOKEN` / `GITEE_REPO` / `SMTP_SENDER` / `SMTP_AUTH` / `SMTP_RECEIVER` 配置你的账号信息，不要把真实账号硬编码进脚本。

## 三通道机制

**不是所有需求都走 12 步。** `flow.py` 按改动规模自动分通道：

| 通道 | 触发条件 | 走几步 |
|---|---|---|
| **快速** | ≤2 文件且 ≤50 行；或纯文档/纯测试 | 5 步 |
| **标准** | 中等改动 | 8 步 |
| **完整** | ≥8 文件 / ≥300 行 / **触及敏感路径** | 全 12 步 |

敏感路径强制完整通道：`auth/ login/ oauth/ token/ payment/ billing/ migration/ schema/ .env/ config/ Dockerfile/ CI配置/ 依赖清单/ crypto/ *.sql`

## 与现有技能的关系

论语是**流程编排层**，不替代技术实现技能：

| 现有技能 | 关系 |
|---|---|
| `fullstack-dev` | 互补：lunyu 管流程，fullstack 管技术细节 |
| `code-review-checklist-hckp` | 已被覆盖：lunyu 有更全的 7 维度 CR |
| `secure-audit-suite` | 互补：lunyu 做提交前扫密钥，secure-audit 做深度审计 |
| `frontend-dev` | 互补：不同领域 |

## 贡献

欢迎提交 Issue 和 PR。详细指南见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可

[MIT](LICENSE) © 2026

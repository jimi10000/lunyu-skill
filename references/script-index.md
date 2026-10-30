# 脚本完整索引

> 自 SKILL.md 下沉：31 项脚本全表、patrol 巡检项、单元测试入口。按需加载。

全部位于 `scripts/`，纯标准库无外部依赖。

| 脚本 | 作用 | 何时用 |
|---|---|---|
| `flow.py` | 判通道：按改动规模+敏感路径决定走几步 | **接到需求第一步** |
| `logkit.py` | 生成分类日志系统到目标项目 | Step 5 编码时 |
| `preflight.py` | 提交前扫密钥/大文件/调试残留/依赖风险（出 SBOM），可装 pre-commit 钩子 | Step 6 提交前 |
| `adr.py` | ADR 架构决策记录（new/list/show/supersede/link） | Step 3 有取舍时 |
| `bug_ledger.py` | 缺陷台账 P0-P3，关闭强制填根因+回归用例，`stats` 门禁 | Step 6/7/9 |
| `release_note.py` | 版本存档 + CHANGELOG + tag/回滚，产物 sha256 入库 | Step 8 |
| `report.py` | 日报/周报/项目总结自动生成，周报自动聚合日报 | Step 12 周期性复盘 |
| `scheduler.py` | 注册「每天自动生成日报」定时任务（schtasks/cron） | Step 12 配置自动日报 |
| `daily_report.sh` | 定时任务入口：生成今日日报 | 定时任务触发时 |
| `release.py` | 双端发布 GitHub+Gitee Release/附件/update.json | 发布 |
| `send_mail.py` | 带附件邮件发送（SMTP） | 交付/通知 |
| `build_apk.sh` | Gradle 打包 APK + md5 | 发版前 |
| `vm_test.sh` | Android 模拟器冒烟测试 | 发版前 |
| `github-publish.sh` | 一键建 GitHub 仓库并推送（PAT） | 开源新项目 |
| `lessons.py` | 经验库：沉淀/检索（命中加权）、缺陷转经验、导入导出、全局库、过期复核 | Step 1 检索 / Step 10 沉淀 |
| `patrol.py` | 主动巡检：11 项检查（含 3 项闭环检查 + 文档同步 + 交接过期），不等指令自己体检输出待办 | 日常 / CI 门禁 / 定时任务 |
| `self_update.py` | 自更新技能包（跨平台，zip 安装也能升，保留 .lunyu） | 已安装用户升级 |
| `self_update.sh` | 自更新入口（有 Python 时委托 .py，无 Python 走 bash 兜底） | 已安装用户升级 |
| `pack.py` | 打包技能包 zip + 生成自更新清单 + 出 sha256（排除 .git/缓存/工作数据/仓库开发目录） | 发布技能包时 |
| `pack_check.py` | 打包清单双向校验：正文引用的必须进包 + 包内文件必须有归属 | pack.py 自动调用 |
| `check_version.py` | 版本四处一致性校验（SKILL.md 顶层/metadata/CHANGELOG/README 徽章）不一致非零 | pack.py 自动调用 / CI |
| `bump.py` | 一次改齐四处版本号，据提交信息推下一版（feat/fix/breaking），打印建议 tag | 发版前 |
| `env_check.py` | 环境锁：snapshot 生成 `.lunyu/env.lock`，verify 校验工具链版本漂移 | **换机器/换人开工前** |
| `impact.py` | 影响面分析：查符号/文件被谁调用、有无测试覆盖、配置与路由字符串引用、跨仓库引用的下游 | **改存量代码前** |
| `handover.py` | 交接文档：生成/更新 `HANDOVER.md`（当前状态/已完成/下一步/未决决策/已知坑），`--read` 供新会话开工读 | **每个会话开工与收尾** |
| `codecraft.py` | 代码工艺机器查：重复代码块/过长函数/嵌套过深/未引用导出（专治 AI 造轮子和堆死代码） | Step 5 编码后 / Step 7 CR |
| `evolve.py` | 智能自进化：从经验库提取 `skill:true`/高权重条目，生成「应上升为技能规则」提案（`.lunyu/evolution-proposals.md`） | 复盘 / 被纠正后 |
| `verify.py` | **完成前验证**：自动探测并实际执行测试命令 + preflight + 构建，结果存 `.lunyu/verify.json` 当证据；有能力没跑过判「未验证」并阻断；`record` 手工登记（要带证据）、`require` 交付前校验某项 | **声称完成前必跑** |
| `plan.py` | 拆成带验收点的小任务（`new`/`list`/`start`/`done`/`show`/`reset`/`set-acceptance`/`clear`/`gate`），验收点必填，`gate` 全部完成才放行 | Step 3 拆任务 / 执行中 |
| `locate.py` | 陌生代码库定位：`--keyword`（找实现在哪）/ `--entry`（入口点）/ `--route`（路由定义）/ `--config`（配置项） | Step 5 接手不熟悉代码时 |
| `worktree.py` | 隔离工作区（git worktree 封装）：`create` / `list` / `path` / `remove` / `prune`，多需求与多 AI 并行互不污染 | 并行推进前 |

---

```bash
python scripts/patrol.py                    # 全量巡检
python scripts/patrol.py --json             # 机器可读，适合挂 CI
python scripts/patrol.py --due-days 7       # 缺陷超期阈值
```

检查项（按阻断程度排序，阻断项永远排最前）：

1. **[阻断]** 未关闭的 P0/P1 缺陷 —— 按门禁不该带着继续开发
2. **[高]** 缺陷超期（默认挂 14 天以上）—— 容易被忘掉的坑
3. **[中]** 今日/本周日报周报还没写 —— 「好记性不如烂笔头」的自驱检查
4. **[中]** 有版本记录但 CHANGELOG 没跟上 —— 版本历史断档
5. **[低]** 经验库长期没沉淀 —— 等于准备在同一个坑再摔一次
6. **[低]** 工作区有未提交改动
7. **[中]** CR 意见提了没闭环 —— 「法语之言，改之为贵」，提了不改等于没提
8. **[中]** 复盘纪要里的待办没打勾 —— 复盘写了，改进项没人跟
9. **[低]** 昨日「明日计划」没兑现 —— 日报变废纸的主因，写了不算、做了才算
10. **[中]** 文档落后于代码 —— 源码改了很久 README/docs 没动，新人按文档做全是错的
11. **[低]** 交接文档过期 —— `HANDOVER.md` 很久没更新，换 AI / 新会话接手读到旧状态

第 7-9 项查的是**闭环**：有产出但没下文，比没产出更隐蔽。第 10-11 项查的是**上下文延续**：人和 AI 都会断片，文档是唯一能跨会话留下的东西。

退出码 `0=无阻断 / 1=有阻断`，可直接当 CI 门禁或挂定时任务。单项检查炸了不影响其他项跑完——**自驱力不能自己先趴下**。

---


## 单元测试

仓库 `tests/` 下为全部 Python 脚本提供 `unittest` 测试（零依赖，444 个用例）。**该目录不进技能包**，是仓库开发者的回归保障；已安装技能不含测试目录。

修改脚本后请先跑测试再提交，防止回归。

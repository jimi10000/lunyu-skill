# 脚本完整索引

> 自 SKILL.md 下沉：20 项脚本全表、patrol 巡检项、单元测试入口。按需加载。

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
| `patrol.py` | 主动巡检：9 项检查（含 3 项闭环检查），不等指令自己体检输出待办 | 日常 / CI 门禁 / 定时任务 |
| `self_update.py` | 自更新技能包（跨平台，zip 安装也能升，保留 .lunyu） | 已安装用户升级 |
| `self_update.sh` | 自更新入口（有 Python 时委托 .py，无 Python 走 bash 兜底） | 已安装用户升级 |
| `pack.py` | 打包技能包 zip + 生成自更新清单 + 出 sha256（排除 .git/缓存/工作数据） | 发布技能包时 |
| `evolve.py` | 智能自进化：从经验库提取 `skill:true`/高权重条目，生成「应上升为技能规则」提案（`.lunyu/evolution-proposals.md`） | 复盘 / 被纠正后 |

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

后三项查的是**闭环**：有产出但没下文，比没产出更隐蔽。

退出码 `0=无阻断 / 1=有阻断`，可直接当 CI 门禁或挂定时任务。单项检查炸了不影响其他项跑完——**自驱力不能自己先趴下**。

---


## 单元测试

`tests/` 下为全部 Python 脚本提供 `unittest` 测试（零依赖，294 个用例）：

```bash
python tests/run_tests.py          # 或
python -m unittest discover -s tests -v
```

修改脚本后请先跑测试再提交，防止回归。

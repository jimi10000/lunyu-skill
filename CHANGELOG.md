# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.1.4] - 2026-10-26

### Fixed

- **`SKILL.md` frontmatter**：补全技能市场解析必需的顶层字段 `version`（原先只写在 `metadata` 子层，解析器读不到）和 `display_name_en`（原先缺失），解决上传技能市场时「解析失败：缺少 Skill 版本号 / 缺少英文展示名」的问题
- `display_name_en` 值加双引号，避免 `R&D` 中的 `&` 被 YAML 当成锚点符号误解析

## [1.1.3] - 2026-10-26

### Added

- **单元测试**：新增 `tests/` 目录，为全部 Python 脚本补上 `unittest` 测试（104 个用例，零第三方依赖），覆盖通道判定、日志模板生成、密钥扫描、缺陷台账、版本存档、日报/周报/总结生成、定时任务、SMTP 邮件、双端发布，以及 shell 脚本完整性检查
- **测试运行入口**：`tests/run_tests.py`，一行命令跑全部测试
- **交付物模板骨架**：新增 `templates/` 目录，7 个交付物模板（需求确认单/技术方案/调研报告/自测结果/风险清单/复盘纪要等），带 HTML 注释占位符，可直接复制使用
- **定时日报**：`scheduler.py` 注册「每天自动生成日报」定时任务（Windows schtasks / Linux cron），`daily_report.sh` 作为任务入口
- **上架指引**：`上架指引.md` 提供 WorkBuddy 技能市场上架操作说明（open.workbuddy.cn）

### Fixed

- **`report.py`**：`summarize_releases` 未把 release 记录的 `created_at` 映射为日期字段，导致「今日/本周发版」统计永远为空；已修复并补充测试

## [1.1.2] - 2026-10-26

### Fixed

- **`release.py`**：修复 GitHub 资产删除 URL 错误（`releases/{rid}/assets/{id}` 会 404，应为 `releases/assets/{id}`），幂等重发现在能正确删旧传新

## [1.1.1] - 2026-10-26

### Fixed

- **`build_apk.sh`**：修复模块路径带冒号导致 APK 定位失败；`--module` 现在接收目录名（`app`），自动转 gradle 坐标（`:app`）；md5 兼容 macOS（`md5 -q`）
- **`vm_test.sh`**：修复 `ANDROID_HOME` 默认值带单引号导致路径错误；可执行文件按平台适配（Windows `.exe` / Unix 无后缀）
- **`bug_ledger.py`**：缺陷关闭时记录 `closed_at`，重新打开时清除，日报/周报统计更准确
- **`report.py`**：读取 `closed_at` 优先于 `updated_at`
- **`release_note.py`**：修复 `related_version` 为空时把所有关闭缺陷误算进版本
- **`flow.py`**：修复无 HEAD 仓库（刚 init 未提交）时 `git diff HEAD` 报错，自动回退到 `git diff`
- **`github-publish.sh`**：用 `trap cleanup EXIT` 确保推送失败时也清除 remote URL 里的 token
- **`send_mail.py`**：非 SSL 模式默认端口改 587，补 STARTTLS 前后 EHLO，检查收件人拒绝
- **`self_update.sh`**：版本比较去掉 `v` 前缀，避免 `v1.1.0` vs `1.1.0` 误判；本地比远端新时不降级

## [1.1.0] - 2026-10-26

### Added

- **项目总结/日报/周报自动生成**：`report.py` 汇总 `.lunyu/` 缺陷台账、版本存档、CHANGELOG，一键生成 Markdown 报告并落盘 `.lunyu/reports/`
- **技能包一键自更新**：`self_update.sh` 对比本地与 GitHub 远端版本号，拉最新版覆盖，保留 `.lunyu/` 数据文件
- **Step 12 周期性复盘**：把「好记性不如烂笔头」制度化，日报/周报/项目总结的触发时机与手写要求
- **触发词扩展**：提到「日报/周报/项目总结/工作总结/复盘」时自动触发 lunyu

## [1.0.0] - 2026-10-26

### Added

- **十二则心法**：将《论语》十二条准则映射到研发流水线的 12 个节点，作为判断依据而非装饰
- **三通道机制**：`flow.py` 按改动规模 + 敏感路径自动判定快速/标准/完整通道，避免小改动套重流程
- **分类日志系统**：`logkit.py` 生成 Python/TS 日志模块，按问题域分类 + trace_id 全链路 + 严格分级 + 结构化字段 + 耗时埋点
- **提交前密钥扫描**：`preflight.py` 检测硬编码密钥、调试残留、大文件、.gitignore 缺项，退出码可直接接 git hook / CI
- **缺陷工单台账**：`bug_ledger.py` 管理 P0-P3 缺陷，状态流转 `新建 → 修复中 → 自测通过 → CR验证 → 关闭`，`stats` 带门禁校验
- **版本存档**：`release_note.py` 生成版本记录、CHANGELOG 条目、tag/合并/回滚命令，支持 SemVer 递增
- **七维度 CR 清单**：正确性、边界、可读性、耦合、健壮性、规范、安全，每条意见给可执行改法
- **质量门禁金字塔**：编码 → 提交前 → 单测 → CI → CR → 线上，各层成本与手段明确
- **事故复盘模板**：无责模式 + 五个为什么 + MTTD/MTTR 指标 + 改进项带负责人和截止日期
- **可观测性三支柱**：日志、指标、追踪，上线前必须回答的三个问题
- **发布策略**：Feature Flag / 灰度 / 蓝绿，数据库变更的两次发布法
- **6 份参考文档**：git-release、bug-triage、review-checklist、deliverable-templates、logging-observability、quality-gates

### Scripts

- `scripts/flow.py` — 判通道（快速/标准/完整）
- `scripts/logkit.py` — 生成分类日志系统（Python/TS/Both）
- `scripts/preflight.py` — 提交前扫描（密钥/调试残留/大文件/.gitignore）
- `scripts/bug_ledger.py` — 缺陷台账（add/list/show/update/stats/export）
- `scripts/release_note.py` — 版本存档（tag/list/show/rollback）
- `scripts/github-publish.sh` — 用 PAT 一键建 GitHub 仓库并推送（REST API，token 走参数不落盘，账号信息走环境变量）
- `scripts/build_apk.sh` — 自动化 Gradle 打包 APK，输出 APK 路径 + md5
- `scripts/vm_test.sh` — Android 模拟器自动化冒烟测试：启动/安装/拉起/截图/UI dump/抓崩溃，输出测试报告
- `scripts/send_mail.py` — 带附件邮件发送（SMTP 465，凭据全走环境变量）
- `scripts/release.py` — 双端发布 GitHub+Gitee：建 Release/传附件/更新 update.json，全幂等

### Notes

- 所有脚本零外部依赖，纯 Python 标准库
- 数据落盘统一在项目根 `.lunyu/` 目录
- 技能兼容 WorkBuddy Agent Skill 规范

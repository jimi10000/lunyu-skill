# CHANGELOG

格式遵循 [Keep a Changelog](https://keepachangelog.com/), 版本号遵循 [SemVer](https://semver.org/)。

## [1.2.10] - 2026-10-27

### Changed
- **包结构拍平为两级**（平台兼容整改）：平台包仅含 `lunyu/SKILL.md` + `references/scripts/templates` 三个可选子目录，`docs/`、`tests/` 与根级元数据（README/CHANGELOG/CONTRIBUTING/LICENSE）不进技能包，`pack.py` 打包时映射排除
- **脚本体检**：`--help` 全部返回 0（修复 `send_mail.py` 将 `--help` 当位置参数返回 1 的问题）；失败路径必须非零退出
- **打包清单双向校验**：新增 `scripts/pack_check.py` 接入打包流程——正向校验正文引用的文件全部进包，反向校验包内文件都有归属（被正文引用 / script-index 兜底 / 清单 / 种子数据），缺失即中断打包
- **版本一致性工具**：新增 `scripts/check_version.py`（校验 SKILL.md 顶层 version = metadata.version = README 徽章 = CHANGELOG 顶部，不一致返回非零）与 `scripts/bump.py`（一次改齐四处版本号并打印建议 tag）
- 版本号由 `bump.py` 统一提升 1.2.9 → 1.2.10（chore → patch）

## [1.2.9] - 2026-10-27

### Added
- **TDD 红绿重构**（对标 Matt Pocock / Superpowers）：Step 5 / Step 6 强制「先写失败测试→实现→重构」小步循环，测试先确认红再写实现
- **系统化调试四步法**（对标 Superpowers）：复现→假设根因→最小测试证伪→只修根因；症状≠根因，禁止掩盖式补丁
- **源码优先 source-driven**（对标 skills-hub）：动手前先读真实源码、引用给出具体文件路径，不凭空发明 API
- 反模式 +3（凭印象写代码 / 写完再补测试从没见过红 / 遇 bug 上来就试改）

## [1.2.8] - 2026-10-27

### Added
- **横切诸则再扩 12 条**（通读《论语》二次筛选，已采条目 23 → 35）：
  - 敏于事而慎于言（多做少说交付优先）
  - 慎终追远（决策变更可追溯 / ADR）
  - 不愤不启，不悱不发（启发式协助不包办）
  - 逝者如斯夫，不舍昼夜（时效优先不拖延）
  - 岁寒，然后知松柏之后凋（恶劣条件自测）
  - 君子周而不比（协作开放不搞小圈子）
  - 德不孤，必有邻（质量自传播）
  - 道不同不相为谋（选型看价值观/技术栈契合）
  - 信近于义，言可复也（承诺可实现）
  - 言忠信，行笃敬（言行一致）
  - 君子欲讷于言而敏于行（少承诺多交付）
  - 三军可夺帅，匹夫不可夺志（架构原则坚定）
- 反模式 +7 条对应上述（多表态少交付 / 决策不留痕 / 替人包办 / 拖延 / 只测正常路径 / 排期吹牛 / 架构原则动摇）。

## [1.2.7] - 2026-10-27

### Added
- **横切诸则扩展**：通读《论语》对照现有设计，新增 7 条工程化原则入「横切诸则」（原七则实为 8 条，现正名）：
  - 欲速则不达（反对赶工省略流程）
  - 工欲善其事，必先利其器（开工先备环境/依赖/工具链）
  - 多闻阙疑，慎言其余（调研存疑留空、不凭一知半解下断言）
  - 质胜文则野，文胜质则史（功能与可读性平衡）
  - 君子不器（角色弹性 + 守住边界）
  - 小不忍则乱大谋（决策克制、别为小问题动架构）
  - 学而时习之（沉淀后要周期性复用验证）
- 反模式新增 6 条与上述对应（赶工跳流程 / 凭一知半解下断言 / 功能与可读性失衡 / 遇小问题冲动改架构 / 沉淀不复用验证）。

## [1.2.6] - 2026-10-27

### Added
- **输出风格纪律「辞达而已矣」**：回答直接给结果/结论/动作，不铺垫、不客套、不重复；锚定到横切七则与反模式（绕圈子半天不给结论列为反模式）。

## [1.2.5] - 2026-10-27

### Added

- **智能自进化（元进化闭环）**：lunyu 从「只帮项目攒经验」升级为「让技能自身越长越聪明」——运行 / 踩坑 / 用户纠正得来的东西回流成技能规则。新增 `scripts/evolve.py`（从经验库提取 `skill:true` / 高权重条目，生成「应上升为技能规则」提案 `.lunyu/evolution-proposals.md`）；`SKILL.md` 新增「智能自进化」小节与反模式（踩坑不复盘回流=重复犯错），`references/step-details.md` 新增专节，`references/script-index.md` 登记 evolve（19→20 项）

## [1.2.4] - 2026-10-27

### Changed

- **「知之为知之」总则补强为「主动联网搜索」**：从「不许编造」升级为「遇到不会 / 不确定的问题先联网检索权威资料（官方文档 / 社区 / 论文 / 源码），基于查证结果回答；搜不到才如实声明『未验证』，绝不凭印象编造」。落到 `SKILL.md` 横切七则、总则专节与反模式（新增「不搜索就瞎编 / 不懂装懂」红线）

## [1.2.3] - 2026-10-27

### Added

- **多 AI / 多人协作一致性纪律**：补齐「工程标识锁死」未覆盖的协作盲区——不同 AI agent 并行开发时禁止（1）各自基于旧源码开工「版本基线漂移」、（2）同时改同一文件互相覆盖、（3）各存各的目录。新增「唯一事实源（git 仓库）/ 开工即同步基线 / 责任区 + 独立分支 / 落盘唯一」四条纪律，落到 `templates/02-需求确认单.md`「协作约定（含多 AI 并行）」、`references/step-details.md` 专节、`SKILL.md` 反模式

## [1.2.2] - 2026-10-27

### Added

- **工程根目录绝对路径锁死**：在「工程标识锁死」基础上补齐落盘路径维度——需求确认单新增「工程根目录绝对路径（含盘符）」字段，**一次定死、全生命周期不变**；流水线重跑 / 换机器 / 定时任务触发都落到同一绝对路径，**禁止跨盘符、跨目录漂移（C 盘 D 盘乱跳属红线）**。落到 `templates/02-需求确认单.md`、`templates/03-技术方案文档.md`、`references/step-details.md` 对齐维度与运行纪律，以及 `SKILL.md` 反模式（新增「换盘符换根目录」红线）
- **运行纪律**：明确 lunyu 脚本运行前必须 `cd` 到项目根或显式传 `--root <绝对路径>`，禁止依赖 CWD 隐式定位（曾因计划任务 CWD=System32 导致 `.lunyu/` 写错位置）

## [1.2.1] - 2026-10-27

### Added

- **工程标识锁死纪律**：流水线新增「工程标识（包名 / 命名空间 / Application ID / GroupId-ArtifactId 等）一次定死、全生命周期不变」规则——需求确认单确认即生效，流水线重新跑一遍不会重新生成或变更工程标识；中途改名换包名视为范围大改，须走需求变更记录并评估对依赖引用 / CI / 发布产物的连锁影响。落到 `templates/01-待确认需求清单.md`、`templates/02-需求确认单.md`、`templates/03-技术方案文档.md`、`references/step-details.md` 与 `SKILL.md` 反模式

### Fixed

- **包名固化**：`scripts/pack.py` 与 `scripts/self_update.py` 的包名改从 `SKILL.md` 顶层 `name` 单一来源派生（zip 文件名、包内顶层目录、自更新下载 URL 四处一致）；`pack.py --name` 传不一致只警告不生效，`self_update.py` 不再硬编码 `lunyu-*.zip`

## [1.2.0] - 2026-10-27

### Added

- **ADR 架构决策记录 `adr.py`**：`new / list / show / supersede / link`，决策落 `.lunyu/decisions/NNNN-*.md` + 索引，方案换人有据可查
- **提交前门禁可安装**：`preflight.py install-hook`（复用 `core.hooksPath`，已存在先备份）/ `uninstall-hook`
- **依赖 SBOM**：`preflight.py scan_deps` 扫第三方依赖并落 `.lunyu/sbom.json`
- **模板补齐至 14 个**：新增 08 交付清单、09 需求变更记录、10 CR 评审意见单、11 事故报告、12 日报、13 周报、14 项目总结
- **参考文档补齐至 18 份**：新增 extreme-conditions、scope-change、anti-patterns、scale-adaptation、script-index、self-update、adr-usage、report-usage、lessons-usage 等，并让原死文档被正文引用
- **日报/周报/总结自动聚合**：`report.py`、`release_note.py` 自动聚合历史日报周报（`--no-agg` 可关）
- **产物可追溯**：`release_note.py --artifact` 算 sha256 入版本存档，回滚预案一并落盘
- **定时日报**：`scheduler.py` + `daily_report.sh`，到点自动生成并发送
- **单元测试骨架**：`tests/` 332 用例，跑前自动清 `__pycache__`
- **上架市场合规**：frontmatter 顶层 `version` 与 `display_name_en`，`&` 加引号避免 YAML 锚点

### Fixed

- **零外部技能依赖（上架审核阻断项）**：正文不再引用任何包外技能及其附属文档（原先指向的三个包外技能与两份外部参考均不在本包内，被判「资产包缺少必需资源」）——改为内置资源索引，包内资产自足，单独安装即可跑完整流水线，离线可用
- **自更新不再有数据销毁窗口**：`self_update.py` 由 rmtree→copytree 改为原子 `os.replace` 换名，中断可回滚，`.lunyu/` 台账不丢
- `self_update.sh` 版本解析改顶层优先 + `[[:space:]]`（原正则只读缩进子层，技能市场只读顶层 version）
- PAT 不再明文写 `.git/config`、不再进 argv，改环境变量 + 临时凭据文件（600）
- `report.py` / `release_note.py` 补 `sys.exit(main())`（原来失败仍返回 0，CI 门禁形同虚设）
- 关闭缺陷强制填根因 + 回归验证，否则退出码 1
- 修 6 条假测试（logkit 同义反复、shell 存在性断言、`sort -V` GNU-only 等），stale `.pyc` 导致的「假全绿」已根治

## [1.1.7] - 2026-10-26

### Added

- **种子经验库**：新增 `references/seed-lessons.json`（12 条通用工程教训：密钥硬编码、反编译 diff 假差异、车机静态 receiver 失效、跨进程 action 先搜常量池、刷包只认 sha256、`&` 在 YAML 是锚点、stale `.pyc` 假全绿、`\s` 在 BSD grep 不支持、动手前先找轮子等），配套 `lessons.py seed` 一键导入，**幂等**（同场景不会重复导入），让项目不从空库起步

## [1.1.6] - 2026-10-26

### Added

- **自学习：经验库 `lessons.py`**（告诸往而知来者）——把踩过的坑、验证过的结论沉淀下来，下次自动复用，不再重复交学费
  - 闭环：**踩坑 → 入库 → 检索命中 → 用到新需求 → 再沉淀**；已嵌进流水线（Step 1 检索、Step 10 沉淀）
  - **命中即加权**：每次 `search` 命中累加 `hits`，用得越多的经验自动排越靠前，不需要人工维护优先级
  - 检索打分：标签 > 场景 > 问题 > 结论；中文走 2-gram 分词，短语也能命中
  - 支持 `add / search / list / stats / export`，可导出 markdown 贴进复盘或周报
- **自驱力：主动巡检 `patrol.py`**（君子求诸己）——不等用户下指令，自己体检项目输出「现在该做的事」
  - 6 项检查：未关闭 P0/P1（阻断）、缺陷超期、日报周报缺失、CHANGELOG 落后、经验库久未沉淀、工作区未提交
  - 阻断项永远排最前；单项检查异常不影响其他项跑完
  - 退出码 `0=无阻断 / 1=有阻断`，可直接当 CI 门禁或挂定时任务；`--json` 机器可读

### Fixed

- **测试入口会给"假全绿"**：`__pycache__` 里的 stale `.pyc` 会让 unittest 加载到旧版测试代码，之前一批坏测试被伪装成通过、测试数也对不上（169 vs 178）。`run_tests.py` 现在跑测试前自动清理 `__pycache__`
- 清缓存后暴露并修复的 4 个测试自身缺陷：`test_scheduler.py` 缺 `import tempfile`；`run_input` 的 input 是位置参数却被当 kwargs 断言；`cmd_install` 会校验 report.py 真实存在（mock 需给真实文件）；Windows 下 `abspath` 会改写路径导致跨平台断言失败；`test_release.py` 调用 `put_update_json` 前未落盘文件

## [1.1.5] - 2026-10-26

### Added

- **`self_update.py`**：新增跨平台自更新脚本（Python 标准库，零依赖）。**用 zip 安装包解压安装的用户现在也能一键升级**——走 HTTP 下载覆盖，不依赖目录里的 `.git`，`git pull` 用不了的场景照样升
  - 支持 `--check`（只检查不改文件）/ `--yes`（非交互）/ `--force`（强制重装）/ `--no-prune`（保留旧文件）
  - 更新前后自动备份并还原 `.lunyu/` 用户数据（缺陷台账、报告都在里面）
  - 清理远端已删除的旧文件（旧 `.sh` 版因本机无 `rsync` 做不到，会残留垃圾文件）
  - **多源回退**：GitHub raw → raw CDN → GitHub API，任一通即可；支持 `LUNYU_MIRROR` 指向镜像站，缓解国内直连不稳
  - 版本比较走语义化元组，远端不比本地新就不更新，**不会降级**

### Fixed

- **`self_update.sh` 版本读取缺陷（定时炸弹）**：原先用 `grep -E '^\s+version:'` 只匹配**带缩进**的那行，读的其实是 `metadata` 子层版本；顶层 `version`（技能市场要求新增的）会被跳过，一旦只有顶层就会读到 `0.0.0` 误判为「有新版」；且 `\s` 在 BSD/macOS grep 下不被支持，同样会读空。已改为「顶层优先、缩进回退」双保险，并使用 POSIX 安全的 `[[:space:]]`
- **`self_update.sh`**：检测到本机有 Python 时直接委托 `self_update.py`，避免两套实现逻辑走偏；无 Python 时才走纯 bash 兜底，并明确提示旧文件未清理

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

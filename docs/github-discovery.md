# GitHub 可发现性设置（复制粘贴用）

> 按整改第四条生成。以下三项在 GitHub 仓库页 **Settings → General → About** 或仓库创建后编辑时填写。

## 1. Description（一句话，直接复制）

```
Enterprise R&D pipeline as an Agent Skill: requirement review → design → coding → self-test → code review → release → retrospective. 12-step workflow with scripts & templates.
```

中文备用（GitHub Description 建议英文，便于全球检索；中文可放 README）：

```
以《论语》为价值观的企业级研发流水线 Agent Skill：需求评审→方案→编码→自测→评审→发版→复盘，12 步 + 脚本 + 模板。
```

## 2. Topics（7 个，全部添加）

在仓库 **About** 区的 Topics 输入框逐个回车添加：

```
agent-skills
claude-skills
ai-coding
code-review
developer-tools
workflow
python
```

> 说明：`agent-skills` 覆盖 Agent Skill 生态；`claude-skills` 兼容主流 skills 检索（skills.sh 等）；`ai-coding` 命中 AI 编码助手人群；`code-review` 命中 CR 场景；`developer-tools` 命中开发者工具类；`workflow` 命中流程编排；`python` 命中脚本语言（全部脚本纯标准库）。

## 3. Homepage（可选，建议）

```
https://skills.sh
```

或如果你的技能有在线文档页，填该页地址；没有则留空，不要填仓库地址本身（GitHub 会自动显示）。

## 4. 保存后自查

- [ ] Description 已粘贴（英文一句，含 Agent Skill / R&D pipeline 关键词）
- [ ] 7 个 topics 全部添加（`agent-skills`、`claude-skills`、`ai-coding`、`code-review`、`developer-tools`、`workflow`、`python`）
- [ ] Homepage 已填（或确认留空）
- [ ] 页面显示 topics 标签与描述，保存成功
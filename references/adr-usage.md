# ADR 架构决策记录使用手册（adr.py）

> 自 SKILL.md 下沉：命令组与落盘说明。按需加载。

### 3.1 关键决策单独存档（ADR）

方案文档会随版本淹没，**后人只看到结果，不知道当初为何否决 B 方案**——于是同一个辩论反复重开。
凡有取舍处，落一条架构决策记录：

```bash
python scripts/adr.py new --title "为何不用 Redis 做主存储" \
  --context "需要持久化与事务" --decision "选 PostgreSQL" \
  --alternatives "Redis（快但无事务）" "MongoDB（灵活但一致性弱）" \
  --consequences "需要维护 schema 迁移"

python scripts/adr.py list                          # 看所有决策
python scripts/adr.py supersede 0001 --by 0005      # 决策演进，旧标「已被取代」
python scripts/adr.py link --id 0001 --version 1.2.0
```

落盘 `.lunyu/decisions/0001-xxx.md` + 索引 `decisions.json`。**被推翻的决策也要留着**——
知道「当初为什么不选」，比知道「现在选了什么」更值钱。

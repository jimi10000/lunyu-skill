# 经验库使用手册（lessons.py）

> 自 SKILL.md 下沉：沉淀 / 检索 / 命中加权 / 过期复核 / 导入导出 / 全局库。按需加载。

### 自学习：经验库（告诸往而知来者）

踩过的坑不入库，下次还得再交一次学费。闭环是：**踩坑 → 入库 → 检索命中 → 用到新需求 → 再沉淀**。

```bash
# 首次使用：导入内置种子经验（12 条通用工程教训），别从空库起步
python scripts/lessons.py seed

# 沉淀一条（复盘时做）
python scripts/lessons.py add --scene "车机静态广播不分发" \
  --problem "manifest 加的 receiver 车机静默忽略" \
  --solution "必须 Application.onCreate 动态注册兜底" \
  --tags "android,车机,广播" --kind 踩坑 --source "哪吒车机实测"

# 接到新需求先检索（Step 1 必做）
python scripts/lessons.py search "车机广播"

python scripts/lessons.py stats          # 沉淀了多少、复用率高不高
python scripts/lessons.py export --out 经验库.md
```

**命中即加权**：每次 `search` 命中会累加 `hits`，用得越多的经验自动排越靠前——不需要人工维护优先级，库会自己"学"出什么最常用。

检索到经验时的态度：**参考，不盲信**。技术会变，结论可能过期，关键决策前复核一遍——
所以有 `stale`（列出超期未复核的经验）和 `review <id>`（标记已复核）。

跨项目/跨机器流转：`export` 出 markdown 后，`import --file` 可原样导回（按 id 去重，冲突取新），
不会像以前那样导出即死。`--global` 存的经验跨项目通用。

---

**复盘完必须沉淀**（否则下次还得再摔一次）：把本次的踩坑和结论逐条入经验库。

```bash
python scripts/lessons.py add --scene "<场景>" --problem "<错在哪>"   --solution "<正确做法>" --tags "<标签>" --kind 踩坑|结论|偏好|禁区|技巧
```

判断标准：**只要这次踩了坑、或者得出了一个"下次照做"的结论，就该入库**。复盘写了但没入库，等于没沉淀。

缺陷可以直接转成经验，不用手动重录：

```bash
python scripts/lessons.py add --from-bug BUG-0001      # 从已关闭缺陷生成经验
python scripts/lessons.py stale --days 180             # 哪些经验该复核了
python scripts/lessons.py add --global --scene "..."   # 存到全局库，跨项目复用
```

`--global` 存到 `~/.lunyu/lessons.json`，`search` 默认**本地 + 全局一起查**（本地优先）。
项目级经验放项目里，**通用教训放全局库**，换项目不再从零开始。

---

**事故教训必须入经验库**——事故是最贵的学费，不入库存等于白交：

```bash
python scripts/lessons.py add --scene "<故障场景>" --problem "<根因>" \
  --solution "<根治办法>" --tags "事故,P0" --kind 禁区 --source "事故复盘"
```

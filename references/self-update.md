# 自更新 / 升级手册（self_update.py）

> 自 SKILL.md 下沉：命令组、行为、环境变量、手动升级。按需加载。

## 自更新 / 升级（已安装用户）

lunyu 本地技能不会静默自动更新。**无论你是 zip 安装包解压安装的，还是 git clone 安装的**，一条命令即可升级：

```bash
# 推荐：跨平台（Windows / macOS / Linux 全通，零依赖，不要求装 unzip/rsync）
python scripts/self_update.py

# 只看有没有新版，不改任何文件
python scripts/self_update.py --check

# 非交互直接升级（适合脚本/CI）
python scripts/self_update.py --yes

# bash 用户也可用 .sh（检测到 Python 会自动委托给 .py，两者逻辑唯一）
bash scripts/self_update.sh
```

行为：对比本地与远端的 `SKILL.md` 版本号 → 有新版才下载覆盖 → **保留 `.lunyu/` 用户数据**（缺陷台账/报告都在里面）→ 清理远端已删除的旧文件（加 `--no-prune` 可关闭）。

特点：

- **zip 安装包也能升**：走 HTTP 下载覆盖，不依赖目录里的 `.git`，`git pull` 用不了的场景照样升
- **多源回退**：GitHub raw → raw CDN → GitHub API，任一通即可；国内网络不稳时可设 `LUNYU_MIRROR` 指向镜像
- **不会降级**：远端版本 ≤ 本地时直接提示已是最新

环境变量：`LUNYU_REPO`（仓库地址）、`LUNYU_BRANCH`（默认 main）、`LUNYU_MIRROR`（镜像站）、`LUNYU_FORCE=1`（强制重装）。

升级失败时（网络不通），手动下载 `https://github.com/jimi10000/lunyu-skill/releases` 最新版 zip，解压覆盖到技能目录即可，`.lunyu/` 别删。

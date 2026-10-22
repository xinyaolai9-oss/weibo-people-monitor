# 定时采集与公网部署

整体数据流：

`MuMu 微博页面 → Windows 每 5 分钟采集 → Supabase → Streamlit Community Cloud`

公开网站不连接 MuMu，也不持有数据库写入密钥。Windows 采集端必须保持登录且 MuMu 必须持续运行；每次采集会在微博 App 中重新打开活动入口，因此不要求页面自行刷新。

## 1. 创建 Supabase 数据库

1. 创建 Supabase 项目。
2. 在 SQL Editor 中完整执行 [`schema.sql`](schema.sql)。
3. 在项目的 API Keys 页面取得：
   - Project URL；
   - Publishable key（仅用于公开网站读取）；
   - Secret key（仅保存在采集电脑，用于写入）。

不要把 Secret key 发到聊天、提交到 GitHub 或填入 Streamlit Cloud。

在项目根目录复制 `.env.example` 为 `.env`，至少填写：

```dotenv
STORAGE_BACKEND=supabase
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SECRET_KEY=YOUR_SECRET_KEY
SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
ADB_PATH=D:\Program Files\Netease\MuMu\nx_main\adb.exe
MUMU_REFRESH_STRATEGY=deeplink
MUMU_REFRESH_WAIT_SECONDS=8
```

通常不要设置 `ADB_SERIAL`：MuMu 的 ADB 端口可能在重启后变化，采集器会通过 `mumu-cli` 自动发现并连接当前实例。

`deeplink` 刷新只调用 Android Activity Manager 重新打开既有活动链接，不点击投票按钮。若微博要求重新登录或出现验证，应由用户手动处理，不应尝试绕过。可用 `--refresh-strategy none` 临时关闭刷新。

`.env` 已被 `.gitignore` 排除。

## 2. 验证云端读写

先只解析，不写入：

```powershell
python android_collector.py --dry-run
```

确认人物和分数正确后写入 Supabase：

```powershell
python android_collector.py
```

再启动本地看板。如果能显示刚才的数据，说明公开读取策略正常：

```powershell
python -m streamlit run app.py
```

如需把现有 SQLite 历史记录上传到 Supabase：

```powershell
python migrate_sqlite_to_supabase.py --dry-run
python migrate_sqlite_to_supabase.py
```

迁移使用 upsert，可以安全重跑；唯一键相同的快照不会重复。

## 3. 安装 Windows 定时任务

先手动验证任务包装脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_collector.ps1 -DryRun
```

确认 `logs/collector-YYYY-MM-DD.log` 中显示成功后，安装每 5 分钟运行一次的任务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_task.ps1 -IntervalMinutes 5
```

安装脚本会把触发器对齐到电脑本地时钟的 5 分钟整点，即每小时的 `00、05、10……55` 分运行，而不是从安装时刻任意顺延 5 分钟。

查看任务状态：

```powershell
Get-ScheduledTask -TaskName WeiboPeopleMonitorCollector
Get-ScheduledTaskInfo -TaskName WeiboPeopleMonitorCollector
```

任务采用 `IgnoreNew`，前一次采集未结束时不会叠加启动。它只在当前 Windows 用户已登录时运行，因为 MuMu 属于该用户的交互式会话。

停止并删除定时任务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\uninstall_task.ps1
```

## 4. 推送到 GitHub

Streamlit Community Cloud 从 GitHub 仓库部署。创建一个仓库后，在项目根目录执行：

```powershell
git init
git add .
git commit -m "Build Weibo people monitoring dashboard"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/YOUR_REPOSITORY.git
git push -u origin main
```

提交前执行 `git status`，确认以下内容没有出现：

- `.env`
- `.streamlit/secrets.toml`
- `score_snapshots.db`
- `debug/`
- `logs/`

## 5. 部署 Streamlit Community Cloud

1. 登录 `https://share.streamlit.io/` 并连接 GitHub。
2. 选择刚创建的仓库和 `main` 分支。
3. App file 设置为 `app.py`。
4. 在 Advanced settings → Secrets 中填写：

```toml
STORAGE_BACKEND = "supabase"
SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "YOUR_PUBLISHABLE_KEY"
```

5. 部署并选择可用的 `*.streamlit.app` 子域名。

网站只获得公开读取权限。采集电脑上的 `SUPABASE_SECRET_KEY` 不得复制到 Streamlit。

## 6. 上线检查

- 网站能显示 `final` 赛段的趋势，并能自定义起止时间；
- “最近成功采样”每约 5 分钟变化；
- 关闭 MuMu 后，网站继续显示历史数据，但会出现数据过期警告；
- 查看 `logs/` 和 Windows 任务的 `LastTaskResult` 排查采集失败；
- 活动结束后删除定时任务，避免继续采集。

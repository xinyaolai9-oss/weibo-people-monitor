# 2026 微博视界大会 · 剧综人物 推荐值监控（starter）

这个仓库是**可运行的看板和 MuMu 只读采集原型**。已验证微博 Wbox 的 Android UI 元素树会暴露“剧综人物”的人物名和页面推荐值，因此无需 OCR 即可读取当前榜单。页面使用 `0.1w` 等缩写，数据会标记为近似值。只有在页面运营方允许自动化读取时才使用采集功能。**程序只读取当前 UI，不自动投票、不登录、不滑动、不绕过限制。**

## 本地演示（无需访问微博）
```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
cp .env.example .env  # Windows: copy .env.example .env
python demo_seed.py
streamlit run app.py
```
在侧边栏选择 `demo` 可观察明确标注的模拟数据趋势。

## 使用 MuMu 模拟器采集
1. 在 MuMu 中手动登录官方微博 App，进入「剧综人物」榜单并保持页面打开。
2. 确认 MuMu 已开启 ADB。程序会自动查找常见安装位置；ADB 设备列表为空时会通过 `mumu-cli` 自动连接正在运行的实例。也可设置 `ADB_PATH`、`MUMU_CLI_PATH` 和 `ADB_SERIAL`。
3. 首次先做只读测试，不写数据库：
```powershell
python android_collector.py --dry-run --save-artifacts
```
4. 核对输出的人物、赛段和推荐值。确认无误后采集一次：
```powershell
python android_collector.py
```
5. 程序默认要求至少解析到 15 人、没有重复人物且每张卡片均可解析。官方人数明确且稳定时，可以额外锁定人数：
```powershell
python android_collector.py --expected-candidates 15
```

采集器会自动识别 `入围赛 / 突围赛 / 巅峰赛`，并将 UI 中的 `2085.1w` 存为 `20,851,000` 且设置 `score_approx=true`。UI 没有可靠的排名文本，因此数据库中的 `rank` 留空，看板只显示“观测排序”。

可以先离线检查已经导出的 UI 文件：
```powershell
python android_collector.py --xml debug/window.xml --dry-run
```

## 网页采集备用方案
1. 检查活动页面及允许的自动化访问条件。链接 `https://t.cn/AXWvhBOy` 是公开传播的活动入口，但并未验证跳转目的页可公开爬取。
2. 获得许可后运行 `pip install -r requirements-web.txt` 和 `python -m playwright install chromium`，再执行 `python probe_page.py` 观察跳转地址、可见文字和保存的截图。若出现登录、验证码、访问拒绝，请停止并改用授权数据源。
3. 在 `.env` 中设置 `CARD_SELECTOR`、`NAME_SELECTOR`、`SCORE_SELECTOR`，可选 `RANK_SELECTOR`、`CATEGORY_TAB_SELECTOR`（仅赛道切换按钮，不是投票按钮）、`ID_ATTRIBUTE`。
4. 运行 `python collector.py`。只有所有卡片解析成功且无重复人物 ID 时，才写入同时间戳数据。
5. 当页面只有“1.2万”等简写时，数据库标记 `score_approx = true`，不应将其用作高精度增速或精确差距判断。

**注意：** 移动端分页/懒加载可能需要专门修改 `collector.py`。默认只滚动三次，不保证抓齐全榜。未抓齐时网页仅报告“已采集人数”“观测排序”。若有官方 rank 字段再显示官方名次。赛段重置应通过 `STAGE` 分表逻辑隔离。

## 部署到公开网站
完整操作见 [`DEPLOYMENT.md`](DEPLOYMENT.md)。

1. 在 Supabase 新建项目，在 SQL Editor 执行 `schema.sql`。开启 Row Level Security：允许匿名查询公开榜单；不给匿名角色写入权限。
2. 采集服务器上的 `.env` 设置 `STORAGE_BACKEND=supabase`、`SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`；使用最小必要权限，不要上传到 GitHub。
3. Streamlit Community Cloud 将本仓库部署为网站。网站端仅设置 `STORAGE_BACKEND=supabase`、`SUPABASE_URL`、`SUPABASE_ANON_KEY`，**不设置 SERVICE_ROLE_KEY**。
4. 在获准读取的前提下，使用合适的云端定时任务执行 `python collector.py`。建议先以 5 分钟采样测试稳定性，访问频率必须服从源站规定。采集应在活动期间运行，并在活动结束后停止。
5. 网站每 60 秒重新读取数据库。该频率只影响网页更新，不表示官方分数每 60 秒变化。

## 推荐的数据字段
`stage, category, candidate_id, candidate_name, score, score_approx, rank, observed_at, source`

## 数据正确性约束
- `stage` 必须与官方赛段吻合；切换阶段时不得沿用前一阶段增长基准。
- 数据爬取失败时不能用零填充，不能覆盖上一轮数据。
- 只有采集到当前页面全部有效卡片时，才能声称覆盖全赛道。
- 公开展示时标明非官方、最近成功采样时间、是否使用近似分数、抓取人数。
- 不保证可抓取封闭页面、需要授权的接口、验证码保护内容或其他受限制内容。

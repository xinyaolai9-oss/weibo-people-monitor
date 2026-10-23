# 2026 微博视界大会 · 剧综人物 推荐值监控（starter）

这个仓库是**可运行的看板和 MuMu 只读采集原型**。页面仍提供人物名时优先读取 Android UI 元素树；人物名隐藏后，可使用经过人工确认的本地头像参考库。页面使用 `0.1w` 等缩写，数据会标记为近似值。只有在页面运营方允许自动化读取时才使用采集功能。**程序只重新打开活动入口、读取 UI/截图，并在头像模式下纵向滚动榜单；不自动投票、不登录、不绕过限制。**

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
看板默认展示 `final` 赛段，可在主页面自定义日期和精确起止时间。

## 使用 MuMu 模拟器采集
1. 在 MuMu 中手动登录官方微博 App，并确认活动可以正常打开。
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

实时采集默认会先通过 Android 深链在微博 App 中重新打开活动入口，等待 8 秒后读取 UI 树，从而避免依赖活动页是否自行刷新。此动作不点击任何页面按钮。需要临时关闭时可使用 `--refresh-strategy none`；页面加载较慢时可将 `MUMU_REFRESH_WAIT_SECONDS` 调大。

### 人物名称隐藏后的头像模式

头像参考图只保存在采集电脑的 `avatar_references/`，已被 Git 忽略，不会上传到网站或 GitHub。默认固定监控前 15 位；如果有新人物进入前 15、头像变化、赛段变化、元数据不一致、数量不完整或匹配不唯一，整轮数据都会拒绝写入。

首次生成待确认参考库：

```powershell
python android_collector.py --build-avatar-references
```

人工检查 `avatar_references/contact_sheet.png` 中的头像、排名和建议姓名，再用第二轮独立截图验证稳定性：

```powershell
python android_collector.py --validate-avatar-references
```

确认 15 个姓名全部正确后，必须按联系表顺序逐一重复姓名才能批准；示例：

```powershell
python android_collector.py --approve-avatar-references --confirm-avatar-names "姓名1,姓名2,姓名3,...,姓名15"
```

批准后先做不写库测试：

```powershell
python android_collector.py --dry-run
```

匹配同时要求：头像相似度至少 `0.88`、相对第二候选至少领先 `0.05`、所有头像一对一唯一匹配，并且卡片分类/作品信息与参考库一致。可通过 `AVATAR_MATCH_THRESHOLD`、`AVATAR_MATCH_MARGIN` 和 `AVATAR_TARGET_CANDIDATES` 调整，但不建议降低默认安全阈值。

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
5. 网站每 60 秒重新读取数据库。该频率只影响网页更新，不表示官方分数每 60 秒变化。图表支持用户指定日期、开始时间和结束时间。

## 推荐的数据字段
`stage, category, candidate_id, candidate_name, score, score_approx, rank, observed_at, source`

## 数据正确性约束
- `stage` 必须与官方赛段吻合；切换阶段时不得沿用前一阶段增长基准。
- 数据爬取失败时不能用零填充，不能覆盖上一轮数据。
- 只有采集到当前页面全部有效卡片时，才能声称覆盖全赛道。
- 公开展示时标明非官方、最近成功采样时间、是否使用近似分数、抓取人数。
- 不保证可抓取封闭页面、需要授权的接口、验证码保护内容或其他受限制内容。

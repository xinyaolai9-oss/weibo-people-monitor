"""Public, read-only fan-made dashboard. Refresh does NOT trigger a crawl."""
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from storage import fetch_snapshots

load_dotenv()
st.set_page_config(page_title="剧综人物·推荐值监控", page_icon="📊", layout="wide")

# Community Cloud provides root-level secrets through st.secrets. Mirror only
# the public/read-only settings into the environment expected by storage.py.
try:
    for key in ("STORAGE_BACKEND", "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY"):
        if key in st.secrets:
            os.environ.setdefault(key, str(st.secrets[key]))
except FileNotFoundError:
    pass

st.title("2026 微博视界大会 · 剧综人物")
st.caption("非官方独立统计 | 推荐值仅供参考 | 采集失败时可能延迟 | 北京时间")

stage = st.sidebar.selectbox("查看赛段", ["final", "demo", "breakthrough", "qualifier"], index=0)
hours = st.sidebar.selectbox("趋势时间范围", [1, 6, 12, 24], index=1)
st.sidebar.caption("演示数据仅供测试，不能作为真实榜单使用。")

@st.cache_data(ttl=30)
def read_data(stage, hours):
    return fetch_snapshots(stage, hours=max(hours, 1) + 1)

@st.fragment(run_every="60s")
def dashboard():
    try:
        records = read_data(stage, hours)
    except Exception as exc:
        st.error(f"读取数据失败：{type(exc).__name__}: {exc}")
        return
    if not records:
        st.info("该赛段尚无采样数据。先运行 python demo_seed.py，然后在左边选择 demo 查看示例。")
        return
    df = pd.DataFrame(records)
    df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)
    df["score"] = pd.to_numeric(df["score"])
    df["score_approx"] = df["score_approx"].astype(bool)
    last = df["observed_at"].max()
    # Only show records from the newest complete sample: otherwise stale candidates
    # can pollute apparent rankings when a later sample covers fewer candidates.
    current = df[df["observed_at"] == last].copy()
    current = current.sort_values("score", ascending=False).reset_index(drop=True)
    current["观测排序"] = range(1, len(current) + 1)
    recent_age = (datetime.now(timezone.utc) - last.to_pydatetime()).total_seconds() / 60
    official_ranks = current["rank"].notna().all()
    observed_time = last.tz_convert(ZoneInfo("Asia/Shanghai")).strftime("%m-%d %H:%M:%S")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("最近成功采样 (北京时间)", observed_time)
    m2.metric("本次采集人数", len(current))
    m3.metric("本次最高推荐值", f"{int(current['score'].max()):,}")
    m4.metric("距最近采样", f"{recent_age:.1f} 分钟")
    if recent_age > 12:
        st.warning("数据超过 12 分钟未更新，请检查采集日志。")
    if current["score_approx"].any():
        st.warning("部分源站分数采用了‘万/亿’等缩写，已标记为近似值，不适合精确增量分析。")
    st.subheader("当前已采集人物榜单")
    current["推荐值"] = current["score"].map(lambda x: f"{int(x):,}")
    current["是否近似"] = current["score_approx"].map({True: "是", False: "否"})
    columns = ["candidate_name", "推荐值", "是否近似"]
    if official_ranks:
        columns.insert(0, "rank")
    else:
        columns.insert(0, "观测排序")
    table = current[columns].copy()
    table.columns = ["官方排名" if c == "rank" else "人物" if c == "candidate_name" else c for c in table.columns]
    st.dataframe(table, use_container_width=True, hide_index=True)
    if not official_ranks:
        st.caption("没有可靠的官方排名字段：上表仅按本次已采集分数排序，不代表官方全榜名次。")
    st.subheader("推荐值趋势对比")
    defaults = current["candidate_name"].head(5).tolist()
    selected = st.multiselect("选择关注人物", current["candidate_name"].tolist(), default=defaults)
    since = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
    trend = df[(df["candidate_name"].isin(selected)) & (df["observed_at"] >= since)].copy()
    if trend.empty:
        st.info("选择至少一位人物以显示趋势。")
    else:
        trend["北京时间"] = trend["observed_at"].dt.tz_convert("Asia/Shanghai")
        fig = px.line(trend.sort_values("北京时间"), x="北京时间", y="score", color="candidate_name",
                      labels={"score": "推荐值", "candidate_name": "人物"}, markers=True)
        fig.update_layout(margin=dict(t=20, b=20, l=10, r=10), legend_title_text="人物")
        st.plotly_chart(fig, use_container_width=True)
    st.caption("网站定期读取数据库，不发起投票或主动请求微博。采集任务单独运行；历史数据从部署后首次采样开始。")

dashboard()

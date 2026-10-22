"""Public, read-only dashboard for the collected Weibo ranking snapshots."""

import importlib
import inspect
import math
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

import storage as storage_module


# Streamlit Community Cloud can hot-reload app.py without restarting imported
# modules. Reload storage explicitly so a deployment never mixes a new page
# with the previous fetch_snapshots signature.
storage_module = importlib.reload(storage_module)
fetch_snapshots = storage_module.fetch_snapshots


load_dotenv()
BEIJING = ZoneInfo("Asia/Shanghai")
STAGE = "final"

st.set_page_config(
    page_title="剧综人物 · 推荐值趋势",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Community Cloud exposes root-level secrets through st.secrets. Only the
# public/read-only settings are mirrored into the environment used by storage.
try:
    for key in (
        "STORAGE_BACKEND",
        "SUPABASE_URL",
        "SUPABASE_PUBLISHABLE_KEY",
        "SUPABASE_ANON_KEY",
    ):
        if key in st.secrets:
            os.environ.setdefault(key, str(st.secrets[key]))
except FileNotFoundError:
    pass

st.markdown(
    """
    <style>
    :root {
        --ink: #f8efe6;
        --muted: #b9aaa0;
        --gold: #e8b66b;
        --line: rgba(232, 182, 107, .20);
        --panel: rgba(29, 20, 18, .78);
    }
    [data-testid="stAppViewContainer"] {
        background:
            radial-gradient(circle at 8% -10%, rgba(151, 72, 38, .25), transparent 34rem),
            radial-gradient(circle at 95% 15%, rgba(195, 128, 57, .12), transparent 28rem),
            #0d0a0a;
        color: var(--ink);
    }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stSidebar"] { display: none; }
    .block-container { max-width: 1220px; padding-top: 2rem; padding-bottom: 3rem; }
    .hero {
        padding: 2.2rem 2.4rem;
        border: 1px solid var(--line);
        border-radius: 24px;
        background: linear-gradient(125deg, rgba(61, 31, 23, .94), rgba(24, 17, 16, .88));
        box-shadow: 0 18px 60px rgba(0, 0, 0, .30);
        margin-bottom: 1.2rem;
    }
    .eyebrow { color: var(--gold); letter-spacing: .16em; font-size: .78rem; font-weight: 700; }
    .hero h1 { color: #fff8ef; font-size: clamp(2rem, 4vw, 3.4rem); margin: .38rem 0 .55rem; }
    .hero p { color: var(--muted); margin: 0; font-size: 1rem; }
    [data-testid="stMetric"] {
        background: var(--panel);
        border: 1px solid rgba(255,255,255,.07);
        padding: 1rem 1.1rem;
        border-radius: 16px;
        min-height: 112px;
    }
    [data-testid="stMetricLabel"] { color: var(--muted); }
    [data-testid="stMetricValue"] { color: #fff6e9; }
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--line) !important;
        background: rgba(19, 14, 13, .62);
        border-radius: 18px;
    }
    div[data-baseweb="select"] > div,
    div[data-baseweb="input"] > div { border-color: rgba(232, 182, 107, .26); }
    .section-kicker { color: var(--gold); font-weight: 700; letter-spacing: .08em; margin-bottom: -.4rem; }
    .fineprint { color: #8f8179; font-size: .84rem; line-height: 1.65; margin-top: 1.2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
      <div class="eyebrow">LIVE VOTING ANALYTICS · 2026</div>
      <h1>微博视界大会 · 剧综人物</h1>
      <p>非官方独立统计 · 推荐值为页面展示的近似值 · 时间均为北京时间</p>
    </div>
    """,
    unsafe_allow_html=True,
)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


@st.cache_data(ttl=30)
def read_interval(start_at: str, end_at: str):
    if "start_at" in inspect.signature(fetch_snapshots).parameters:
        return fetch_snapshots(
            STAGE,
            hours=None,
            start_at=start_at,
            end_at=end_at,
            limit=60000,
        )

    # Compatibility for an already-running Streamlit process that still has
    # the pre-interval storage function cached. Query a broad window, then
    # apply the exact bounds locally until the process restarts.
    start = datetime.fromisoformat(start_at)
    end = datetime.fromisoformat(end_at)
    hours = max(
        1,
        math.ceil((datetime.now(timezone.utc) - start).total_seconds() / 3600) + 1,
    )
    rows = fetch_snapshots(STAGE, hours=hours, limit=60000)
    return [
        row
        for row in rows
        if start <= datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00")) <= end
    ]


@st.cache_data(ttl=30)
def read_latest():
    return fetch_snapshots(STAGE, hours=None, limit=100)


now_beijing = datetime.now(BEIJING)
default_start = now_beijing - timedelta(hours=6)

st.markdown('<p class="section-kicker">趋势时间区间</p>', unsafe_allow_html=True)
with st.container(border=True):
    start_group, end_group = st.columns(2, gap="large")
    with start_group:
        st.markdown("**开始时间**")
        start_date_col, start_time_col = st.columns([1.35, 1])
        with start_date_col:
            selected_start_date = st.date_input(
                "开始日期",
                value=default_start.date(),
                max_value=now_beijing.date(),
                format="YYYY-MM-DD",
            )
        with start_time_col:
            selected_start_time = st.time_input(
                "开始时刻",
                value=default_start.time().replace(second=0, microsecond=0),
                step=300,
            )
    with end_group:
        st.markdown("**结束时间**")
        end_date_col, end_time_col = st.columns([1.35, 1])
        with end_date_col:
            selected_end_date = st.date_input(
                "结束日期",
                value=now_beijing.date(),
                max_value=now_beijing.date(),
                format="YYYY-MM-DD",
            )
        with end_time_col:
            selected_end_time = st.time_input(
                "结束时刻",
                value=now_beijing.time().replace(second=0, microsecond=0),
                step=300,
            )

start_beijing = datetime.combine(selected_start_date, selected_start_time, tzinfo=BEIJING)
end_beijing = datetime.combine(selected_end_date, selected_end_time, tzinfo=BEIJING)
if end_beijing <= start_beijing:
    st.error("结束时间必须晚于开始时间。")
    st.stop()
if end_beijing - start_beijing > timedelta(days=31):
    st.error("单次最多查询 31 天，请缩短时间区间。")
    st.stop()


def _prepare(records: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    frame["score"] = pd.to_numeric(frame["score"])
    frame["score_approx"] = frame["score_approx"].astype(bool)
    return frame


@st.fragment(run_every="60s")
def dashboard() -> None:
    try:
        interval_df = _prepare(read_interval(_utc_iso(start_beijing), _utc_iso(end_beijing)))
        latest_df = _prepare(read_latest())
    except Exception as exc:
        st.error(f"读取数据失败：{type(exc).__name__}: {exc}")
        return

    if latest_df.empty:
        st.info("尚无可用采样数据，请先确认电脑端采集任务正在运行。")
        return

    latest_time = latest_df["observed_at"].max()
    latest_sample = latest_df[latest_df["observed_at"] == latest_time].copy()
    age_minutes = max(
        0.0,
        (datetime.now(timezone.utc) - latest_time.to_pydatetime()).total_seconds() / 60,
    )
    status = "正常" if age_minutes <= 12 else "延迟"
    latest_label = latest_time.tz_convert(BEIJING).strftime("%m-%d %H:%M")
    sample_count = 0 if interval_df.empty else interval_df["observed_at"].nunique()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("数据状态", status)
    m2.metric("最近采样", latest_label)
    m3.metric("当前采集人数", len(latest_sample))
    m4.metric("区间采样次数", f"{sample_count:,}")

    if age_minutes > 12:
        st.warning(f"最近一次采样距今 {age_minutes:.1f} 分钟，请检查 MuMu 和定时任务日志。")
    if latest_sample["score_approx"].any():
        st.caption("页面以“万”等单位展示推荐值，曲线中的数值为按显示精度换算的近似值。")

    st.markdown("### 推荐值趋势")
    if interval_df.empty:
        st.info("所选时间区间内没有采样数据，请调整起止时间。")
        return

    end_sample_time = interval_df["observed_at"].max()
    end_sample = interval_df[interval_df["observed_at"] == end_sample_time].sort_values(
        "score", ascending=False
    )
    all_names = end_sample["candidate_name"].tolist()
    for name in interval_df["candidate_name"].drop_duplicates().tolist():
        if name not in all_names:
            all_names.append(name)

    selected = st.multiselect(
        "选择要对比的人物",
        all_names,
        default=all_names[:5],
        placeholder="输入人物名称",
    )
    st.caption(
        f"当前区间：{start_beijing.strftime('%Y-%m-%d %H:%M')} — "
        f"{end_beijing.strftime('%Y-%m-%d %H:%M')}（北京时间）"
    )
    trend = interval_df[interval_df["candidate_name"].isin(selected)].copy()
    if trend.empty:
        st.info("请选择至少一位人物以显示趋势。")
        return

    trend["北京时间"] = trend["observed_at"].dt.tz_convert(BEIJING)
    palette = ["#f4c272", "#ef8262", "#d8a7e8", "#79c7c5", "#9fb9f4", "#c6d77b", "#e9a6b2"]
    fig = px.line(
        trend.sort_values("北京时间"),
        x="北京时间",
        y="score",
        color="candidate_name",
        color_discrete_sequence=palette,
        labels={"score": "推荐值", "candidate_name": "人物"},
        markers=True,
    )
    fig.update_traces(line={"width": 2.5}, marker={"size": 4})
    fig.update_layout(
        height=560,
        margin={"t": 28, "b": 20, "l": 10, "r": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#e9ddd4"},
        legend={
            "title_text": "人物",
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
        },
        hovermode="x unified",
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,.07)", showline=False)
    fig.update_yaxes(gridcolor="rgba(255,255,255,.07)", tickformat=",d", showline=False)
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})

    st.markdown(
        '<p class="fineprint">网站每 60 秒读取一次数据库；采集任务在本地电脑独立运行。'
        "重新载入网页不会触发采集，也不会发起投票。</p>",
        unsafe_allow_html=True,
    )


dashboard()

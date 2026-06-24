"""
SkillCorner Scout Intelligence
実行: streamlit run app.py
"""
import os, sys, json, time, csv, io, tempfile
from pathlib import Path
from datetime import datetime, date

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import numpy as np

# ============================================================
#  CONFIG
# ============================================================
st.set_page_config(
    page_title="SkillCorner Scout Intelligence",
    page_icon="⚽", layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown("""<style>
[data-testid="stSidebar"]{background:#0c1220}
div[data-testid="stMetricValue"]{font-size:1.6rem}
.stTabs [data-baseweb="tab"]{padding:8px 16px}
</style>""", unsafe_allow_html=True)

# ============================================================
#  SEASONS
# ============================================================
SEASONS = {
    "J2 2024":          {"id": 788,  "label": "J2 League 2024"},
    "J2 2025":          {"id": 1076, "label": "J2 League 2025"},
    "J3 2025":          {"id": 1077, "label": "J3 League 2025"},
    "J2/J3 2026":       {"id": 1426, "label": "J2/J3 百年構想 2026"},
    "J2/J3 2027":       {"id": 1643, "label": "J2/J3 百年構想 2027"},
}
DEFAULT_SEASON = "J2/J3 2026"
YFC_TEAM_ID = 930

# ============================================================
#  CACHE DIR
# ============================================================
_base = Path(__file__).parent / "data"
try:
    _base.mkdir(exist_ok=True)
    (_base / ".test").write_text("ok"); (_base / ".test").unlink()
    CACHE_BASE = _base
except (PermissionError, OSError):
    CACHE_BASE = Path(tempfile.gettempdir()) / "sc_cache"
    CACHE_BASE.mkdir(exist_ok=True)

def cache_dir(season_key):
    d = CACHE_BASE / str(SEASONS[season_key]["id"])
    d.mkdir(exist_ok=True)
    return d

def _load(season_key, key):
    p = cache_dir(season_key) / f"{key}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except: return None
    return None

def _save(season_key, key, data):
    p = cache_dir(season_key) / f"{key}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, default=str))

def load_meta(season_key):
    m = _load(season_key, "meta")
    return m or {
        "last_updated": None,
        "summary_done": False,
        "dynamic_done": False,
        "obr_done": [],
        "po_done": [],
        "pp_done": [],
    }

def save_meta(season_key, m):
    _save(season_key, "meta", m)

# ============================================================
#  API CLIENT
# ============================================================
def get_client():
    try:
        from skillcorner.client import SkillcornerClient
        return SkillcornerClient(
            username=st.session_state.get("sc_user", "r.komori@yokohamafc.com"),
            password=st.session_state.get("sc_pass", "Rion3375"),
        )
    except Exception as e:
        st.error(f"SkillCorner接続エラー: {e}")
        return None

# ============================================================
#  DATA FETCH
# ============================================================
def fetch_summary(client, season_key, prog=None):
    """集計データ取得（matches/runs/passes/pressures/physical）"""
    ced = SEASONS[season_key]["id"]
    meta = load_meta(season_key)

    # matches
    if prog: prog.progress(0.05, text="試合情報取得中...")
    matches = client.get_matches(params={"competition_edition": ced})
    _save(season_key, "matches", matches)

    team_ids = sorted({m["home_team"]["id"] for m in matches} |
                      {m["away_team"]["id"] for m in matches})
    total = len(team_ids)

    runs_all, passes_all, press_all = [], [], []

    for i, tid in enumerate(team_ids):
        pct = 0.05 + 0.85 * (i / total)
        if prog: prog.progress(pct, text=f"チーム {i+1}/{total} 取得中...")
        params = {"competition_edition": ced, "team": tid}
        try:
            runs_all  += client.get_in_possession_off_ball_runs(params=params)
            time.sleep(0.2)
        except: pass
        try:
            passes_all += client.get_in_possession_passes(params=params)
            time.sleep(0.2)
        except: pass
        try:
            press_all  += client.get_in_possession_on_ball_pressures(params=params)
            time.sleep(0.2)
        except: pass

    _save(season_key, "runs",    runs_all)
    _save(season_key, "passes",  passes_all)
    _save(season_key, "pressures", press_all)

    if prog: prog.progress(0.95, text="フィジカルデータ取得中...")
    try:
        phy = client.get_physical(params={"competition_edition": ced})
        _save(season_key, "physical", phy)
    except: pass

    meta["summary_done"] = True
    meta["last_updated"] = datetime.now().isoformat()
    save_meta(season_key, meta)
    if prog: prog.progress(1.0, text="完了")
    return len(matches)

def fetch_dynamic(client, season_key, prog=None):
    """Dynamic Events取得（OBR/PO/PP）"""
    meta = load_meta(season_key)
    matches = _load(season_key, "matches") or []
    all_ids = [m["id"] for m in matches]

    obr_done = set(meta.get("obr_done", []))
    po_done  = set(meta.get("po_done",  []))
    pp_done  = set(meta.get("pp_done",  []))

    existing_obr = _load(season_key, "obr") or []
    existing_po  = _load(season_key, "po")  or []
    existing_pp  = _load(season_key, "pp")  or []

    new_obr, new_po, new_pp = [], [], []
    total = len(all_ids) * 3
    done = 0

    for mid in all_ids:
        if prog: prog.progress(done/total, text=f"OBR {mid}")
        if mid not in obr_done:
            try:
                data = client.get_dynamic_events_off_ball_runs(match_id=str(mid))
                if isinstance(data, bytes):
                    new_obr += list(csv.DictReader(io.StringIO(data.decode())))
                    obr_done.add(mid)
                time.sleep(0.3)
            except Exception as e:
                if "quality standard" not in str(e): pass
        done += 1

    for mid in all_ids:
        if prog: prog.progress(done/total, text=f"PO {mid}")
        if mid not in po_done:
            try:
                data = client.get_dynamic_events_passing_options(match_id=str(mid))
                if isinstance(data, bytes):
                    new_po += list(csv.DictReader(io.StringIO(data.decode())))
                    po_done.add(mid)
                time.sleep(0.3)
            except Exception as e:
                if "quality standard" not in str(e): pass
        done += 1

    for mid in all_ids:
        if prog: prog.progress(done/total, text=f"PP {mid}")
        if mid not in pp_done:
            try:
                data = client.get_dynamic_events_player_possessions(match_id=str(mid))
                if isinstance(data, bytes):
                    new_pp += list(csv.DictReader(io.StringIO(data.decode())))
                    pp_done.add(mid)
                time.sleep(0.3)
            except Exception as e:
                if "quality standard" not in str(e): pass
        done += 1

    _save(season_key, "obr", existing_obr + new_obr)
    _save(season_key, "po",  existing_po  + new_po)
    _save(season_key, "pp",  existing_pp  + new_pp)

    meta["obr_done"] = list(obr_done)
    meta["po_done"]  = list(po_done)
    meta["pp_done"]  = list(pp_done)
    meta["dynamic_done"] = True
    meta["last_updated"]  = datetime.now().isoformat()
    save_meta(season_key, meta)
    if prog: prog.progress(1.0, text="完了")
    return len(new_obr), len(new_po), len(new_pp)

# ============================================================
#  DATAFRAME HELPERS
# ============================================================
@st.cache_data(ttl=86400)
def df_runs(season_key):
    d = _load(season_key, "runs")
    return pd.DataFrame(d) if d else pd.DataFrame()

@st.cache_data(ttl=86400)
def df_passes(season_key):
    d = _load(season_key, "passes")
    return pd.DataFrame(d) if d else pd.DataFrame()

@st.cache_data(ttl=86400)
def df_pressures(season_key):
    d = _load(season_key, "pressures")
    return pd.DataFrame(d) if d else pd.DataFrame()

@st.cache_data(ttl=86400)
def df_physical(season_key):
    d = _load(season_key, "physical")
    return pd.DataFrame(d) if d else pd.DataFrame()

@st.cache_data(ttl=86400)
def df_obr(season_key):
    d = _load(season_key, "obr")
    if not d: return pd.DataFrame()
    df = pd.DataFrame(d)
    for c in ["x_start","y_start","x_end","y_end","xthreat"]:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

@st.cache_data(ttl=86400)
def df_pp(season_key):
    d = _load(season_key, "pp")
    if not d: return pd.DataFrame()
    df = pd.DataFrame(d)
    for c in ["x_start","y_start","x_end","y_end",
              "player_targeted_x_reception","player_targeted_y_reception","player_targeted_xthreat"]:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def num(df, col):
    return pd.to_numeric(df[col], errors="coerce") if col in df.columns else pd.Series(0, index=df.index)

# ============================================================
#  PITCH
# ============================================================
PITCH_SHAPES = [
    dict(type="rect",  x0=-52.5,y0=-34,   x1=52.5, y1=34,   fillcolor="#1a4020",line=dict(color="rgba(255,255,255,.5)",width=1)),
    dict(type="line",  x0=0,    y0=-34,   x1=0,    y1=34,   line=dict(color="rgba(255,255,255,.4)",width=1)),
    dict(type="rect",  x0=-52.5,y0=-20.16,x1=-36,  y1=20.16,line=dict(color="rgba(255,255,255,.4)",width=1)),
    dict(type="rect",  x0=36,   y0=-20.16,x1=52.5, y1=20.16,line=dict(color="rgba(255,255,255,.4)",width=1)),
    dict(type="circle",x0=-9.15,y0=-9.15, x1=9.15, y1=9.15, line=dict(color="rgba(255,255,255,.4)",width=1)),
    dict(type="rect",  x0=-52.5,y0=-9.16, x1=-47,  y1=9.16, line=dict(color="rgba(255,255,255,.4)",width=1)),
    dict(type="rect",  x0=47,   y0=-9.16, x1=52.5, y1=9.16, line=dict(color="rgba(255,255,255,.4)",width=1)),
]
PITCH_LAYOUT = dict(
    xaxis=dict(range=[-55,55],showgrid=False,zeroline=False,visible=False),
    yaxis=dict(range=[-37,37],showgrid=False,zeroline=False,visible=False,scaleanchor="x"),
    plot_bgcolor="#1a4020", paper_bgcolor="#0c1220",
    margin=dict(l=0,r=0,t=10,b=0),
)

SUBTYPE_COLORS = {
    "run_ahead_of_the_ball":"#00d4ff","support":"#22c55e","coming_short":"#f59e0b",
    "dropping_off":"#94a3b8","cross_receiver":"#f97316","behind":"#ef4444",
    "pulling_wide":"#a855f7","overlap":"#06b6d4","pulling_half_space":"#8b5cf6","underlap":"#ec4899",
}
SUBTYPE_JP = {
    "run_ahead_of_the_ball":"前方ラン","support":"サポート","coming_short":"ショート",
    "dropping_off":"ドロップ","cross_receiver":"クロス受け","behind":"裏抜け",
    "pulling_wide":"ワイド","overlap":"オーバーラップ","pulling_half_space":"ハーフスペース","underlap":"アンダーラップ",
}

# ============================================================
#  SESSION STATE
# ============================================================
if "sc_user" not in st.session_state:
    st.session_state["sc_user"] = "r.komori@yokohamafc.com"
    st.session_state["sc_pass"] = "Rion3375"

# ============================================================
#  SIDEBAR
# ============================================================
with st.sidebar:
    st.markdown("## ⚽ SkillCorner Scout")
    st.markdown("---")

    # シーズン選択
    st.markdown("### 📅 シーズン")
    season_key = st.selectbox(
        "シーズン選択",
        list(SEASONS.keys()),
        index=list(SEASONS.keys()).index(DEFAULT_SEASON),
        label_visibility="collapsed",
    )
    st.caption(f"competition_edition_id: {SEASONS[season_key]['id']}")

    st.markdown("---")

    # データ状態
    meta = load_meta(season_key)
    st.markdown("### 📊 データ状態")
    matches_data = _load(season_key, "matches") or []
    obr_count = len(set(meta.get("obr_done", [])))
    pp_count  = len(set(meta.get("pp_done",  [])))

    c1,c2,c3 = st.columns(3)
    c1.metric("試合",  len(matches_data))
    c2.metric("OBR",   obr_count)
    c3.metric("PP",    pp_count)

    if meta.get("last_updated"):
        dt = datetime.fromisoformat(meta["last_updated"])
        st.caption(f"最終更新: {dt.strftime('%Y/%m/%d %H:%M')}")
    else:
        st.caption("⚠️ 未取得")

    col_s = "✅" if meta.get("summary_done") else "❌"
    col_d = "✅" if meta.get("dynamic_done") else "❌"
    st.caption(f"集計データ {col_s}  Dynamic Events {col_d}")

    st.markdown("---")

    # データ更新
    st.markdown("### 🔄 データ更新")
    update_type = st.radio(
        "取得内容",
        ["集計データ（runs/passes/physical）",
         "Dynamic Events（OBR/PO/PP）",
         "すべて"],
        label_visibility="collapsed",
    )

    if st.button("🚀 更新実行", type="primary", use_container_width=True):
        client = get_client()
        if client:
            prog = st.progress(0, text="開始中...")
            try:
                if "集計" in update_type or "すべて" in update_type:
                    n = fetch_summary(client, season_key, prog)
                    st.success(f"集計データ: {n}試合分取得")
                if "Dynamic" in update_type or "すべて" in update_type:
                    o, p, pp = fetch_dynamic(client, season_key, prog)
                    st.success(f"OBR:{o}行 PO:{p}行 PP:{pp}行")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"エラー: {e}")
            prog.empty()

    st.markdown("---")

    # ページ選択
    st.markdown("### 📑 ページ")
    PAGE = st.radio("", [
        "🏠 ホーム",
        "📋 Post Match Report",
        "🗺️ ランマップ",
        "🔗 パスネットワーク",
        "🔍 スカウティング",
        "📈 時系列トラッカー",
        "💪 フィジカル",
        "📊 リーグ概要",
    ], label_visibility="collapsed")

# ============================================================
#  PAGES
# ============================================================

def warn_no_data(label="集計データ"):
    st.warning(f"⚠️ {label}未取得。サイドバーから「更新実行」してください。")

# -------- HOME --------
def page_home():
    st.title("⚽ SkillCorner Scout Intelligence")
    st.caption(f"現在のシーズン: {SEASONS[season_key]['label']}")
    st.markdown("---")

    # 全シーズン状態一覧
    st.markdown("### 📅 全シーズン データ取得状況")
    rows = []
    for sk, sv in SEASONS.items():
        m = load_meta(sk)
        md = _load(sk, "matches") or []
        rows.append({
            "シーズン": sv["label"],
            "ID": sv["id"],
            "試合数": len(md),
            "集計": "✅" if m.get("summary_done") else "—",
            "Dynamic": "✅" if m.get("dynamic_done") else "—",
            "OBR": len(m.get("obr_done", [])),
            "PP": len(m.get("pp_done", [])),
            "最終更新": m["last_updated"][:10] if m.get("last_updated") else "未取得",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### 📑 機能一覧")
    features = [
        ("📋","Post Match Report","試合別プレス・フィジカル・フェーズレポート"),
        ("🗺️","ランマップ","ピッチ上のOBR座標可視化（選手・種別フィルター）"),
        ("🔗","パスネットワーク","実パス（player_possessions）の接続ネットワーク"),
        ("🔍","スカウティング","複数シーズンのxT・危険ランで全選手比較"),
        ("📈","時系列","試合別指標推移（最大5選手比較）"),
        ("💪","フィジカル","走行距離・スプリント・加速減速"),
        ("📊","リーグ概要","全チームランキング・散布図"),
    ]
    cols = st.columns(3)
    for i,(icon,name,desc) in enumerate(features):
        with cols[i%3]:
            st.markdown(f"""<div style="background:#141c2e;border-radius:8px;padding:14px;
            margin-bottom:10px;border:1px solid rgba(255,255,255,.08)">
            <div style="font-size:22px">{icon}</div>
            <div style="font-weight:700;margin:4px 0">{name}</div>
            <div style="font-size:12px;color:#64748b">{desc}</div>
            </div>""", unsafe_allow_html=True)

    st.info("""
    **毎節の更新手順:**
    1. サイドバーでシーズンを選択
    2. 「集計データ」→「更新実行」（差分のみ・約5分）
    3. Dynamic Eventsは品質基準クリア試合のみ取得可能
    """)

# -------- POST MATCH REPORT --------
def page_post_match():
    st.title("📋 Post Match Report")
    st.caption(SEASONS[season_key]["label"])

    runs = df_runs(season_key)
    if runs.empty: return warn_no_data()

    matches_raw = _load(season_key, "matches") or []
    if not matches_raw: return warn_no_data("試合データ")

    # 試合選択
    opts = {}
    for m in sorted(matches_raw, key=lambda x: x.get("date_time",""), reverse=True):
        h = m["home_team"]["short_name"]
        a = m["away_team"]["short_name"]
        d = m["date_time"][:10]
        opts[f"{d} | {h} vs {a}"] = m["id"]
    sel = st.selectbox("試合を選択", list(opts.keys()))
    mid = opts[sel]

    m_runs = runs[runs["match_id"]==mid] if "match_id" in runs.columns else pd.DataFrame()
    if m_runs.empty: return st.warning("この試合のデータがありません")

    teams = m_runs["team_name"].unique()
    ht = teams[0] if len(teams)>0 else "—"
    at = teams[1] if len(teams)>1 else "—"

    # スコア取得（player_possessionsから）
    pp = df_pp(season_key)
    home_score, away_score = "—", "—"
    if not pp.empty and "match_id" in pp.columns:
        m_pp = pp[pp["match_id"].astype(str)==str(mid)]
        if not m_pp.empty and "team_score" in m_pp.columns and "team_shortname" in m_pp.columns:
            last = m_pp.sort_values("minute_start" if "minute_start" in m_pp.columns else m_pp.columns[0]).iloc[-1]
            ht_pp = m_pp[m_pp["team_shortname"].str.contains(ht.split()[0] if ht!="—" else "X", na=False)]
            at_pp = m_pp[m_pp["team_shortname"].str.contains(at.split()[0] if at!="—" else "X", na=False)]
            if not ht_pp.empty:
                home_score = int(pd.to_numeric(ht_pp["team_score"], errors="coerce").max())
            if not at_pp.empty:
                away_score = int(pd.to_numeric(at_pp["team_score"], errors="coerce").max())

    # ヘッダー
    st.markdown(f"""<div style="background:linear-gradient(135deg,#001a5c,#1a56db);
    border-radius:12px;padding:24px;text-align:center;margin-bottom:20px">
    <div style="font-size:11px;color:rgba(255,255,255,.6)">{SEASONS[season_key]['label']}</div>
    <div style="display:flex;justify-content:center;align-items:center;gap:32px;margin-top:12px">
        <div style="text-align:right;min-width:140px">
            <div style="font-size:20px;font-weight:800;color:white">{ht}</div>
            <div style="font-size:11px;color:rgba(255,255,255,.5)">HOME</div>
        </div>
        <div style="background:rgba(255,255,255,.15);border-radius:10px;padding:12px 24px;text-align:center">
            <div style="font-size:36px;font-weight:900;color:white">{home_score} : {away_score}</div>
        </div>
        <div style="text-align:left;min-width:140px">
            <div style="font-size:20px;font-weight:800;color:white">{at}</div>
            <div style="font-size:11px;color:rgba(255,255,255,.5)">AWAY</div>
        </div>
    </div>
    <div style="font-size:11px;color:rgba(255,255,255,.5);margin-top:8px">{sel.split('|')[0].strip()}</div>
    </div>""", unsafe_allow_html=True)

    def tstats(team):
        t = m_runs[m_runs["team_name"]==team]
        tip  = num(t,"adjusted_min_tip_per_match").sum()
        mins = num(t,"minutes_played_per_match").sum()
        return {
            "poss":   round(tip/mins*100,1) if mins else 0,
            "press":  num(t,"count_pressing").sum(),
            "cp":     num(t,"count_counter_press").sum(),
            "obe":    num(t,"count_on_ball_engagements").sum(),
            "reg":    num(t,"count_direct_regain_on_ball_engagements").sum(),
            "fb":     num(t,"count_force_backward_on_ball_engagements").sum(),
            "hi":     num(t,"count_on_ball_engagements_high_block").sum(),
            "mid":    num(t,"count_on_ball_engagements_medium_block").sum(),
            "lo":     num(t,"count_on_ball_engagements_in_low_block").sum(),
        }

    hs = tstats(ht); as_ = tstats(at)
    tab1, tab2, tab3 = st.tabs(["📊 Match Summary", "🏃 Pressing", "💪 Physical"])

    with tab1:
        tot = (hs["poss"]+as_["poss"]) or 1
        st.markdown("**Possession**")
        c1,c2,c3 = st.columns([2,6,2])
        c1.markdown(f"<div style='text-align:right;font-weight:700;color:#003087'>{hs['poss']}%</div>",unsafe_allow_html=True)
        c2.markdown(f"""<div style='display:flex;height:10px;border-radius:5px;overflow:hidden'>
            <div style='background:#003087;width:{hs["poss"]/tot*100:.0f}%'></div>
            <div style='background:#cc0000;flex:1'></div></div>""",unsafe_allow_html=True)
        c3.markdown(f"<div style='font-weight:700;color:#cc0000'>{as_['poss']}%</div>",unsafe_allow_html=True)
        st.markdown("---")
        for lbl,hv,av in [
            ("Pressing",       hs["press"], as_["press"]),
            ("Counter Press",  hs["cp"],    as_["cp"]),
            ("On-ball Eng",    hs["obe"],   as_["obe"]),
            ("Direct Regains", hs["reg"],   as_["reg"]),
            ("Force Backward", hs["fb"],    as_["fb"]),
        ]:
            c1,c2,c3 = st.columns([2,6,2])
            c1.markdown(f"<div style='text-align:right;font-weight:700;color:#003087'>{hv:.0f}</div>",unsafe_allow_html=True)
            c2.markdown(f"<div style='text-align:center;font-size:11px;color:#64748b'>{lbl}</div>",unsafe_allow_html=True)
            c3.markdown(f"<div style='font-weight:700;color:#cc0000'>{av:.0f}</div>",unsafe_allow_html=True)

    with tab2:
        fig = go.Figure()
        for team,vals,col in [
            (ht, [hs["hi"],hs["mid"],hs["lo"]],"#003087"),
            (at, [as_["hi"],as_["mid"],as_["lo"]],"#cc0000"),
        ]:
            fig.add_bar(name=team, x=["High Block","Mid Block","Low Block"], y=vals, marker_color=col)
        fig.update_layout(barmode="group", height=300,
                         plot_bgcolor="#0c1220", paper_bgcolor="#0c1220", font_color="#e2e8f0")
        st.plotly_chart(fig, use_container_width=True)

    with tab3:
        phy = df_physical(season_key)
        if phy.empty:
            st.warning("フィジカルデータ未取得")
        elif "total_distance_full_all_per_match" in phy.columns:
            for team, col in [(ht,"#003087"),(at,"#cc0000")]:
                t_phy = phy[phy["team_name"]==team] if "team_name" in phy.columns else pd.DataFrame()
                if t_phy.empty: continue
                fig = px.bar(
                    t_phy.sort_values("total_distance_full_all_per_match",ascending=False).head(15),
                    x="player_name", y="total_distance_full_all_per_match",
                    title=f"{team} — 走行距離",
                    color_discrete_sequence=[col],
                )
                fig.update_layout(height=260, plot_bgcolor="#0c1220", paper_bgcolor="#0c1220",
                                 font_color="#e2e8f0", xaxis_tickangle=45)
                st.plotly_chart(fig, use_container_width=True)

# -------- RUN MAP --------
def page_run_map():
    st.title("🗺️ ランマップ")
    st.caption(SEASONS[season_key]["label"])

    obr = df_obr(season_key)
    if obr.empty:
        return warn_no_data("Dynamic Events（OBR）")

    c1,c2,c3 = st.columns(3)
    m_opts = ["全試合"] + sorted(obr["match_id"].astype(str).unique())
    m_sel  = c1.selectbox("試合", m_opts)
    t_opts = ["全チーム"] + sorted(obr["team_shortname"].dropna().unique())
    t_sel  = c2.selectbox("チーム", t_opts)

    tmp = obr.copy()
    if m_sel!="全試合":  tmp = tmp[tmp["match_id"].astype(str)==m_sel]
    if t_sel!="全チーム": tmp = tmp[tmp["team_shortname"]==t_sel]
    p_opts = ["全選手"] + sorted(tmp["player_name"].dropna().unique())
    p_sel  = c3.selectbox("選手", p_opts)

    fc1,fc2,fc3,fc4 = st.columns(4)
    f_d = fc1.checkbox("Dangerous"); f_t = fc2.checkbox("Targeted")
    f_r = fc3.checkbox("Received");  f_s = fc4.checkbox("→Shot")

    subtypes = sorted(obr["event_subtype"].dropna().unique())
    sel_st = st.multiselect("ラン種別", subtypes, default=subtypes,
                             format_func=lambda x: SUBTYPE_JP.get(x,x))

    df = obr.copy()
    if m_sel!="全試合":  df = df[df["match_id"].astype(str)==m_sel]
    if t_sel!="全チーム": df = df[df["team_shortname"]==t_sel]
    if p_sel!="全選手":  df = df[df["player_name"]==p_sel]
    if f_d and "dangerous"  in df.columns: df = df[df["dangerous"]==True]
    if f_t and "targeted"   in df.columns: df = df[df["targeted"]==True]
    if f_r and "received"   in df.columns: df = df[df["received"]==True]
    if f_s and "lead_to_shot" in df.columns: df = df[df["lead_to_shot"]==True]
    if sel_st: df = df[df["event_subtype"].isin(sel_st)]

    k1,k2,k3,k4 = st.columns(4)
    k1.metric("ラン数", f"{len(df):,}")
    k2.metric("Dangerous", int(df["dangerous"].sum()) if "dangerous" in df.columns else "—")
    k3.metric("受け取り",  int((df["received"]==True).sum()) if "received" in df.columns else "—")
    k4.metric("→Shot",    int(df["lead_to_shot"].sum()) if "lead_to_shot" in df.columns else "—")

    sample = df.sample(min(1500,len(df)), random_state=42) if len(df)>1500 else df
    fig = go.Figure()
    for s in PITCH_SHAPES: fig.add_shape(**s)

    for st_name in (sel_st or subtypes):
        sub = sample[sample["event_subtype"]==st_name].dropna(subset=["x_start","y_start","x_end","y_end"])
        if sub.empty: continue
        color = SUBTYPE_COLORS.get(st_name, "#64748b")
        for _, row in sub.iterrows():
            is_d = bool(row.get("dangerous", False))
            fig.add_annotation(
                x=row["x_end"],  y=row["y_end"],
                ax=row["x_start"], ay=row["y_start"],
                xref="x",yref="y",axref="x",ayref="y",
                arrowhead=2, arrowwidth=1.5 if is_d else 0.8,
                arrowcolor="#ff4444" if is_d else color,
                opacity=0.9 if is_d else 0.4, showarrow=True,
            )

    fig.update_layout(height=560, showlegend=False, **PITCH_LAYOUT)
    if len(sample) < len(df):
        st.caption(f"⚡ {len(sample):,}件表示（全{len(df):,}件中）")
    st.plotly_chart(fig, use_container_width=True)

# -------- PASS NETWORK --------
def page_pass_network():
    st.title("🔗 パスネットワーク")
    st.caption(SEASONS[season_key]["label"] + " — 実パスデータ（player_possessions）")

    pp = df_pp(season_key)
    if pp.empty: return warn_no_data("Dynamic Events（PP）")

    passes = pp[(pp["end_type"]=="pass") & (pp["player_targeted_name"].notna())].copy() \
        if "end_type" in pp.columns and "player_targeted_name" in pp.columns else pd.DataFrame()
    if passes.empty: return st.warning("パスデータが見つかりません")

    c1,c2,c3 = st.columns(3)
    teams = sorted(passes["team_shortname"].dropna().unique())
    def_i = next((i for i,t in enumerate(teams) if "Yokohama" in t), 0)
    t_sel = c1.selectbox("チーム", teams, index=def_i)

    m_opts = ["全試合（平均）"] + sorted(
        passes[passes["team_shortname"]==t_sel]["match_id"].astype(str).unique())
    m_sel = c2.selectbox("試合", m_opts)
    f_t   = c3.checkbox("Targeted only", value=True)

    df = passes[passes["team_shortname"]==t_sel].copy()
    if m_sel!="全試合（平均）": df = df[df["match_id"].astype(str)==m_sel]
    if f_t and "targeted" in df.columns: df = df[df["targeted"]==True]
    if df.empty: return st.warning("条件に一致するデータがありません")

    # ノード
    nodes = df.groupby("player_targeted_name").agg(
        x=("player_targeted_x_reception","mean"),
        y=("player_targeted_y_reception","mean"),
        received=("player_targeted_name","count"),
    ).reset_index().rename(columns={"player_targeted_name":"player"})
    nodes = nodes.dropna(subset=["x","y"])

    # エッジ
    edges = df.groupby(["player_name","player_targeted_name"]).agg(
        count=("match_id","count"),
        xt=("player_targeted_xthreat","sum"),
        success=("pass_outcome", lambda x: (x=="successful").sum() if "pass_outcome" in df.columns else 0),
    ).reset_index().rename(columns={"player_name":"passer","player_targeted_name":"receiver"})
    edges["success_rate"] = (edges["success"]/edges["count"]*100).round(1)
    edges = edges[edges["count"]>=2].sort_values("count",ascending=False).head(40)

    max_t = nodes["received"].max() or 1
    max_e = edges["count"].max()    or 1
    node_map = {r["player"]:r for _,r in nodes.iterrows()}

    fig = go.Figure()
    for s in PITCH_SHAPES: fig.add_shape(**s)

    for _,e in edges.iterrows():
        fn = node_map.get(e["passer"]); tn = node_map.get(e["receiver"])
        if fn is None or tn is None: continue
        sr = (e["success_rate"] or 0)/100
        r  = int(255*(1-sr)); g = int(200*sr)
        fig.add_trace(go.Scatter(
            x=[fn["x"],tn["x"],None], y=[fn["y"],tn["y"],None],
            mode="lines",
            line=dict(color=f"rgba({r},{g},80,0.5)", width=e["count"]/max_e*5),
            showlegend=False, hoverinfo="skip",
        ))

    node_sz = [8 + n["received"]/max_t*22 for _,n in nodes.iterrows()]
    fig.add_trace(go.Scatter(
        x=nodes["x"], y=nodes["y"],
        mode="markers+text",
        marker=dict(size=node_sz, color="rgba(0,212,255,0.7)",
                   line=dict(color="#00d4ff",width=1.5)),
        text=nodes["player"].str.split().str[-1],
        textposition="top center", textfont=dict(size=9,color="white"),
        hovertext=[f"{r['player']}<br>受取:{int(r['received'])}" for _,r in nodes.iterrows()],
        hoverinfo="text", showlegend=False,
    ))

    fig.update_layout(height=540, **PITCH_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)

    col1,col2 = st.columns(2)
    with col1:
        st.markdown("##### Top接続ペア")
        d = edges.head(10)[["passer","receiver","count","success_rate","xt"]].copy()
        d.columns = ["パサー","受け手","回数","成功率%","xT"]
        d["xT"] = d["xT"].round(3)
        st.dataframe(d, use_container_width=True, hide_index=True)
    with col2:
        st.markdown("##### 最多ターゲット選手")
        d2 = nodes.sort_values("received",ascending=False).head(10)[["player","received"]].copy()
        d2.columns = ["選手","受取回数"]
        st.dataframe(d2, use_container_width=True, hide_index=True)

# -------- SCOUTING --------
def page_scouting():
    st.title("🔍 スカウティング")

    # 複数シーズン比較
    avail = [sk for sk in SEASONS if not df_runs(sk).empty]
    if not avail: return warn_no_data()

    c1,c2 = st.columns([3,1])
    compare_seasons = c1.multiselect(
        "比較シーズン（複数選択可）", avail,
        default=[s for s in [season_key] if s in avail],
    )
    if not compare_seasons: return st.info("シーズンを選択してください")

    M_COLS = ["runs_threat_per_match","count_dangerous_runs_per_match",
              "runs_targeted_threat_per_match","count_runs_per_match",
              "count_opportunities_to_pass_to_runs_per_match","pass_completion_ratio_to_runs"]
    G_COLS = ["player_id","player_name","team_name","position","group","player_birthdate"]

    all_dfs = []
    for sk in compare_seasons:
        df = df_runs(sk)
        if df.empty: continue
        g = [c for c in G_COLS if c in df.columns]
        m = [c for c in M_COLS if c in df.columns]
        tmp = df.groupby(g)[m].mean().reset_index()
        tmp["season"] = sk
        all_dfs.append(tmp)

    if not all_dfs: return st.warning("データがありません")
    players = pd.concat(all_dfs, ignore_index=True)

    if "player_birthdate" in players.columns:
        def age(bd):
            try:
                b=date.fromisoformat(str(bd)[:10]); t=date.today()
                return t.year-b.year-((t.month,t.day)<(b.month,b.day))
            except: return 0
        players["age"] = players["player_birthdate"].apply(age)

    # フィルター
    fc1,fc2,fc3,fc4,fc5 = st.columns(5)
    t_sel = fc1.selectbox("チーム", ["全チーム"]+sorted(players["team_name"].dropna().unique()))
    p_sel = fc2.selectbox("ポジション", ["全ポジション"]+(sorted(players["group"].dropna().unique()) if "group" in players.columns else []))
    a_sel = fc3.selectbox("年齢", ["全年齢","U23","U27","27歳以上"])
    s_sel = fc4.selectbox("シーズン", ["全シーズン"]+compare_seasons)
    x_col = fc5.selectbox("ソート指標", [c for c in M_COLS if c in players.columns], format_func=lambda x:x.replace("_"," "))

    df = players.copy()
    if t_sel!="全チーム":   df = df[df["team_name"]==t_sel]
    if p_sel!="全ポジション" and "group" in df.columns: df = df[df["group"]==p_sel]
    if s_sel!="全シーズン": df = df[df["season"]==s_sel]
    if "age" in df.columns:
        if a_sel=="U23":   df = df[(df["age"]>0)&(df["age"]<23)]
        elif a_sel=="U27": df = df[(df["age"]>0)&(df["age"]<27)]
        elif a_sel=="27歳以上": df = df[df["age"]>=27]

    df = df.sort_values(x_col, ascending=False).reset_index(drop=True)
    st.caption(f"{len(df)}選手")

    # 散布図
    if len(df)>0 and "runs_threat_per_match" in df.columns and "count_dangerous_runs_per_match" in df.columns:
        fig = px.scatter(
            df.head(300), x="count_dangerous_runs_per_match", y="runs_threat_per_match",
            hover_name="player_name", color="season" if s_sel=="全シーズン" else "team_name",
            symbol="season" if s_sel=="全シーズン" else None,
            labels={"count_dangerous_runs_per_match":"危険ラン/試合","runs_threat_per_match":"ランxT/試合"},
        )
        yfc = df[df["team_name"].str.contains("Yokohama",na=False)]
        if len(yfc):
            fig.add_scatter(
                x=yfc["count_dangerous_runs_per_match"], y=yfc["runs_threat_per_match"],
                mode="markers+text", text=yfc["player_name"].str.split().str[-1],
                textposition="top center",
                marker=dict(color="#e8002d",size=12,symbol="star"),
                name="横浜FC", textfont=dict(size=9),
            )
        fig.update_layout(height=420, plot_bgcolor="#0c1220", paper_bgcolor="#0c1220", font_color="#e2e8f0")
        st.plotly_chart(fig, use_container_width=True)

    show = [c for c in ["player_name","team_name","season","age"]+[c for c in M_COLS if c in df.columns][:5] if c in df.columns]
    st.dataframe(
        df[show].head(100).style.format({c:"{:.3f}" for c in M_COLS if c in show}),
        use_container_width=True, height=380,
    )

# -------- TIMESERIES --------
def page_timeseries():
    st.title("📈 時系列トラッカー")
    st.caption(SEASONS[season_key]["label"])

    runs = df_runs(season_key)
    if runs.empty: return warn_no_data()
    if "match_date" not in runs.columns: return st.warning("試合日データがありません")

    COLORS = ["#00d4ff","#f97316","#a855f7","#22c55e","#f43f5e"]
    M_COLS = [c for c in ["runs_threat_per_match","count_dangerous_runs_per_match",
                           "runs_targeted_threat_per_match","count_runs_per_match",
                           "count_opportunities_to_pass_to_runs_per_match",
                           "pass_completion_ratio_to_runs"] if c in runs.columns]

    c1,c2 = st.columns([3,1])
    metric  = c1.selectbox("指標", M_COLS, format_func=lambda x:x.replace("_"," "))
    t_filt  = c2.selectbox("チーム絞り込み", ["全チーム"]+sorted(runs["team_name"].dropna().unique()))

    df = runs.copy()
    if t_filt!="全チーム": df = df[df["team_name"]==t_filt]

    all_p   = sorted(df["player_name"].dropna().unique())
    defaults = [p for p in all_p if p in ["Lukian Araújo de Almeida","João Paulo Queiroz de Moraes","Leo Takae"]]
    selected = st.multiselect("選手（最大5人）", all_p, default=defaults[:3], max_selections=5)
    if not selected: return st.info("選手を選択してください")

    fig = go.Figure()
    for i, player in enumerate(selected):
        p = df[df["player_name"]==player].copy()
        if metric not in p.columns: continue
        p[metric] = pd.to_numeric(p[metric], errors="coerce")
        p = p.dropna(subset=["match_date",metric]).sort_values("match_date")
        if p.empty: continue
        fig.add_trace(go.Scatter(
            x=p["match_date"], y=p[metric], name=player,
            mode="lines+markers",
            line=dict(color=COLORS[i], width=2.5),
            marker=dict(size=8, color=COLORS[i]),
        ))

    fig.update_layout(
        height=400, title=metric.replace("_"," "),
        plot_bgcolor="#0c1220", paper_bgcolor="#0c1220", font_color="#e2e8f0",
        legend=dict(orientation="h", y=-0.2),
        xaxis=dict(gridcolor="rgba(255,255,255,.05)"),
        yaxis=dict(gridcolor="rgba(255,255,255,.05)"),
    )
    st.plotly_chart(fig, use_container_width=True)

# -------- PHYSICAL --------
def page_physical():
    st.title("💪 フィジカルデータ")
    st.caption(SEASONS[season_key]["label"])

    phy = df_physical(season_key)
    if phy.empty: return warn_no_data("フィジカル")

    M_COLS = {c:c.replace("_"," ") for c in [
        "total_distance_full_all_per_match","hsr_distance_full_all_per_match",
        "sprint_distance_full_all_per_match","sprint_count_full_all_per_match",
        "highaccel_count_full_all_per_match","highdecel_count_full_all_per_match",
    ] if c in phy.columns}
    if not M_COLS: return st.warning("フィジカル指標の列がありません")

    c1,c2 = st.columns(2)
    t_sel = c1.selectbox("チーム", ["全チーム"]+sorted(phy["team_name"].dropna().unique()) if "team_name" in phy.columns else ["全チーム"])
    m_sel = c2.selectbox("指標", list(M_COLS.keys()), format_func=lambda x:M_COLS[x])

    df = phy.copy()
    if t_sel!="全チーム" and "team_name" in df.columns: df = df[df["team_name"]==t_sel]
    df[m_sel] = pd.to_numeric(df[m_sel], errors="coerce")

    fig = px.bar(
        df.sort_values(m_sel, ascending=False).head(20),
        x="player_name", y=m_sel, title=f"{M_COLS[m_sel]} Top20",
        color="team_name" if "team_name" in df.columns else None,
    )
    fig.update_layout(height=400, plot_bgcolor="#0c1220", paper_bgcolor="#0c1220",
                     font_color="#e2e8f0", xaxis_tickangle=45, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    if "team_name" in phy.columns:
        st.markdown("### チーム比較")
        ta = phy.groupby("team_name")[list(M_COLS.keys())].mean().reset_index()
        st.dataframe(
            ta.sort_values(m_sel, ascending=False).style.format({c:"{:.1f}" for c in M_COLS if c in ta.columns}),
            use_container_width=True,
        )

# -------- LEAGUE --------
def page_league():
    st.title("📊 リーグ概要")
    st.caption(SEASONS[season_key]["label"])

    runs = df_runs(season_key)
    if runs.empty: return warn_no_data()

    M_COLS = [c for c in ["runs_threat_per_match","count_dangerous_runs_per_match","count_runs_per_match"] if c in runs.columns]
    team_df = runs.groupby("team_name")[M_COLS].mean().reset_index()

    if "adjusted_min_tip_per_match" in runs.columns and "minutes_played_per_match" in runs.columns:
        tip = runs.groupby("team_name").agg(
            tip=("adjusted_min_tip_per_match","sum"),
            mins=("minutes_played_per_match","sum"),
        ).reset_index()
        tip["poss_pct"] = (tip["tip"]/tip["mins"]*100).round(1)
        team_df = team_df.merge(tip[["team_name","poss_pct"]], on="team_name", how="left")

    team_df["is_yfc"] = team_df["team_name"].str.contains("Yokohama FC", na=False)
    CMAP = {True:"#e8002d", False:"#1e3a5f"}
    LY = dict(height=680, showlegend=False,
              plot_bgcolor="#0c1220", paper_bgcolor="#0c1220", font_color="#e2e8f0")

    tab1,tab2,tab3 = st.tabs(["ランxT","ポゼッション","散布図"])

    with tab1:
        if "runs_threat_per_match" in team_df.columns:
            fig = px.bar(
                team_df.sort_values("runs_threat_per_match", ascending=True),
                x="runs_threat_per_match", y="team_name", orientation="h",
                color="is_yfc", color_discrete_map=CMAP,
            )
            fig.update_layout(**LY, yaxis_title="", xaxis_title="ランxT/試合")
            st.plotly_chart(fig, use_container_width=True)

    with tab2:
        if "poss_pct" in team_df.columns and team_df["poss_pct"].sum()>0:
            fig = px.bar(
                team_df.sort_values("poss_pct", ascending=True),
                x="poss_pct", y="team_name", orientation="h",
                color="is_yfc", color_discrete_map=CMAP,
            )
            fig.update_layout(**LY)
            st.plotly_chart(fig, use_container_width=True)

    with tab3:
        if "runs_threat_per_match" in team_df.columns and "poss_pct" in team_df.columns:
            fig = px.scatter(
                team_df, x="poss_pct", y="runs_threat_per_match",
                text="team_name", color="is_yfc", color_discrete_map=CMAP,
                labels={"poss_pct":"ポゼッション%","runs_threat_per_match":"ランxT/試合"},
            )
            fig.update_traces(textposition="top center", textfont_size=8)
            fig.update_layout(height=500, showlegend=False,
                             plot_bgcolor="#0c1220", paper_bgcolor="#0c1220", font_color="#e2e8f0")
            st.plotly_chart(fig, use_container_width=True)

# ============================================================
#  ROUTER
# ============================================================
{
    "🏠 ホーム":           page_home,
    "📋 Post Match Report": page_post_match,
    "🗺️ ランマップ":        page_run_map,
    "🔗 パスネットワーク":  page_pass_network,
    "🔍 スカウティング":    page_scouting,
    "📈 時系列トラッカー":  page_timeseries,
    "💪 フィジカル":        page_physical,
    "📊 リーグ概要":        page_league,
}.get(PAGE, page_home)()

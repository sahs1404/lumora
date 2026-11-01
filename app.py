"""
Lumora - plan a mini-grid before you build it.

Run locally:   pip install -r requirements.txt
               streamlit run app.py

Reads:
  data/villages.json             features, CV outputs, forecast, growth, drivers per village
  data/buildings/<id>.csv        optional: CV building points (columns: lat, lon, type = home|business)
  data/overlays/<id>.png         optional: CV overlay image
  model/sizing_optimizer.py      the optimizer, run live (results are cached per input)
"""

import json
import math
from pathlib import Path

import altair as alt
import folium
import pandas as pd
import streamlit as st
from folium import plugins
from streamlit_folium import st_folium

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="Lumora · plan a mini-grid", page_icon="🌅", layout="wide",
                   initial_sidebar_state="collapsed")

STEPS = [
    ("See the village", "village"),
    ("Forecast demand", "demand"),
    ("Find the best system", "system"),
    ("Test a decision", "decide"),
]
st.session_state.setdefault("step", 0)
st.session_state.setdefault("dark", False)

# ----------------------------------------------------------------------------
# Theme
# ----------------------------------------------------------------------------
DAWN, TEAL, CORAL = "#F2A93B", "#1F8A70", "#D1495B"
LIGHT = dict(bg="#F7F8FB", card="#FFFFFF", ink="#14213D", muted="#5B6478", line="#E3E8F0", soft="#FBFCFE",
             good_bg="#E6F4EF", good_ink="#145C4B", bad_bg="#FBE9EC", bad_ink="#8E2534", teal=TEAL, coral=CORAL)
DARK = dict(bg="#0D1526", card="#152038", ink="#EEF2FA", muted="#A3AEC6", line="#26334F", soft="#18243F",
            good_bg="#123A33", good_ink="#9FE3CF", bad_bg="#3D1A24", bad_ink="#F5B3BF", teal="#3CC4A0", coral="#F07587")


def css(t):
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
:root {{ --bg:{t['bg']}; --card:{t['card']}; --ink:{t['ink']}; --muted:{t['muted']}; --line:{t['line']}; --soft:{t['soft']}; }}
.stApp {{ background: var(--bg); color: var(--ink); }}
html, body, .stApp, .stMarkdown, p, li, label, input, button, textarea {{ font-family:'IBM Plex Sans', system-ui, sans-serif; }}
.stApp p, .stApp li, .stApp label, .stApp span {{ color: var(--ink); }}
h1, h2, h3, h4, .lm-h {{ font-family:'Sora', system-ui, sans-serif !important; color: var(--ink) !important; letter-spacing:-0.01em; }}
header[data-testid="stHeader"], footer, #MainMenu, [data-testid="stToolbar"], [data-testid="stSidebar"],
[data-testid="collapsedControl"], .stDeployButton {{ display:none !important; }}
.block-container {{ padding-top:1.1rem; padding-bottom:4rem; max-width:1180px; }}

/* inputs in both themes */
[data-baseweb="select"] > div {{ background: var(--card) !important; border-color: var(--line) !important; color: var(--ink) !important; }}
[data-baseweb="select"] svg {{ fill: var(--muted); }}
[data-baseweb="popover"] li, [data-baseweb="menu"] {{ background: var(--card) !important; color: var(--ink) !important; }}
[data-testid="stExpander"] details {{ background: var(--card); border-color: var(--line) !important; }}
[data-testid="stExpander"] summary p {{ color: var(--ink); }}
.stApp [data-testid="stCaptionContainer"] p {{ color: var(--muted); }}

/* brand */
.lm-brand {{ display:flex; align-items:center; gap:.6rem; font-family:'Sora',sans-serif; font-weight:700; font-size:1.45rem; color:var(--ink); padding-top:.3rem; }}
.lm-brand .sun {{ width:26px; height:26px; border-radius:50%; background: radial-gradient(circle at 50% 70%, {DAWN} 0 45%, transparent 46%); }}
.lm-brand small {{ font-family:'IBM Plex Sans',sans-serif; font-weight:400; font-size:.9rem; color:var(--muted); margin-left:.3rem; }}

/* hero */
.lm-hero {{ position:relative; overflow:hidden; border-radius:18px; padding:2rem 2.4rem 1.8rem; color:#fff; margin:.7rem 0 1.2rem;
           background: linear-gradient(180deg, #14213D 0%, #1D2F55 58%, #3B3F63 78%, #C9803A 96%, {DAWN} 100%); }}
.lm-hero > * {{ position:relative; z-index:1; }}
.lm-hero::after {{ content:''; position:absolute; right:7%; bottom:-150px; width:300px; height:300px; border-radius:50%;
  background: radial-gradient(circle, #FFD58A 0%, {DAWN} 45%, rgba(242,169,59,0) 70%); }}
.lm-hero .place {{ font-size:1rem; opacity:.82; margin-bottom:.35rem; color:#fff; }}
.lm-hero .rec {{ font-family:'Sora',sans-serif; font-weight:700; font-size:2.2rem; line-height:1.15; max-width:24ch; color:#fff; }}
.lm-hero .rec span {{ color:{DAWN}; white-space:nowrap; }}
.lm-hero .facts {{ display:flex; gap:2.6rem; margin-top:1.3rem; flex-wrap:wrap; }}
.lm-hero .fact {{ font-size:.92rem; color:#fff; opacity:.92; }}
.lm-hero .fact b {{ display:block; font-family:'Sora',sans-serif; font-size:1.55rem; font-weight:600; color:#fff; }}

/* stepper */
.st-key-stepper {{ background: var(--card); border:1px solid var(--line); border-radius:14px; padding:.55rem; margin-bottom:1.2rem; }}
.st-key-stepper button {{ width:100%; border-radius:10px !important; border:none !important; padding:.65rem .5rem !important;
  background: transparent !important; justify-content:flex-start; }}
.st-key-stepper button p {{ font-family:'Sora',sans-serif; font-weight:600; font-size:.98rem; color: var(--muted) !important; }}
.st-key-stepper button:hover {{ background: var(--soft) !important; }}
.st-key-stepper button[kind="primary"] {{ background: {DAWN} !important; }}
.st-key-stepper button[kind="primary"] p {{ color:#14213D !important; }}

/* step header */
.lm-step {{ display:flex; gap:1.2rem; align-items:flex-start; margin:.2rem 0 1.2rem; }}
.lm-step .n {{ flex:none; width:44px; height:44px; border-radius:50%; background:{DAWN}; color:#14213D; display:flex; align-items:center;
  justify-content:center; font-family:'Sora',sans-serif; font-weight:700; font-size:1.2rem; }}
.lm-step h2 {{ margin:0; font-size:1.55rem; }}
.lm-step .of {{ color:var(--muted); font-size:.9rem; }}
.lm-guide {{ background: var(--card); border:1px solid var(--line); border-left:4px solid {DAWN}; border-radius:10px;
  padding:.85rem 1.1rem; margin-bottom:1.3rem; color:var(--ink); font-size:.98rem; line-height:1.55; }}
.lm-guide b {{ font-family:'Sora',sans-serif; }}

/* blocks */
.lm-stat {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:1rem 1.1rem; height:100%; }}
.lm-stat .k {{ color:var(--muted); font-size:.88rem; }}
.lm-stat .v {{ font-family:'Sora',sans-serif; font-weight:600; font-size:1.55rem; color:var(--ink); margin-top:.15rem; }}
.lm-stat .s {{ color:var(--muted); font-size:.82rem; margin-top:.2rem; }}
.lm-stat.good .v {{ color:{t['teal']}; }}
.lm-design {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:1.3rem 1.4rem; }}
.lm-design.win {{ border:2px solid {t['teal']}; box-shadow:0 6px 24px rgba(31,138,112,.14); }}
.lm-design h3 {{ font-size:1.12rem; margin:0 0 .2rem; }}
.lm-design .tag {{ display:inline-block; font-size:.78rem; font-weight:600; color:#fff; background:{t['teal']}; border-radius:999px; padding:.1rem .6rem; margin-bottom:.5rem; }}
.lm-design .tag.grey {{ background:#5B6478; }}
.lm-design .kit {{ color:var(--muted); font-size:.92rem; margin-bottom:.9rem; }}
.lm-row {{ display:flex; justify-content:space-between; padding:.55rem 0; border-top:1px solid var(--line); font-size:.97rem; color:var(--ink); }}
.lm-row b {{ font-family:'Sora',sans-serif; color:var(--ink); }}
.lm-delta {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); }}
.lm-delta th, .lm-delta td {{ padding:.75rem 1rem; text-align:left; border-bottom:1px solid var(--line); font-size:.97rem; color:var(--ink); }}
.lm-delta th {{ color:var(--muted); font-weight:500; background:var(--soft); }}
.lm-delta td.up {{ color:{t['teal']}; font-weight:600; }} .lm-delta td.down {{ color:{t['coral']}; font-weight:600; }} .lm-delta td.flat {{ color:var(--muted); }} .lm-delta td.size {{ color:var(--ink); font-weight:600; }}
.lm-verdict {{ border-radius:12px; padding:1rem 1.2rem; margin-top:1rem; font-size:1.02rem; }}
.lm-verdict.good {{ background:{t['good_bg']}; color:{t['good_ink']}; }} .lm-verdict.bad {{ background:{t['bad_bg']}; color:{t['bad_ink']}; }}
.lm-verdict b {{ color:inherit; }}
.lm-memo {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:1.8rem 2.1rem; max-width:780px; line-height:1.6; }}
.lm-memo h3 {{ margin-top:0; }}
.lm-memo p, .lm-memo strong, .lm-memo em {{ color:var(--ink); }}
.lm-legend {{ display:flex; gap:1.2rem; flex-wrap:wrap; font-size:.9rem; color:var(--muted); margin-top:.5rem; }}
.lm-legend i {{ display:inline-block; width:11px; height:11px; border-radius:50%; margin-right:.4rem; vertical-align:-1px; }}

/* nav buttons */
.st-key-nav button {{ border-radius:10px !important; padding:.6rem 1.2rem !important; }}
.st-key-nav button[kind="primary"] {{ background:{DAWN} !important; border:none !important; }}
.st-key-nav button[kind="primary"] p {{ color:#14213D !important; font-weight:600; }}
.st-key-nav button[kind="secondary"] {{ background:var(--card) !important; border:1px solid var(--line) !important; }}
.stDownloadButton button {{ background:{DAWN} !important; border:none !important; border-radius:10px !important; }}
.stDownloadButton button p {{ color:#14213D !important; font-weight:600; }}
[data-testid="stButtonGroup"] button {{ background:var(--card) !important; border:1px solid var(--line) !important; padding:.45rem .9rem; }}
[data-testid="stButtonGroup"] button p {{ color:var(--ink) !important; }}
[data-testid="stButtonGroup"] button[aria-checked="true"] {{ background:{DAWN} !important; border-color:{DAWN} !important; }}
[data-testid="stButtonGroup"] button[aria-checked="true"] p {{ color:#14213D !important; font-weight:600; }}
[data-testid="stSelectbox"] [role="group"] {{ background:var(--card) !important; border:1px solid var(--line) !important; border-radius:10px; }}
[data-testid="stSelectbox"] input {{ background:transparent !important; color:var(--ink) !important; -webkit-text-fill-color:var(--ink); }}
[data-testid="stSelectbox"] button svg {{ color:var(--muted); }}
[role="listbox"], [role="listbox"] [role="option"] {{ background:var(--card) !important; color:var(--ink) !important; }}
iframe {{ border-radius:14px; }}
</style>"""


# ----------------------------------------------------------------------------
# Model (live)
# ----------------------------------------------------------------------------
import sys
from dataclasses import replace as dc_replace

sys.path.insert(0, str(ROOT / "model"))
import sizing_optimizer as so  # noqa: E402

BASE_COSTS, BASE_TECH = so.Costs(), so.Tech()
DEFAULT_GROWTH = [1.0, 1.3, 1.55, 1.7]


@st.cache_data(show_spinner=False)
def plan_cached(n_cust, kwh, biz, mills, cold, diesel_price, batt_cost, solar_factor, target):
    costs = dc_replace(BASE_COSTS, fuel_price_per_l=diesel_price, batt_capex_per_kwh=batt_cost)
    tech = dc_replace(BASE_TECH, solar_yield_kwh_per_kwp_day=BASE_TECH.solar_yield_kwh_per_kwp_day * solar_factor)
    extra = so.mill_load_kw(mills) + so.cold_room_load_kw(cold) if (mills or cold) else None
    return so.plan_to_target(n_cust, kwh, biz, extra, costs, tech, target)


@st.cache_data(show_spinner=False)
def stress_cached(row_items, n_cust, kwh, biz, mills, cold, diesel_price, batt_cost, solar_factor):
    costs = dc_replace(BASE_COSTS, fuel_price_per_l=diesel_price, batt_capex_per_kwh=batt_cost)
    tech = dc_replace(BASE_TECH, solar_yield_kwh_per_kwp_day=BASE_TECH.solar_yield_kwh_per_kwp_day * solar_factor)
    extra = so.mill_load_kw(mills) + so.cold_room_load_kw(cold) if (mills or cold) else None
    return so.stress_test(dict(row_items), n_cust, kwh, biz, extra, costs, tech)


# ----------------------------------------------------------------------------
# Data and helpers
# ----------------------------------------------------------------------------
@st.cache_data
def load_villages():
    raw = json.loads((ROOT / "data" / "villages.json").read_text())
    return {v["id"]: v for v in raw["villages"]}


@st.cache_data
def load_buildings(village_id):
    p = ROOT / "data" / "buildings" / f"{village_id}.csv"
    return pd.read_csv(p) if p.exists() else None


def cents(x): return f"{x * 100:.1f}¢"


def ci_pct(r):
    lo, hi = (float(x) for x in r["reliable_95ci"].split("-"))
    return f"{lo:.0%}–{hi:.0%}"


def stat(col, label, value, sub="", tone=""):
    col.markdown(f'<div class="lm-stat {tone}"><div class="k">{label}</div><div class="v">{value}</div>'
                 f'<div class="s">{sub}</div></div>', unsafe_allow_html=True)


def step_header(i, guide):
    st.markdown(f'<div class="lm-step"><div class="n">{i + 1}</div><div><div class="of">Step {i + 1} of {len(STEPS)}</div>'
                f'<h2>{STEPS[i][0]}</h2></div></div><div class="lm-guide">{guide}</div>', unsafe_allow_html=True)


def go(i):
    st.session_state.step = i


def nav(i):
    st.write("")
    with st.container(key="nav"):
        left, _, right = st.columns([1, 2, 1.3])
        if i > 0:
            left.button(f"Back: {STEPS[i - 1][0]}", on_click=go, args=(i - 1,), width="stretch")
        if i < len(STEPS) - 1:
            right.button(f"Next: {STEPS[i + 1][0]}", on_click=go, args=(i + 1,), type="primary", width="stretch")


def chart_style(ch, t):
    return (ch.configure(background="transparent").configure_view(stroke=None)
            .configure_axis(grid=True, gridColor=t["line"], domain=False, labelColor=t["muted"], titleColor=t["muted"],
                            labelFont="IBM Plex Sans", titleFont="IBM Plex Sans")
            .configure_legend(labelColor=t["muted"], labelFont="IBM Plex Sans"))


def bind(key):
    """Widgets on hidden steps lose their state in Streamlit. Keep the value in `key`,
    give the widget its own key `w_<key>`, and copy back on change."""
    wk = f"w_{key}"
    st.session_state[wk] = st.session_state[key]
    return dict(key=wk, on_change=_copy_back, args=(key, wk))


def _copy_back(key, wk):
    val = st.session_state.get(wk)
    if val is not None:
        st.session_state[key] = val


villages = load_villages()
CUSTOM = "__custom__"
SPREADS = {"Narrow": (0.7, 1.4), "Typical": (0.5, 2.0), "Wide": (0.35, 3.0)}

# defaults for custom-site inputs (widgets further down use these keys)
for k, val in {"c_lat": -1.2833, "c_lon": 36.8167, "c_name": "My site", "c_cust": 300, "c_biz": 25,
               "c_p50": 12.0, "c_spread": "Typical", "target": "95%"}.items():
    st.session_state.setdefault(k, val)

# ----------------------------------------------------------------------------
# Top bar
# ----------------------------------------------------------------------------
tb_l, tb_m, tb_r = st.columns([2.1, 1.2, 0.55])
with tb_r:
    st.toggle("Dark", key="dark")
T = DARK if st.session_state.dark else LIGHT
st.markdown(css(T), unsafe_allow_html=True)
with tb_l:
    st.markdown('<div class="lm-brand"><div class="sun"></div>Lumora<small>Plan a mini-grid before you build it</small></div>',
                unsafe_allow_html=True)
with tb_m:
    vid = st.selectbox("Site", list(villages) + [CUSTOM], label_visibility="collapsed", key="site",
                       format_func=lambda k: "Custom site: enter coordinates" if k == CUSTOM
                       else f"{villages[k]['name']}, {villages[k]['country']}")

# ----------------------------------------------------------------------------
# Build the site description (preset village or custom coordinates)
# ----------------------------------------------------------------------------
is_custom = vid == CUSTOM
if is_custom:
    lo, hi = SPREADS[st.session_state.c_spread]
    p50 = float(st.session_state.c_p50)
    site = dict(id="custom", name=st.session_state.c_name or "My site", country="custom coordinates",
                lat=float(st.session_state.c_lat), lon=float(st.session_state.c_lon), features=None,
                forecast_kwh_customer_month={"p10": p50 * lo, "p50": p50, "p90": p50 * hi},
                business_share_of_load=st.session_state.c_biz / 100, growth_multiplier_by_year=DEFAULT_GROWTH,
                drivers=None, n_cust=int(st.session_state.c_cust))
else:
    site = dict(villages[vid])
    site["n_cust"] = site["features"]["est_customers"]

if not st.session_state.get("target"):
    st.session_state.target = "95%"
fc, growth = site["forecast_kwh_customer_month"], site["growth_multiplier_by_year"]
KWH = (fc["p10"], fc["p50"], fc["p90"])
TARGET = {"90%": 0.90, "95%": 0.95, "99%": 0.99}[st.session_state.target]
BASE_ARGS = (site["n_cust"], KWH, site["business_share_of_load"], 0, 0,
             BASE_COSTS.fuel_price_per_l, BASE_COSTS.batt_capex_per_kwh, 1.0, TARGET)

with st.spinner("Sizing the system across hundreds of demand scenarios…"):
    det, lum = plan_cached(*BASE_ARGS)
N_TEST = 500

# ----------------------------------------------------------------------------
# Hero
# ----------------------------------------------------------------------------
st.markdown(f"""
<div class="lm-hero">
  <div class="place">{site['name']}, {site['country']}. About {site['n_cust']:,} future customers</div>
  <div class="rec">Build <span>{lum['pv_kw']:.0f} kW</span> of solar, a <span>{lum['batt_kwh']:.0f} kWh</span> battery
  and {lum['diesel_kw']:.0f} kW diesel backup</div>
  <div class="facts">
    <div class="fact"><b>{lum['reliable_share']:.0%}</b>of days with reliable power (target {st.session_state.target})</div>
    <div class="fact"><b>{cents(lum['cost_of_power_usd_kwh'])}</b>cost per kWh</div>
    <div class="fact"><b>{fc['p50']:.0f} kWh</b>expected use per customer each month</div>
  </div>
</div>""", unsafe_allow_html=True)

cur = st.session_state.step
with st.container(key="stepper"):
    cols = st.columns(len(STEPS))
    for i, (name, _) in enumerate(STEPS):
        mark = "✓" if i < cur else str(i + 1)
        cols[i].button(f"{mark}  {name}", key=f"step_{i}", on_click=go, args=(i,),
                       type="primary" if i == cur else "secondary", width="stretch")


# ----------------------------------------------------------------------------
# Step 1: village + map
# ----------------------------------------------------------------------------
def village_map(site, dark):
    m = folium.Map(location=[site["lat"], site["lon"]], zoom_start=15, tiles=None, control_scale=True)
    folium.TileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                     attr="Imagery © Esri, Maxar, Earthstar Geographics", name="Satellite", max_zoom=19, show=True).add_to(m)
    street = ("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
              if dark else "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
    folium.TileLayer(street, attr="© Esri" if dark else "© OpenStreetMap contributors", name="Street map",
                     max_zoom=19, show=False).add_to(m)
    folium.TileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
                     attr="Labels © Esri", name="Place names", overlay=True, control=True, show=True, max_zoom=19).add_to(m)
    for r, op in [(1400, .08), (1000, .12), (650, .18)]:
        folium.Circle([site["lat"], site["lon"]], radius=r, color=None, fill=True, fill_color=DAWN, fill_opacity=op).add_to(m)
    folium.Circle([site["lat"], site["lon"]], radius=650, color=DAWN, weight=2, dash_array="6 6", fill=False,
                  tooltip="Planned service area").add_to(m)
    b = load_buildings(site["id"])
    if b is not None:
        for _, r in b.iterrows():
            biz = str(r.get("type", "home")).lower().startswith("bus")
            folium.CircleMarker([r["lat"], r["lon"]], radius=4 if biz else 2.5, weight=0, fill=True,
                                fill_color=DAWN if biz else "#7FD1FF", fill_opacity=.95,
                                tooltip="Likely business" if biz else "Home").add_to(m)
    folium.Marker([site["lat"], site["lon"]], tooltip=f"{site['name']}: proposed mini-grid site",
                  icon=folium.DivIcon(html=f'<div style="width:22px;height:22px;border-radius:50%;background:{DAWN};'
                                           f'border:3px solid #fff;box-shadow:0 0 0 6px rgba(242,169,59,.35),0 0 24px {DAWN};'
                                           f'transform:translate(-11px,-11px)"></div>')).add_to(m)
    plugins.Fullscreen(position="topright").add_to(m)
    plugins.MiniMap(toggle_display=True, zoom_level_offset=-7, position="bottomright").add_to(m)
    folium.LayerControl(position="topleft", collapsed=False).add_to(m)
    return m, b is not None


if cur == 0:
    if is_custom:
        step_header(0, "<b>What you're looking at:</b> any location you choose. Type coordinates or click the map to move "
                       "the site, then describe the village. Lumora sizes the system for your inputs straight away.")
        a, b_, c_ = st.columns([1.4, 1, 1])
        a.text_input("Site name", **bind("c_name"))
        b_.number_input("Latitude", **bind("c_lat"), min_value=-90.0, max_value=90.0, step=0.001, format="%.4f")
        c_.number_input("Longitude", **bind("c_lon"), min_value=-180.0, max_value=180.0, step=0.001, format="%.4f")
        a, b_, c_, d_ = st.columns(4)
        a.slider("Customers to connect", 30, 3000, step=10, **bind("c_cust"))
        b_.slider("Business share of demand (%)", 0, 70, **bind("c_biz"))
        c_.slider("Expected use (kWh per customer per month)", 1.0, 80.0, step=0.5, **bind("c_p50"))
        d_.select_slider("How uncertain is demand?", options=list(SPREADS), **bind("c_spread"))
        st.caption("Satellite features (buildings, businesses, roofs) are extracted automatically for the preset villages. "
                   "For custom sites, enter what you know; automatic extraction for any point is on the roadmap.")
    else:
        f = site["features"]
        step_header(0, "<b>What you're looking at:</b> the village as seen from satellite imagery and open maps, before anyone "
                       "visits. Lumora counts buildings, spots likely businesses and reads roof types, because these tell us "
                       "how much electricity people will use.")
        c = st.columns(4)
        stat(c[0], "Buildings counted", f"{f['buildings']:,}", "from building footprints")
        stat(c[1], "Likely businesses", f"{f['businesses_detected']:,}", "shops, mills and workshops seen from above")
        stat(c[2], "Metal roofs", f"{f['metal_roof_share']:.0%}", "a sign of household income")
        stat(c[3], "Distance to the grid", f"{f['dist_to_grid_km']:.0f} km", f"nearest market {f['dist_to_market_km']:.1f} km away")
    st.write("")
    m, has_b = village_map(site, st.session_state.dark)
    out = st_folium(m, height=540, use_container_width=True,
                    returned_objects=["last_clicked"] if is_custom else [],
                    key=f"map_{vid}_{st.session_state.dark}")
    if is_custom and out and out.get("last_clicked"):
        lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
        if abs(lat - st.session_state.c_lat) > 1e-6 or abs(lon - st.session_state.c_lon) > 1e-6:
            st.session_state.c_lat, st.session_state.c_lon = round(lat, 5), round(lon, 5)
            st.rerun()
    legend = f'<span><i style="background:{DAWN}"></i>Proposed mini-grid site and service area</span>'
    if has_b:
        legend += f'<span><i style="background:#7FD1FF"></i>Home</span><span><i style="background:{DAWN}"></i>Likely business</span>'
    legend += ('<span>Click the map to move the site.</span>' if is_custom else
               '<span>Switch between satellite and street map at top left. Use full screen to explore.</span>')
    st.markdown(f'<div class="lm-legend">{legend}</div>', unsafe_allow_html=True)
    nav(0)

# ----------------------------------------------------------------------------
# Step 2: demand
# ----------------------------------------------------------------------------
elif cur == 1:
    step_header(1, "<b>What you're looking at:</b> how much electricity each customer is likely to use each month. "
                   "Instead of one guess, Lumora gives a range: a low case, the most likely case and a high case. "
                   "Demand also grows after connection as people buy appliances.")
    c = st.columns(3)
    stat(c[0], "Low case", f"{fc['p10']:.1f} kWh", "per customer per month. 1 in 10 chance it is lower")
    stat(c[1], "Most likely", f"{fc['p50']:.1f} kWh", "per customer per month", "good")
    stat(c[2], "High case", f"{fc['p90']:.1f} kWh", "per customer per month. 1 in 10 chance it is higher")
    st.write("")
    g_col, d_col = st.columns([1.25, 1]) if site["drivers"] else (st.container(), None)
    with g_col:
        st.markdown("#### Demand grows after connection")
        gdf = pd.DataFrame({"Year": [f"Year {i}" for i in range(len(growth))],
                            "Low": [fc["p10"] * g for g in growth], "Most likely": [fc["p50"] * g for g in growth],
                            "High": [fc["p90"] * g for g in growth]})
        base = alt.Chart(gdf).encode(x=alt.X("Year:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)))
        band = base.mark_area(opacity=0.28, color=DAWN).encode(y=alt.Y("Low:Q", title="kWh per customer per month"), y2="High:Q")
        line = base.mark_line(point=alt.OverlayMarkDef(size=80, filled=True, color=T["ink"]), strokeWidth=3, color=T["ink"]).encode(
            y="Most likely:Q", tooltip=["Year", alt.Tooltip("Low:Q", format=".1f"), alt.Tooltip("Most likely:Q", format=".1f"),
                                        alt.Tooltip("High:Q", format=".1f")])
        st.altair_chart(chart_style((band + line).properties(height=320), T), width="stretch")
        st.caption("Line: most likely. Shaded band: low case to high case.")
    if d_col is not None:
        with d_col:
            st.markdown("#### What drives this forecast")
            ddf = pd.DataFrame(site["drivers"]).sort_values("effect_kwh_month", ascending=False)
            ddf["Effect"] = ddf["effect_kwh_month"].apply(lambda x: "Raises demand" if x > 0 else "Lowers demand")
            bars = alt.Chart(ddf).mark_bar(cornerRadius=4, height=22).encode(
                x=alt.X("effect_kwh_month:Q", title="kWh per customer per month"),
                y=alt.Y("feature:N", sort=None, title=None, axis=alt.Axis(labelLimit=200)),
                color=alt.Color("Effect:N", scale=alt.Scale(domain=["Raises demand", "Lowers demand"], range=[T["teal"], T["coral"]]),
                                legend=alt.Legend(orient="bottom", title=None)),
                tooltip=["feature", alt.Tooltip("effect_kwh_month:Q", format="+.1f")])
            st.altair_chart(chart_style(bars.properties(height=320), T), width="stretch")
    nav(1)


# ----------------------------------------------------------------------------
# Step 3: best system
# ----------------------------------------------------------------------------
def design_panel(r, title, tag, win):
    warn = f' style="color:{T["coral"]}"' if r["mean_unmet_pct"] >= 5 else ""
    return f"""<div class="lm-design {'win' if win else ''}">
  <span class="tag {'' if win else 'grey'}">{tag}</span><h3>{title}</h3>
  <div class="kit">{r['pv_kw']:.0f} kW solar, {r['batt_kwh']:.0f} kWh battery, {r['diesel_kw']:.0f} kW diesel</div>
  <div class="lm-row"><span>Days with reliable power</span><b>{r['reliable_share']:.0%}</b></div>
  <div class="lm-row"><span>Demand left unmet</span><b{warn}>{r['mean_unmet_pct']:.1f}%</b></div>
  <div class="lm-row"><span>Cost per kWh</span><b>{cents(r['cost_of_power_usd_kwh'])}</b></div>
  <div class="lm-row"><span>Diesel share of power</span><b>{r['diesel_share_pct']:.0f}%</b></div></div>"""


if cur == 2:
    step_header(2, f"<b>What you're looking at:</b> two ways to size the same mini-grid. The usual way sizes for the most "
                   f"likely demand only. Lumora sizes for the whole range and keeps adding a safety margin until the system "
                   f"meets your reliability target on {N_TEST} simulated days it has never seen. A reliable day means "
                   f"less than 5% of demand goes unmet.")
    st.markdown("**Reliability target**: how many days out of 100 should have reliable power?")
    st.segmented_control("Reliability target", ["90%", "95%", "99%"], label_visibility="collapsed", **bind("target"))
    st.write("")
    a, b = st.columns(2)
    a.markdown(design_panel(det, "Sized for the most likely demand", "Usual practice", False), unsafe_allow_html=True)
    b.markdown(design_panel(lum, f"Sized to meet {st.session_state.target} reliable days", "Lumora", True), unsafe_allow_html=True)
    gain = (lum["reliable_share"] - det["reliable_share"]) * 100
    extra = (lum["cost_of_power_usd_kwh"] / det["cost_of_power_usd_kwh"] - 1) * 100
    met = "meets" if lum["target_met"] else "comes closest to"
    st.markdown(f'<div class="lm-verdict good">Lumora {met} the {st.session_state.target} target: '
                f'<b>{lum["reliable_share"]:.0%}</b> reliable days (95% confidence {ci_pct(lum)}), '
                f'<b>{gain:.0f} points</b> more than usual practice, for <b>{extra:+.0f}%</b> on the cost per kWh. '
                f'Try another target to see what reliability costs.</div>', unsafe_allow_html=True)
    st.write("")
    with st.expander("How the optimizer chooses the system"):
        st.markdown(f"1. Sample {40} training scenarios and {N_TEST} fresh test scenarios of daily demand and sunshine (Monte Carlo).\n"
                    "2. Solve for the lowest-cost solar, battery and diesel sizes that keep unmet demand under 5% in every "
                    "training scenario, dispatching each scenario hour by hour.\n"
                    "3. Test the design on the fresh scenarios with a realistic controller that cannot see tomorrow.\n"
                    f"4. If it misses the target, add a safety margin to demand and repeat. This plan used a margin of "
                    f"{(lum['safety_margin'] - 1) * 100:.0f}%.")
        st.latex(r"\min_{P,B,G}\ \sum_k c_k(\mathrm{CRF}_k+\phi)x_k+\frac{365}{N}\sum_{s,t}c_f g_{st}"
                 r"\quad\text{s.t.}\quad \sum_t u_{st}\le(1-\alpha)\,D_s\ \ \forall s,\quad d_{st}\leftarrow m\,d_{st}")
    nav(2)

# ----------------------------------------------------------------------------
# Step 4: scenario builder + memo
# ----------------------------------------------------------------------------
PRESETS = {
    "Custom": None,
    "Productive-use programme": dict(mills=3, cold=4),
    "Demand boom": dict(dem=1.6, cust=1.2),
    "Slow uptake": dict(dem=0.5, cust=0.7),
    "Cloudy year": dict(solar=0.8),
    "Diesel price spike": dict(diesel=2.2),
    "Cheaper batteries": dict(batt=200),
}
SC_DEFAULTS = dict(dem=1.0, cust=1.0, mills=0, cold=0, diesel=BASE_COSTS.fuel_price_per_l,
                   batt=int(BASE_COSTS.batt_capex_per_kwh), solar=1.0)
for k, val in SC_DEFAULTS.items():
    st.session_state.setdefault(f"sc_{k}", val)


def _preset_changed():
    val = st.session_state.get("w_preset")
    if val is None:
        return
    st.session_state.preset = val
    p = PRESETS.get(val)
    if p is None:
        return
    for k, dv in SC_DEFAULTS.items():
        st.session_state[f"sc_{k}"] = p.get(k, dv)


def bind_preset():
    st.session_state.setdefault("preset", "Custom")
    st.session_state["w_preset"] = st.session_state.preset
    return dict(key="w_preset", on_change=_preset_changed)


def _sc_changed(key):
    st.session_state[key] = st.session_state[f"w_{key}"]
    st.session_state.preset = "Custom"


def bind_sc(key):
    st.session_state[f"w_{key}"] = st.session_state[key]
    return dict(key=f"w_{key}", on_change=_sc_changed, args=(key,))


if cur == 3:
    step_header(3, "<b>What you're looking at:</b> a sandbox for the future. Pick a ready-made scenario or set your own with "
                   "the sliders. <b>Keep today's system</b> shows what happens to the system you planned. "
                   "<b>Redesign</b> finds the best new system for that future.")
    st.markdown("**Start from a scenario**")
    st.segmented_control("Preset", list(PRESETS), label_visibility="collapsed", **bind_preset())
    st.write("")
    s1, s2, s3 = st.columns(3)
    with s1:
        st.markdown("**Demand**")
        st.slider("Use per customer vs forecast", 0.3, 2.0, step=0.05, format="%.2fx", **bind_sc("sc_dem"))
        st.slider("Customers who connect vs plan", 0.5, 1.5, step=0.05, format="%.2fx", **bind_sc("sc_cust"))
    with s2:
        st.markdown("**Productive use**")
        st.slider("Grain mills financed (7.5 kW, daytime)", 0, 8, **bind_sc("sc_mills"))
        st.slider("Cold rooms or shop fridges (0.6 kW, all day)", 0, 20, **bind_sc("sc_cold"))
    with s3:
        st.markdown("**Prices and weather**")
        st.slider("Diesel price (USD per litre)", 0.6, 3.0, step=0.1, **bind_sc("sc_diesel"))
        st.slider("Battery cost (USD per kWh)", 120, 600, step=10, **bind_sc("sc_batt"))
        st.slider("Sunshine vs normal year", 0.6, 1.2, step=0.05, format="%.2fx", **bind_sc("sc_solar"))

    st.session_state.setdefault("mode", "Keep today's system")
    st.segmented_control("Mode", ["Keep today's system", "Redesign for this future"], label_visibility="collapsed",
                         **bind("mode"))
    mode = st.session_state.mode
    ss = st.session_state
    sc_kwh = tuple(x * ss.sc_dem for x in KWH)
    sc_cust = max(10, int(round(site["n_cust"] * ss.sc_cust)))
    sc_args = (sc_cust, sc_kwh, site["business_share_of_load"], int(ss.sc_mills), int(ss.sc_cold),
               float(ss.sc_diesel), float(ss.sc_batt), float(ss.sc_solar))
    if mode == "Keep today's system":
        wi = stress_cached(tuple(sorted((k, v) for k, v in lum.items() if k in ("pv_kw", "batt_kwh", "diesel_kw"))), *sc_args)
        after_label = "Same system, new future"
    else:
        with st.spinner("Re-optimizing for this future…"):
            _, wi = plan_cached(*sc_args, TARGET)
        after_label = "Best system for this future"
    pct = lambda x: f"{x:.0%}"

    def row(name, before, after, fmt, higher_is_good=True):
        d = after - before
        tiny = 0.005 if fmt is pct else (0.0005 if fmt is cents else 0.05)
        if abs(d) < tiny:
            cls = "flat"
        elif higher_is_good is None:
            cls = "size"
        else:
            cls = "up" if (d > 0) == higher_is_good else "down"
        dfmt = (lambda x: f"{x * 100:.0f} pts") if fmt is pct else fmt
        sign = "no change" if cls == "flat" else (("+" if d > 0 else "−") + dfmt(abs(d)))
        return f"<tr><td>{name}</td><td>{fmt(before)}</td><td>{fmt(after)}</td><td class='{cls}'>{sign}</td></tr>"

    st.markdown(f"<table class='lm-delta'><tr><th></th><th>Today's plan</th><th>{after_label}</th><th>Change</th></tr>"
                + row("Solar", lum["pv_kw"], wi["pv_kw"], lambda x: f"{x:.0f} kW", None)
                + row("Battery", lum["batt_kwh"], wi["batt_kwh"], lambda x: f"{x:.0f} kWh", None)
                + row("Diesel generator", lum["diesel_kw"], wi["diesel_kw"], lambda x: f"{x:.0f} kW", None)
                + row("Cost per kWh", lum["cost_of_power_usd_kwh"], wi["cost_of_power_usd_kwh"], cents, False)
                + row("Days with reliable power", lum["reliable_share"], wi["reliable_share"], pct)
                + row("Diesel share of power", lum["diesel_share_pct"] / 100, wi["diesel_share_pct"] / 100, pct, False)
                + "</table>", unsafe_allow_html=True)
    cheaper = wi["cost_of_power_usd_kwh"] <= lum["cost_of_power_usd_kwh"]
    reliable_ok = wi["reliable_share"] >= TARGET - 0.005
    if cheaper and reliable_ok:
        tone, msg = "good", f"<b>Good news</b>: power costs {cents(wi['cost_of_power_usd_kwh'])} per kWh and reliability holds at {wi['reliable_share']:.0%}."
    elif not reliable_ok:
        tone, msg = "bad", (f"<b>Reliability drops to {wi['reliable_share']:.0%}</b>, below the {st.session_state.target} target. "
                            + ("Switch to <b>Redesign for this future</b> to see the system that fixes it." if mode.startswith("Keep") else ""))
    else:
        tone, msg = "bad", (f"<b>Power gets more expensive</b>: {cents(lum['cost_of_power_usd_kwh'])} to "
                            f"{cents(wi['cost_of_power_usd_kwh'])} per kWh. Plan for this risk before financial close.")
    st.markdown(f'<div class="lm-verdict {tone}">{msg}</div>', unsafe_allow_html=True)
    st.caption("Scenario loads and all cost inputs are illustrative until replaced with benchmark data.")

    st.write("")
    st.markdown("#### Lender memo")
    drivers_txt = ""
    if site["drivers"]:
        top = sorted(site["drivers"], key=lambda d: -abs(d["effect_kwh_month"]))[:3]
        drivers_txt = " Main drivers: " + "; ".join(f"{d['feature'].lower()} ({d['effect_kwh_month']:+.1f} kWh)" for d in top) + "."
    memo = f"""### Site assessment: {site['name']}, {site['country']}

**Recommendation.** Build {lum['pv_kw']:.0f} kW of solar, a {lum['batt_kwh']:.0f} kWh battery and {lum['diesel_kw']:.0f} kW of diesel backup. Tested on {N_TEST} simulated days it was not designed on, this system gives reliable power on {lum['reliable_share']:.0%} of days (95% confidence: {ci_pct(lum)}) at {cents(lum['cost_of_power_usd_kwh'])} per kWh.

**Demand.** About {site['n_cust']:,} customers. Most likely use is {fc['p50']:.1f} kWh per customer per month (low case {fc['p10']:.1f}, high case {fc['p90']:.1f}), growing about {growth[-1] - 1:.0%} over {len(growth) - 1} years.{drivers_txt}

**Risk.** Sizing only for the most likely demand gives reliable power on just {det['reliable_share']:.0%} of days, with {det['mean_unmet_pct']:.1f}% of demand unmet.

**Scenario tested.** {st.session_state.preset if st.session_state.preset not in (None, 'Custom') else 'Custom scenario'} ({mode.lower()}): cost per kWh {cents(wi['cost_of_power_usd_kwh'])}, reliable days {wi['reliable_share']:.0%}.

*Prepared with Lumora. Confirm cost inputs and forecasts before financial close.*"""
    st.markdown(f'<div class="lm-memo">\n\n{memo}\n\n</div>', unsafe_allow_html=True)
    st.write("")
    st.download_button("Download lender memo", memo, file_name=f"lumora_memo_{site['id']}.md")
    nav(3)

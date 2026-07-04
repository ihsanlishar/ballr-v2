import streamlit as st
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timezone, date
import os
import re
from zoneinfo import ZoneInfo
BACKEND = os.getenv("BACKEND_URL", "http://127.0.0.1:5002")

# ── Fix: Markdown treats 4+ leading spaces as a code block, even with       ─
# ── unsafe_allow_html=True. Our HTML strings are indented for readability  ─
# ── in the Python source, so we strip leading whitespace on every line     ─
# ── before it reaches the Markdown parser. This patches every HTML render  ─
# ── in the app in one place instead of touching each f-string individually.─
_markdown = st.markdown
def _html_safe_markdown(body, *args, **kwargs):
    if kwargs.get("unsafe_allow_html") and isinstance(body, str):
        body = re.sub(r'(?m)^[ \t]+', '', body)
    return _markdown(body, *args, **kwargs)
st.markdown = _html_safe_markdown

st.set_page_config(
    page_title="Ballr 2.0",
    page_icon="⚽",
    layout="wide"
)

# ── Team colors ────────────────────────────────────────────────────────────
TEAM_COLORS = {
    'Algeria':              '#006233',
    'Argentina':            '#74ACDF',
    'Australia':            '#FFD700',
    'Austria':              '#ED2939',
    'Belgium':              '#000000',
    'Bosnia-Herzegovina':   '#002395',
    'Brazil':               '#F7D116',
    'Canada':               '#FF0000',
    'Cape Verde Islands':   '#003893',
    'Colombia':             '#FCD116',
    'Congo DR':             '#007FFF',
    'Croatia':              '#FF0000',
    'Curaçao':              '#003DA5',
    'Czechia':              '#D7141A',
    'Ecuador':              '#FFD100',
    'Egypt':                '#CE1126',
    'England':              '#CF091D',
    'France':               '#002395',
    'Germany':              '#000000',
    'Ghana':                '#FCD116',
    'Haiti':                '#00209F',
    'Iran':                 '#239F40',
    'Iraq':                 '#007A3D',
    'Ivory Coast':          '#F77F00',
    'Japan':                '#BC002D',
    'Jordan':               '#007A3D',
    'Mexico':               '#006847',
    'Morocco':              '#C1272D',
    'Netherlands':          '#FF6600',
    'New Zealand':          '#000000',
    'Norway':               '#EF2B2D',
    'Panama':               '#DA121A',
    'Paraguay':             '#D52B1E',
    'Portugal':             '#006600',
    'Qatar':                '#8D1B3D',
    'Saudi Arabia':         '#006C35',
    'Scotland':             '#003DA5',
    'Senegal':              '#00853F',
    'South Africa':         '#007A4D',
    'South Korea':          '#CD2E3A',
    'Spain':                '#AA151B',
    'Sweden':               '#006AA7',
    'Switzerland':          '#FF0000',
    'Tunisia':              '#E70013',
    'Turkey':               '#E30A17',
    'United States':        '#002868',
    'Uruguay':              '#5EB6E4',
    'Uzbekistan':           '#1EB53A',
}

TEAM_COLORS_AWAY = {
    'Germany':      '#FFFFFF',
    'Belgium':      '#FFD700',
    'New Zealand':  '#FFFFFF',
    'Ghana':        '#006B3F',
    'Colombia':     '#003087',
}

def get_team_color(team, other_team=None):
    color = TEAM_COLORS.get(team, '#4a9eff')
    if other_team:
        other_color = TEAM_COLORS.get(other_team, '#7dd3fc')
        if color.lower() == other_color.lower():
            color = TEAM_COLORS_AWAY.get(team, '#ffffff')
    return color

def hex_to_rgba(hex_color, alpha=1.0):
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f'rgba({r},{g},{b},{alpha})'

st.markdown("""
<style>
    .main, [data-testid="stAppViewContainer"], section[data-testid="stMain"] {
        background-color: #080d18 !important;
    }
    [data-testid="stHeader"] { background: transparent !important; }
    #MainMenu, footer, header { visibility: hidden; }
    .block-container { padding: 2rem 3rem !important; max-width: 1400px; }

    /* ── Header ── */
    .ballr-header-row {
        display: flex;
        align-items: baseline;
        gap: 10px;
        line-height: 1;
        margin-bottom: 2px;
    }
    .ballr-title {
        font-size: 2.8rem;
        font-weight: 900;
        color: #ffffff;
        letter-spacing: -2px;
        line-height: 1;
    }
    .ballr-version {
        font-size: 1rem;
        font-weight: 700;
        color: #4a9eff;
        letter-spacing: 1px;
        margin-bottom: 6px;
        align-self: flex-end;
    }
    .ballr-sub {
        font-size: 0.82rem;
        color: #3d4f6b;
        letter-spacing: 2px;
        text-transform: uppercase;
        margin-top: 2px;
        margin-bottom: 28px;
    }

    /* ── Tabs ── */
    [data-testid="stTabs"] { border-bottom: 1px solid #131e30 !important; margin-bottom: 24px; }
    [data-testid="stTabs"] button { font-size:0.8rem !important;font-weight:600 !important;color:#3d4f6b !important;padding:10px 22px !important;border-radius:0 !important;border:none !important;background:transparent !important;letter-spacing:0.5px; }
    [data-testid="stTabs"] button:hover { color:#94a3b8 !important; }
    [data-testid="stTabs"] button[aria-selected="true"] { color:#ffffff !important;border-bottom:2px solid #4a9eff !important; }

    /* ── Date group ── */
    .date-group { font-size:0.68rem;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:#3d4f6b;margin:28px 0 14px 0;display:flex;align-items:center;gap:12px; }
    .date-group::after { content:'';flex:1;height:1px;background:#131e30; }
    .date-group-today { color:#4a9eff; }

    /* ── Match cards ── */
    .match-card { background:#0d1526;border:1px solid #131e30;border-radius:14px;padding:18px 20px 14px 20px;margin-bottom:3px; }
    .card-comp  { font-size:0.6rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#3d4f6b;margin-bottom:12px; }
    .card-body  { display:flex;align-items:center;justify-content:space-between;gap:8px; }
    .card-team-home { font-size:1rem;font-weight:700;color:#e2e8f0;flex:1; }
    .card-team-away { font-size:1rem;font-weight:700;color:#e2e8f0;flex:1;text-align:right; }
    .card-winner { color:#f0fdf4 !important; }
    .card-loser  { color:#3d4f6b !important; }
    .card-score-block { display:flex;flex-direction:column;align-items:center;gap:2px;min-width:72px; }
    .card-score-nums  { display:flex;align-items:center;gap:6px; }
    .card-score-num   { font-size:1.5rem;font-weight:900;color:#ffffff;min-width:20px;text-align:center;line-height:1; }
    .card-score-sep   { font-size:1rem;color:#1e2d45;font-weight:300; }
    .card-vs          { font-size:0.72rem;font-weight:600;color:#1e2d45;letter-spacing:1px; }
    .card-score-pens  { font-size:0.8rem;font-weight:700;color:#64748b;margin:0 2px; }
    .card-footer      { display:flex;justify-content:space-between;align-items:center;margin-top:12px;padding-top:10px;border-top:1px solid #0f1626; }
    .card-time        { font-size:0.73rem;color:#3d4f6b; }
    .badge-ft         { font-size:0.6rem;font-weight:700;letter-spacing:1.5px;background:#131e30;color:#3d4f6b;border-radius:20px;padding:3px 10px; }
    .badge-live       { font-size:0.6rem;font-weight:700;letter-spacing:1.5px;background:#0f2d1a;color:#4ade80;border-radius:20px;padding:3px 10px; }
    .badge-upcoming   { font-size:0.6rem;font-weight:700;letter-spacing:1.5px;background:#0d1a2e;color:#4a9eff;border-radius:20px;padding:3px 10px; }

    /* ── Buttons ── */
    .stButton > button { background:transparent !important;border:1px solid #131e30 !important;color:#3d4f6b !important;border-radius:8px !important;font-size:0.75rem !important;font-weight:600 !important;padding:6px 0 !important;width:100% !important;letter-spacing:0.5px;transition:all 0.15s !important; }
    .stButton > button:hover { border-color:#4a9eff !important;color:#4a9eff !important;background:#0d1a2e !important; }

    /* ── Match hero ── */
    .match-hero { background:linear-gradient(160deg,#0d1a2e 0%,#080d18 100%);border:1px solid #131e30;border-radius:20px;padding:48px 40px 40px 40px;text-align:center;margin-bottom:32px;position:relative;overflow:hidden; }
    .hero-meta   { font-size:0.72rem;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:#3d4f6b;margin-bottom:16px; }
    .hero-teams  { font-size:2rem;font-weight:900;color:#ffffff;letter-spacing:-0.5px;margin-bottom:4px; }
    .hero-vs     { color:#131e30; }
    .hero-score  { font-size:5rem;font-weight:900;letter-spacing:-4px;line-height:1;margin:8px 0 16px 0; }
    .hero-score-sep { color:#1e2d45;letter-spacing:0; }
    .hero-pens   { font-size:1.6rem;font-weight:700;color:#64748b;letter-spacing:-1px;margin:0 6px;vertical-align:middle; }
    .hero-badges { display:flex;justify-content:center;align-items:center;gap:12px;margin-top:4px; }
    .hero-badge-w { background:#0f2d1a;color:#4ade80;border:1px solid #166534;border-radius:20px;padding:4px 16px;font-size:0.72rem;font-weight:700;letter-spacing:1px; }
    .hero-badge-l { background:#1f0f0f;color:#f87171;border:1px solid #7f1d1d;border-radius:20px;padding:4px 16px;font-size:0.72rem;font-weight:700;letter-spacing:1px; }
    .hero-badge-d { background:#131e30;color:#94a3b8;border:1px solid #1e2d45;border-radius:20px;padding:4px 16px;font-size:0.72rem;font-weight:700;letter-spacing:1px; }
    .hero-result  { font-size:0.85rem;color:#3d4f6b; }

    /* ── Section headers ── */
    .sec-header { font-size:0.65rem;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#3d4f6b;margin:36px 0 16px 0;display:flex;align-items:center;gap:12px; }
    .sec-header::after { content:'';flex:1;height:1px;background:#0f1626; }

    /* ── Goal scorers ── */
    .goal-row { display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #0f1626; }
    .goal-row:last-child { border-bottom:none; }
    .goal-minute { background:#0f2d1a;color:#4ade80;border-radius:6px;padding:4px 8px;font-size:0.75rem;font-weight:800;min-width:38px;text-align:center; }
    .red-minute  { background:#1f0f0f;color:#f87171;border-radius:6px;padding:4px 8px;font-size:0.75rem;font-weight:800;min-width:38px;text-align:center; }
    .goal-player { font-size:0.9rem;color:#e2e8f0;font-weight:500; }
    .no-goals    { font-size:0.82rem;color:#3d4f6b;padding:8px 0; }

    /* ── Timeline ── */
    .timeline-wrap   { background:#0d1526;border:1px solid #131e30;border-radius:10px;padding:16px 20px 12px 20px;margin-top:20px; }
    .timeline-bar    { position:relative;background:#080d18;border-radius:6px;height:40px;margin:8px 0 6px 0; }
    .timeline-labels { display:flex;justify-content:space-between;font-size:0.65rem;color:#3d4f6b;margin-top:4px; }

    /* ── Stat boxes ── */
    .stat-box       { background:#0d1526;border:1px solid #131e30;border-radius:12px;padding:20px 16px;text-align:center; }
    .stat-val       { font-size:1.8rem;font-weight:800;color:#4a9eff;line-height:1;margin-bottom:6px; }
    .stat-val-green { font-size:1.8rem;font-weight:800;color:#4ade80;line-height:1;margin-bottom:6px; }
    .stat-val-red   { font-size:1.8rem;font-weight:800;color:#f87171;line-height:1;margin-bottom:6px; }
    .stat-lbl       { font-size:0.65rem;color:#3d4f6b;text-transform:uppercase;letter-spacing:1.5px; }

    /* ── Form pills ── */
    .form-pill-W { display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;background:#0f2d1a;color:#4ade80;border-radius:6px;font-weight:800;font-size:0.82rem;margin:2px; }
    .form-pill-D { display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;background:#131e30;color:#94a3b8;border-radius:6px;font-weight:800;font-size:0.82rem;margin:2px; }
    .form-pill-L { display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;background:#1f0f0f;color:#f87171;border-radius:6px;font-weight:800;font-size:0.82rem;margin:2px; }

    /* ── Form block ── */
    .form-block     { background:#0d1526;border:1px solid #131e30;border-radius:12px;padding:20px; }
    .form-team-name { font-size:1rem;font-weight:700;color:#ffffff;margin-bottom:12px; }
    .form-stats-row { font-size:0.78rem;color:#3d4f6b;margin-top:10px;line-height:1.7; }

    /* ── Momentum bar ── */
    .momentum-card { background:#0d1526;border:1px solid #131e30;border-radius:12px;padding:20px; }
    .momentum-team { font-size:1rem;font-weight:700;color:#ffffff;margin-bottom:4px; }
    .momentum-desc { font-size:0.78rem;color:#4b5a75;margin-bottom:12px; }
    .momentum-bar-bg { background:#080d18;border-radius:6px;height:6px;width:100%;margin:8px 0 6px 0; }
    .momentum-score-row { display:flex;justify-content:space-between;align-items:center;margin-top:6px; }
    .momentum-score-label { font-size:0.65rem;color:#3d4f6b; }
    .momentum-score-val   { font-size:0.88rem;font-weight:700; }

    /* ── Key factors ── */
    .key-factors { background:#0d1526;border:1px solid #131e30;border-radius:14px;padding:24px;margin:16px 0; }
    .kf-row      { display:flex;align-items:flex-start;gap:14px;padding:12px 0;border-bottom:1px solid #0f1626; }
    .kf-row:last-child { border-bottom:none; }
    .kf-icon  { font-size:1.1rem;min-width:24px;margin-top:1px; }
    .kf-label { font-size:0.72rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#3d4f6b;margin-bottom:3px; }
    .kf-text  { font-size:0.88rem;color:#94a3b8;line-height:1.5; }
    .kf-text strong { color:#e2e8f0; }
    .kf-badge-pos { display:inline-block;background:#0f2d1a;color:#4ade80;border-radius:4px;padding:1px 7px;font-size:0.72rem;font-weight:700;margin-left:6px; }
    .kf-badge-neg { display:inline-block;background:#1f0f0f;color:#f87171;border-radius:4px;padding:1px 7px;font-size:0.72rem;font-weight:700;margin-left:6px; }
    .kf-badge-neu { display:inline-block;background:#131e30;color:#94a3b8;border-radius:4px;padding:1px 7px;font-size:0.72rem;font-weight:700;margin-left:6px; }

    /* ── Heatmap ── */
    .heatmap-wrap { background:#0d1526;border:1px solid #131e30;border-radius:14px;padding:24px;margin:8px 0; }

    /* ── Insight box ── */
    .insight-box { background:#0d1526;border-left:3px solid #4a9eff;border-radius:0 10px 10px 0;padding:16px 20px;margin:16px 0;font-size:0.85rem;color:#64748b;line-height:1.7; }
    .insight-box strong { color:#e2e8f0; }

    /* ── Empty state ── */
    .empty-state { text-align:center;padding:60px 20px;color:#3d4f6b; }
    .empty-icon  { font-size:2.5rem;margin-bottom:12px; }

    [data-testid="stPlotlyChart"] { border-radius:12px;overflow:hidden; }

    /* ── Confidence meter ── */
    .confidence-card { background:#0d1526;border:1px solid #131e30;border-left:3px solid;border-radius:0 12px 12px 0;padding:16px 20px;margin:16px 0 28px 0; }
    .confidence-head { display:flex;align-items:center;gap:14px; }
    .confidence-icon { font-size:1.5rem;line-height:1; }
    .confidence-tier { font-size:0.85rem;font-weight:800;letter-spacing:0.5px;margin-bottom:3px; }
    .confidence-note { font-size:0.78rem;color:#64748b;line-height:1.4; }
    .confidence-note strong { color:#e2e8f0; }
    .confidence-badge { margin-left:auto;font-size:0.7rem;font-weight:800;border:1px solid;border-radius:20px;padding:4px 12px;white-space:nowrap; }
    .confidence-bar-bg { background:#080d18;border-radius:6px;height:6px;width:100%;margin-top:14px;overflow:hidden; }
    .confidence-bar-fill { height:100%;border-radius:6px;transition:width 0.3s; }

    /* ── Bracket ── */
    .bracket-wrap  { background:#0d1526;border:1px solid #131e30;border-radius:14px;padding:20px 16px;margin:8px 0 24px 0;overflow-x:auto; }
    .bracket-wrap svg { display:block;min-width:920px; }
    .bracket-legend { display:flex;gap:20px;justify-content:center;margin-top:14px;font-size:0.68rem;color:#3d4f6b; }
    .bracket-legend span { display:inline-flex;align-items:center;gap:6px; }
    .bracket-dot { width:8px;height:8px;border-radius:50%;display:inline-block; }

    /* ── Segmented control ── */
    [data-testid="stSegmentedControl"] label { font-size:0.75rem !important; }
</style>
""", unsafe_allow_html=True)

# ── Session state ──────────────────────────────────────────────────────────
if 'page' not in st.session_state:
    st.session_state.page = 'home'
if 'selected_match' not in st.session_state:
    st.session_state.selected_match = None

# ── Helpers ───────────────────────────────────────────────────────────────
def get_local_tz():
    return ZoneInfo("America/Los_Angeles")

def fmt_date_local(iso):
    try:
        dt_utc = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        dt_local = dt_utc.astimezone(get_local_tz())
        return dt_local.strftime('%a %d %b · %H:%M')
    except:
        return iso

def get_match_local_date(iso):
    try:
        dt_utc = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        dt_local = dt_utc.astimezone(get_local_tz())
        return dt_local.date()
    except:
        return None

def match_winner(m):
    """
    True winner side ('home'/'away') accounting for penalty shootouts.
    Returns None for an unfinished match or a genuine draw (e.g. group stage).
    """
    if m.get('status') != 'FINISHED':
        return None
    hs, aws = m.get('home_score'), m.get('away_score')
    if hs is None or aws is None:
        return None
    if hs != aws:
        return 'home' if hs > aws else 'away'
    if m.get('went_to_penalties'):
        hp, ap = m.get('home_penalties'), m.get('away_penalties')
        if hp is not None and ap is not None and hp != ap:
            return 'home' if hp > ap else 'away'
    return None

def score_parts(m):
    """
    Returns (home_score, home_pens, away_score, away_pens). Penalty values
    are None unless the match was decided on penalties, letting callers
    style the shootout count differently from the main scoreline.
    """
    hs, aws = m.get('home_score'), m.get('away_score')
    if hs is None or aws is None:
        return None, None, None, None
    if m.get('went_to_penalties'):
        return hs, m.get('home_penalties'), aws, m.get('away_penalties')
    return hs, None, aws, None

def fmt_stage(stage):
    return {
        'GROUP_STAGE':'Group Stage','LAST_32':'Round of 32','LAST_16':'Round of 16',
        'QUARTER_FINALS':'Quarter Final','SEMI_FINALS':'Semi Final',
        'THIRD_PLACE':'Third Place','FINAL':'Final',
    }.get(stage, stage.replace('_',' ').title())

def form_pills(form_string):
    return ''.join(f'<span class="form-pill-{c}">{c}</span>' for c in form_string)

def stat_box(val, lbl, color='blue'):
    cls = {'blue':'stat-val','green':'stat-val-green','red':'stat-val-red'}.get(color,'stat-val')
    return f'<div class="stat-box"><div class="{cls}">{val}</div><div class="stat-lbl">{lbl}</div></div>'

def sec_header(title):
    st.markdown(f'<div class="sec-header">{title}</div>', unsafe_allow_html=True)

def hero_badge(winner_side, side):
    if winner_side is None: return '<span class="hero-badge-d">DRAW</span>'
    if winner_side == side: return '<span class="hero-badge-w">WIN</span>'
    return '<span class="hero-badge-l">LOSS</span>'

def plotly_base(fig, height=300):
    fig.update_layout(
        height=height,
        paper_bgcolor='#0d1526',
        plot_bgcolor='#0d1526',
        font=dict(family='Inter, sans-serif', color='#94a3b8', size=11),
        margin=dict(l=16, r=16, t=40, b=24),
        showlegend=False,
    )
    return fig

# ── Chart: Donut ───────────────────────────────────────────────────────────
def chart_donut(home_team, away_team, p1, pd_, p2):
    c1 = get_team_color(home_team, other_team=away_team)
    c2 = get_team_color(away_team, other_team=home_team)

    fig = go.Figure(go.Pie(
        labels=[home_team, 'Draw', away_team],
        values=[p1, pd_, p2],
        hole=0.62,
        marker=dict(colors=[c1, '#131e30', c2], line=dict(color='#080d18', width=3)),
        textinfo='none',
        hovertemplate='<b>%{label}</b><br>%{value}%<extra></extra>',
        direction='clockwise',
        sort=False,
    ))

    winner     = home_team if p1 > p2 else away_team if p2 > p1 else 'Draw'
    winner_pct = max(p1, p2) if winner != 'Draw' else pd_

    fig.add_annotation(text=f'<b>{winner_pct}%</b>', x=0.5, y=0.56,
        font=dict(size=26, color='#ffffff', family='Inter, sans-serif'),
        showarrow=False, xref='paper', yref='paper')
    fig.add_annotation(text=winner, x=0.5, y=0.40,
        font=dict(size=12, color='#3d4f6b', family='Inter, sans-serif'),
        showarrow=False, xref='paper', yref='paper')

    fig.update_layout(height=300, paper_bgcolor='#0d1526', plot_bgcolor='#0d1526',
        margin=dict(l=0, r=0, t=0, b=0), showlegend=False)
    return fig

# ── Donut + prob boxes ─────────────────────────────────────────────────────
def render_donut_with_boxes(home_team, away_team, p1, pd_, p2):
    col1, col2 = st.columns([1, 1])
    with col1:
        st.plotly_chart(chart_donut(home_team, away_team, p1, pd_, p2),
                        use_container_width=True, config={'displayModeBar': False})
    with col2:
        highlight = 'home' if p1 > p2 else 'away'
        items = [(home_team, p1, 'home'), ('Draw', pd_, None), (away_team, p2, 'away')]
        boxes_html = ''
        for label, pct, side in items:
            is_hl     = side == highlight
            border    = 'border-color:#1e3a5f;' if is_hl else ''
            bg        = 'background:#0a1628;' if is_hl else ''
            pct_color = '#4a9eff' if is_hl else '#1e2d45'
            sub_text  = 'chance of winning' if side else 'chance of draw'
            boxes_html += f"""
            <div style="background:#0d1526;border:1px solid #131e30;{border}{bg}
                        border-radius:12px;padding:0;text-align:center;
                        flex:1;display:flex;flex-direction:column;
                        align-items:center;justify-content:center;">
                <div style="font-size:0.65rem;font-weight:700;letter-spacing:2px;
                            text-transform:uppercase;color:#3d4f6b;margin-bottom:6px">{label}</div>
                <div style="font-size:2.4rem;font-weight:900;color:{pct_color};line-height:1">{pct}%</div>
                <div style="font-size:0.72rem;color:#3d4f6b;margin-top:6px">{sub_text}</div>
            </div>"""
        st.markdown(f"""
        <div style="display:flex;flex-direction:column;gap:8px;height:300px;padding:4px 0;">
            {boxes_html}
        </div>
        """, unsafe_allow_html=True)

# ── Confidence meter ────────────────────────────────────────────────────────
def render_confidence_meter(home_team, away_team, p1, pd_, p2):
    """
    Confidence = gap between the model's top pick and the next most likely
    outcome. A narrow gap (e.g. 38% vs 34%) means the model sees this as
    close to a toss-up even if it has a nominal favorite; a wide gap means
    it's genuinely backing one outcome.
    """
    outcomes = [('home', home_team, p1), ('draw', 'Draw', pd_), ('away', away_team, p2)]
    ranked   = sorted(outcomes, key=lambda x: x[2], reverse=True)
    top_key, top_label, top_val = ranked[0]
    _, _, second_val            = ranked[1]
    margin = round(top_val - second_val, 1)

    if margin >= 25:
        tier, color, border, icon = 'High Confidence', '#4ade80', '#166534', '🔒'
    elif margin >= 10:
        tier, color, border, icon = 'Medium Confidence', '#eab308', '#78530a', '⚖️'
    else:
        tier, color, border, icon = 'Toss-Up', '#f87171', '#7f1d1d', '🎲'

    bar_pct = max(4, min(100, round((margin / 50) * 100)))

    st.markdown(f"""
    <div class="confidence-card" style="border-left-color:{border}">
        <div class="confidence-head">
            <span class="confidence-icon">{icon}</span>
            <div>
                <div class="confidence-tier" style="color:{color}">{tier}</div>
                <div class="confidence-note">Model favors <strong>{top_label}</strong> by {margin} pts over the next most likely outcome</div>
            </div>
            <span class="confidence-badge" style="color:{color};border-color:{border}">{margin} pt gap</span>
        </div>
        <div class="confidence-bar-bg">
            <div class="confidence-bar-fill" style="width:{bar_pct}%;background:{color}"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ── Chart: Stats comparison ────────────────────────────────────────────────
def chart_stats_comparison(home_team, away_team, home_stats, away_stats):
    c1 = get_team_color(home_team, other_team=away_team)
    c2 = get_team_color(away_team, other_team=home_team)

    def form_points(form_str):
        return sum(3 if r=='W' else 1 if r=='D' else 0 for r in form_str)

    def def_solidity(cpg):
        return round(max(0, 10 - (cpg * 2.5)), 2)

    def attack_eff(stats):
        return round(stats['goals_per_game'] * (0.5 + stats['win_rate']), 2)

    stats_config = [
        {'label':'Win Rate %',       'sublabel':'recent games',
         'home': round(home_stats['win_rate']*100,1),
         'away': round(away_stats['win_rate']*100,1), 'suffix':'%'},
        {'label':'Form Points',      'sublabel':'last 5 · max 15',
         'home': form_points(home_stats.get('form_string','')),
         'away': form_points(away_stats.get('form_string','')), 'suffix':'pts'},
        {'label':'Attack Efficiency','sublabel':'goals × win rate',
         'home': attack_eff(home_stats),
         'away': attack_eff(away_stats), 'suffix':''},
        {'label':'Def. Solidity',    'sublabel':'lower conceded = higher',
         'home': def_solidity(home_stats['conceded_per_game']),
         'away': def_solidity(away_stats['conceded_per_game']), 'suffix':''},
    ]

    fig = make_subplots(rows=1, cols=4,
        subplot_titles=[s['label'] for s in stats_config],
        horizontal_spacing=0.10)

    for i, stat in enumerate(stats_config, start=1):
        hv, av = stat['home'], stat['away']
        diff    = abs(hv - av)
        padding = diff * 0.5 if diff > 0 else max(hv, av) * 0.25 if max(hv,av) > 0 else 1
        y_min   = max(0, min(hv,av) - padding)
        y_max   = max(hv,av) + padding

        fig.add_trace(go.Bar(name=home_team, x=[home_team], y=[hv],
            marker_color=hex_to_rgba(c1, 0.85),
            marker_line=dict(color=c1, width=1),
            showlegend=(i==1), width=0.4,
            hovertemplate=f'<b>{home_team}</b><br>{hv}{stat["suffix"]}<extra></extra>'),
            row=1, col=i)
        fig.add_trace(go.Bar(name=away_team, x=[away_team], y=[av],
            marker_color=hex_to_rgba(c2, 0.85),
            marker_line=dict(color=c2, width=1),
            showlegend=(i==1), width=0.4,
            hovertemplate=f'<b>{away_team}</b><br>{av}{stat["suffix"]}<extra></extra>'),
            row=1, col=i)

        fig.update_yaxes(range=[y_min, y_max], showgrid=True,
            gridcolor='#0f1626', zeroline=False,
            tickfont=dict(color='#3d4f6b', size=9), row=1, col=i)
        fig.update_xaxes(showgrid=False,
            tickfont=dict(color='#3d4f6b', size=10), row=1, col=i)

    fig.update_layout(height=300, paper_bgcolor='#0d1526', plot_bgcolor='#0d1526',
        font=dict(family='Inter, sans-serif', color='#94a3b8', size=11),
        margin=dict(l=16, r=16, t=52, b=16), showlegend=True, barmode='group',
        legend=dict(orientation='h', yanchor='bottom', y=1.08, xanchor='right', x=1,
            font=dict(size=11, color='#94a3b8'), bgcolor='rgba(0,0,0,0)'))

    for ann in fig.layout.annotations:
        ann.font = dict(size=10, color='#3d4f6b', family='Inter, sans-serif')

    return fig

# ── Chart: Score heatmap ───────────────────────────────────────────────────
def chart_score_heatmap(home_team, away_team, score_dist, actual_score=None):
    c1 = get_team_color(home_team, other_team=away_team)
    h  = c1.lstrip('#')
    r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)

    max_goals = 5
    z, text = [], []
    for ag in range(max_goals+1):
        row_z, row_t = [], []
        for hg in range(max_goals+1):
            val = score_dist.get(f'{hg}-{ag}', 0.0)
            row_z.append(val)
            row_t.append(f'{val:.1f}%')
        z.append(row_z)
        text.append(row_t)

    colorscale = [
        [0.0, 'rgba(8,13,24,1)'],
        [0.3, f'rgba({r},{g},{b},0.2)'],
        [0.6, f'rgba({r},{g},{b},0.55)'],
        [1.0, f'rgba({r},{g},{b},1)'],
    ]

    fig = go.Figure(go.Heatmap(
        z=z, x=[str(i) for i in range(max_goals+1)],
        y=[str(i) for i in range(max_goals+1)],
        text=text, texttemplate='%{text}',
        textfont=dict(size=10, color='#ffffff'),
        colorscale=colorscale, showscale=False,
        hovertemplate=f'{home_team} %{{x}} – %{{y}} {away_team}<br>%{{z:.1f}}%<extra></extra>',
        xgap=4, ygap=4,
    ))

    if actual_score and '-' in str(actual_score):
        try:
            hg, ag = int(str(actual_score).split('-')[0]), int(str(actual_score).split('-')[1])
            if hg <= max_goals and ag <= max_goals:
                fig.add_shape(type='rect',
                    x0=hg-0.5, x1=hg+0.5, y0=ag-0.5, y1=ag+0.5,
                    line=dict(color='#4ade80', width=2), fillcolor='rgba(0,0,0,0)')
                fig.add_annotation(x=hg, y=ag, text='✓',
                    font=dict(size=16, color='#4ade80'), showarrow=False, yshift=14)
        except:
            pass

    fig.update_layout(
        xaxis=dict(title=dict(text=home_team, font=dict(size=11, color='#94a3b8')), side='bottom'),
        yaxis=dict(title=dict(text=away_team, font=dict(size=11, color='#94a3b8')), autorange='reversed'),
        height=420, paper_bgcolor='#0d1526', plot_bgcolor='#0d1526',
        font=dict(family='Inter, sans-serif', color='#94a3b8', size=11),
        margin=dict(l=48, r=16, t=32, b=48),
    )
    fig.update_xaxes(showgrid=False, tickfont=dict(color='#3d4f6b', size=10))
    fig.update_yaxes(showgrid=False, tickfont=dict(color='#3d4f6b', size=10))
    return fig

# ── Form momentum cards ────────────────────────────────────────────────────
def render_momentum_cards(home_team, away_team, sim):
    mom1 = sim.get('home_momentum', 0)
    mom2 = sim.get('away_momentum', 0)

    def momentum_desc(score):
        if score > 0.6:   return "Excellent recent run — high confidence"
        if score > 0.3:   return "Good form heading into this match"
        if score > 0.0:   return "Decent form — slightly positive"
        if score > -0.3:  return "Mixed recent results"
        if score > -0.6:  return "Struggling for form going in"
        return "Poor recent run — low confidence"

    col1, col2 = st.columns(2)
    for col, team, mom in [(col1, home_team, mom1), (col2, away_team, mom2)]:
        with col:
            fill_pct = int((mom + 1) / 2 * 100)
            color    = '#4ade80' if mom > 0.2 else '#f87171' if mom < -0.2 else '#94a3b8'
            label    = 'Positive' if mom > 0.2 else 'Negative' if mom < -0.2 else 'Neutral'
            st.markdown(f"""
            <div class="momentum-card">
                <div class="momentum-team">{team}</div>
                <div class="momentum-desc">{momentum_desc(mom)}</div>
                <div class="momentum-bar-bg">
                    <div style="width:{fill_pct}%;background:{color};height:6px;border-radius:6px"></div>
                </div>
                <div class="momentum-score-row">
                    <span class="momentum-score-label">Low</span>
                    <span class="momentum-score-val" style="color:{color}">{label} · {mom:+.2f}</span>
                    <span class="momentum-score-label">High</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

# ── Form blocks ────────────────────────────────────────────────────────────
def render_form_blocks(home_team, away_team, hs, aws):
    col1, col2 = st.columns(2)
    for col, team, stats in [(col1, home_team, hs), (col2, away_team, aws)]:
        with col:
            wr_color = '#4ade80' if stats.get('win_rate',0) >= 0.5 else '#f87171' if stats.get('win_rate',0) < 0.25 else '#94a3b8'
            st.markdown(f"""
            <div class="form-block">
                <div class="form-team-name">{team}</div>
                <div style="margin-bottom:8px">{form_pills(stats['form_string'])}</div>
                <div class="form-stats-row">
                    <span style="color:{wr_color};font-weight:700">{stats['wins']}W {stats['draws']}D {stats['losses']}L</span>
                    &nbsp;·&nbsp; {stats['played']} games<br>
                    Goals scored: <strong style="color:#e2e8f0">{stats['goals_per_game']:.2f}/game</strong>
                    &nbsp;·&nbsp; Conceded: <strong style="color:#e2e8f0">{stats['conceded_per_game']:.2f}/game</strong><br>
                    Clean sheet rate: <strong style="color:#e2e8f0">{stats['clean_sheet_rate']*100:.0f}%</strong>
                    &nbsp;·&nbsp; GD/game: <strong style="color:{'#4ade80' if stats['gd_per_game']>=0 else '#f87171'}">{stats['gd_per_game']:+.2f}</strong>
                </div>
            </div>
            """, unsafe_allow_html=True)

# ── Key factors ────────────────────────────────────────────────────────────
def render_key_factors(home_team, away_team, home_stats, away_stats, sim):
    sec_header("Why the Model Predicted This")
    factors = []

    # Elo factor
    elo_h = sim.get('elo_home', 1600)
    elo_a = sim.get('elo_away', 1600)
    elo_diff = elo_h - elo_a
    if abs(elo_diff) > 50:
        stronger = home_team if elo_diff > 0 else away_team
        weaker   = away_team if elo_diff > 0 else home_team
        badge_cls = 'kf-badge-pos'
        factors.append({'icon':'🏅','label':'Elo Rating',
            'text': f'<strong>{stronger}</strong> enters this match ranked <strong>{abs(elo_diff)} Elo points higher</strong> than <strong>{weaker}</strong> ({max(elo_h,elo_a)} vs {min(elo_h,elo_a)}). Elo is a globally accepted measure of team strength — this gap anchors the base win probability before any form data is applied.',
            'badge': f'<span class="{badge_cls}">{stronger} higher ranked</span>'})

    # Form momentum factor
    mom1 = sim.get('home_momentum', 0)
    mom2 = sim.get('away_momentum', 0)
    mom_diff = mom1 - mom2
    if abs(mom_diff) > 0.2:
        better = home_team if mom_diff > 0 else away_team
        badge_cls = 'kf-badge-pos' if mom_diff > 0 else 'kf-badge-neg'
        factors.append({'icon':'📈','label':'Form Momentum',
            'text': f'<strong>{better}</strong> came into this match on a measurably stronger run of recent results. Form momentum score gap: <strong>{abs(mom_diff):.2f}</strong> — this translated to a <strong>~{abs(mom_diff)*6:.1f}%</strong> adjustment in projected attacking output.',
            'badge': f'<span class="{badge_cls}">{better} better form</span>'})

    # Defensive strength
    h_cs, a_cs = home_stats['clean_sheet_rate'], away_stats['clean_sheet_rate']
    if abs(h_cs - a_cs) > 0.1:
        stronger_def = home_team if h_cs > a_cs else away_team
        factors.append({'icon':'🛡️','label':'Defensive Strength',
            'text': f'<strong>{stronger_def}</strong> kept clean sheets in <strong>{max(h_cs,a_cs)*100:.0f}%</strong> of recent games vs <strong>{min(h_cs,a_cs)*100:.0f}%</strong> for their opponent — directly suppressing the opposition\'s expected goals in the model.',
            'badge': f'<span class="kf-badge-pos">{stronger_def} tighter defense</span>'})

    # Attacking output
    h_gpg, a_gpg = home_stats['goals_per_game'], away_stats['goals_per_game']
    if abs(h_gpg - a_gpg) > 0.3:
        sharper = home_team if h_gpg > a_gpg else away_team
        factors.append({'icon':'⚡','label':'Attacking Output',
            'text': f'<strong>{sharper}</strong> averaged <strong>{max(h_gpg,a_gpg):.1f} goals/game</strong> in recent form vs <strong>{min(h_gpg,a_gpg):.1f}</strong> for their opponent — raising their base xG in the simulation.',
            'badge': f'<span class="kf-badge-pos">{sharper} more clinical</span>'})

    # GD per game
    h_gd, a_gd = home_stats['gd_per_game'], away_stats['gd_per_game']
    if abs(h_gd - a_gd) > 0.5:
        dominant = home_team if h_gd > a_gd else away_team
        factors.append({'icon':'📊','label':'Goal Difference Per Game',
            'text': f'<strong>{dominant}</strong> carried a GD of <strong>{max(h_gd,a_gd):+.2f} per game</strong> into this match. Sustained positive GD indicates a team that consistently dominates — the model applies a small compounding multiplier for this.',
            'badge': f'<span class="kf-badge-pos">{dominant} dominant</span>'})

    if not factors:
        factors.append({'icon':'⚖️','label':'Evenly Matched',
            'text': 'Both teams came in with comparable Elo ratings, form, and attacking output. The model found no dominant edge — this is a genuinely open match.',
            'badge': '<span class="kf-badge-neu">No clear edge</span>'})

    rows_html = ''.join(f'''
    <div class="kf-row">
        <div class="kf-icon">{f["icon"]}</div>
        <div>
            <div class="kf-label">{f["label"]} {f["badge"]}</div>
            <div class="kf-text">{f["text"]}</div>
        </div>
    </div>''' for f in factors[:5])

    st.markdown(f'<div class="key-factors">{rows_html}</div>', unsafe_allow_html=True)

# ── Bracket visualization ────────────────────────────────────────────────────
def render_bracket_view(fixtures):
    """
    Renders the knockout stage as a proper connected tournament tree (SVG),
    built purely from data already in `fixtures` — no extra API calls.
    Each round is vertically centered between the two matches that feed it,
    so the connector lines line up cleanly regardless of bracket size.
    """
    stage_order = ['LAST_32', 'LAST_16', 'QUARTER_FINALS', 'SEMI_FINALS', 'FINAL']
    stage_names = {
        'LAST_32': 'Round of 32', 'LAST_16': 'Round of 16',
        'QUARTER_FINALS': 'Quarterfinals', 'SEMI_FINALS': 'Semifinals', 'FINAL': 'Final',
    }
    rounds = [[f for f in fixtures if f['stage'] == s] for s in stage_order]

    if not rounds[0]:
        st.markdown(
            '<div class="empty-state"><div class="empty-icon">🏆</div>'
            'Bracket will appear once the Round of 32 draw is set.</div>',
            unsafe_allow_html=True)
        return

    base_pitch = 64
    card_w, card_h = 172, 46
    col_gap, left_pad, top_pad = 64, 24, 40
    champ_w = 150

    def slot_y(round_idx, match_idx):
        pitch = base_pitch * (2 ** round_idx)
        return top_pad + pitch / 2 + match_idx * pitch

    n0 = len(rounds[0])
    total_h = n0 * base_pitch + top_pad + 30
    total_w = left_pad + len(rounds) * (card_w + col_gap) + champ_w + 20

    def esc(s):
        return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    def team_row(name, score, pens, is_winner, is_loser, y_off, color):
        if not name:
            return f'<text x="14" y="{y_off}" font-size="10" fill="#3d4f6b" font-style="italic">TBD</text>'
        disp = esc(name if len(name) <= 17 else name[:16] + '…')
        weight = '800' if is_winner else '500'
        fill   = '#f8fafc' if is_winner else ('#3d4f6b' if is_loser else '#cbd5e1')
        score_txt = '' if score is None else str(score)
        pens_txt  = f'<tspan font-size="8" font-weight="600" fill="{fill}" opacity="0.75" dx="3">({pens})</tspan>' if pens is not None else ''
        return (
            f'<circle cx="6" cy="{y_off-4}" r="3" fill="{color}"/>'
            f'<text x="16" y="{y_off}" font-size="10.5" font-weight="{weight}" fill="{fill}" font-family="Inter, sans-serif">{disp}</text>'
            f'<text x="{card_w-12}" y="{y_off}" font-size="11" font-weight="800" fill="{fill}" text-anchor="end" font-family="Inter, sans-serif">{score_txt}{pens_txt}</text>'
        )

    parts = [f'<svg viewBox="0 0 {total_w} {total_h}" xmlns="http://www.w3.org/2000/svg" width="100%" height="{total_h}">']

    # round headers
    for r, s in enumerate(stage_order):
        x = left_pad + r * (card_w + col_gap)
        parts.append(
            f'<text x="{x+card_w/2}" y="20" font-size="9.5" font-weight="700" letter-spacing="1.5" '
            f'fill="#3d4f6b" text-anchor="middle" font-family="Inter, sans-serif">{stage_names[s].upper()}</text>'
        )

    # connectors (drawn first, so cards sit on top)
    for r in range(1, len(rounds)):
        prev_n = len(rounds[r - 1])
        for i in range(len(rounds[r])):
            if 2 * i + 1 >= prev_n:
                break
            y1 = slot_y(r - 1, 2 * i)
            y2 = slot_y(r - 1, 2 * i + 1)
            ym = slot_y(r, i)
            x_prev_right = left_pad + (r - 1) * (card_w + col_gap) + card_w
            x_mid        = x_prev_right + col_gap / 2
            x_next_left  = left_pad + r * (card_w + col_gap)
            parts.append(f'<path d="M{x_prev_right},{y1} H{x_mid}" stroke="#1e2d45" stroke-width="1.5" fill="none"/>')
            parts.append(f'<path d="M{x_prev_right},{y2} H{x_mid}" stroke="#1e2d45" stroke-width="1.5" fill="none"/>')
            parts.append(f'<path d="M{x_mid},{y1} V{y2}" stroke="#1e2d45" stroke-width="1.5" fill="none"/>')
            parts.append(f'<path d="M{x_mid},{ym} H{x_next_left}" stroke="#1e2d45" stroke-width="1.5" fill="none"/>')

    # match cards
    for r, ms in enumerate(rounds):
        x = left_pad + r * (card_w + col_gap)
        for i, m in enumerate(ms):
            y = slot_y(r, i) - card_h / 2
            home, away = m.get('home'), m.get('away')
            hs, aw_s   = m.get('home_score'), m.get('away_score')
            finished   = m.get('status') == 'FINISHED' and hs is not None and aw_s is not None
            winner_side = match_winner(m)
            home_win   = winner_side == 'home'
            away_win   = winner_side == 'away'
            home_pens  = m.get('home_penalties') if m.get('went_to_penalties') else None
            away_pens  = m.get('away_penalties') if m.get('went_to_penalties') else None
            hc = get_team_color(home, other_team=away) if home else '#1e2d45'
            ac = get_team_color(away, other_team=home) if away else '#1e2d45'
            border = '#131e30' if not finished else '#1e3a5f'

            parts.append(f'<g transform="translate({x},{y})">')
            parts.append(f'<rect width="{card_w}" height="{card_h}" rx="8" fill="#0d1526" stroke="{border}" stroke-width="1"/>')
            parts.append(f'<line x1="0" y1="{card_h/2}" x2="{card_w}" y2="{card_h/2}" stroke="#0f1626" stroke-width="1"/>')
            parts.append(team_row(home, hs, home_pens, home_win, away_win, 17, hc))
            parts.append(team_row(away, aw_s, away_pens, away_win, home_win, card_h - 7, ac))
            parts.append('</g>')

    # champion box
    final_matches = rounds[-1]
    champ, champ_known = 'TBD', False
    if final_matches:
        fm = final_matches[0]
        hs, aw_s = fm.get('home_score'), fm.get('away_score')
        if fm.get('status') == 'FINISHED' and hs is not None and aw_s is not None and hs != aw_s:
            champ, champ_known = (fm['home'] if hs > aw_s else fm['away']), True
        x_final_right = left_pad + (len(rounds) - 1) * (card_w + col_gap) + card_w
        x_champ       = x_final_right + col_gap
        y_champ       = slot_y(len(rounds) - 1, 0)
        champ_border  = '#facc15' if champ_known else '#131e30'
        champ_color   = '#facc15' if champ_known else '#3d4f6b'
        parts.append(f'<path d="M{x_final_right},{y_champ} H{x_champ}" stroke="#1e2d45" stroke-width="1.5" fill="none"/>')
        parts.append(f'<g transform="translate({x_champ},{y_champ-30})">')
        parts.append(f'<rect width="{champ_w}" height="60" rx="10" fill="#0d1526" stroke="{champ_border}" stroke-width="1.5"/>')
        parts.append(f'<text x="{champ_w/2}" y="26" font-size="18" text-anchor="middle">🏆</text>')
        parts.append(f'<text x="{champ_w/2}" y="47" font-size="11" font-weight="800" fill="{champ_color}" text-anchor="middle" font-family="Inter, sans-serif">{esc(champ)}</text>')
        parts.append('</g>')

    parts.append('</svg>')

    st.markdown(f'<div class="bracket-wrap">{"".join(parts)}</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="bracket-legend">
        <span><span class="bracket-dot" style="background:#f8fafc"></span>Winner</span>
        <span><span class="bracket-dot" style="background:#3d4f6b"></span>Eliminated</span>
        <span><span class="bracket-dot" style="background:#facc15"></span>Champion</span>
    </div>
    """, unsafe_allow_html=True)

def render_third_place_card(m):
    home, away = m.get('home'), m.get('away')
    hs, aws    = m.get('home_score'), m.get('away_score')
    finished   = m.get('status') == 'FINISHED' and hs is not None and aws is not None
    winner_side = match_winner(m)
    home_cls   = 'card-winner' if winner_side == 'home' else 'card-loser' if winner_side == 'away' else ''
    away_cls   = 'card-winner' if winner_side == 'away' else 'card-loser' if winner_side == 'home' else ''

    if finished:
        hs_disp, hp, aws_disp, ap = score_parts(m)
        hp_html = f'<span class="card-score-pens">({hp})</span>' if hp is not None else ''
        ap_html = f'<span class="card-score-pens">({ap})</span>' if ap is not None else ''
        score_html = f'<div class="card-score-nums">{hp_html}<span class="card-score-num">{hs_disp}</span><span class="card-score-sep">–</span><span class="card-score-num">{aws_disp}</span>{ap_html}</div>'
        badge = '<span class="badge-ft">PENS</span>' if m.get('went_to_penalties') else '<span class="badge-ft">FT</span>'
    else:
        score_html = '<div class="card-vs">VS</div>'
        badge = '<span class="badge-upcoming">Upcoming</span>'

    st.markdown('<div class="date-group">🥉 THIRD PLACE PLAYOFF</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="match-card" style="max-width:440px;margin:0 auto;">
        <div class="card-body">
            <div class="card-team-home {home_cls}">{home or 'TBD'}</div>
            <div class="card-score-block">{score_html}</div>
            <div class="card-team-away {away_cls}">{away or 'TBD'}</div>
        </div>
        <div class="card-footer">
            <span class="card-time">{fmt_date_local(m['date']) if m.get('date') else ''}</span>
            {badge}
        </div>
    </div>
    """, unsafe_allow_html=True)

# ── HOME PAGE ──────────────────────────────────────────────────────────────
def show_home():
    logo_path = os.path.join(os.path.dirname(__file__), 'logo.png')
    col_logo, col_title = st.columns([1, 10])
    with col_logo:
        if os.path.exists(logo_path):
            st.image(logo_path, width=72)
    with col_title:
        st.markdown("""
        <div style="padding-top:6px">
            <div class="ballr-header-row">
                <span class="ballr-title">Ballr</span>
                <span class="ballr-version">2.0</span>
            </div>
            <div class="ballr-sub">2026 FIFA World Cup · Match Predictor</div>
        </div>""", unsafe_allow_html=True)

    with st.spinner(""):
        try:
            r = requests.get(f"{BACKEND}/fixtures", timeout=10)
            fixtures = r.json()
        except:
            st.error("Can't reach backend.")
            return

    fixtures = [f for f in fixtures if f['home'] and f['away']]
    today    = datetime.now(ZoneInfo("America/Los_Angeles")).date()
    knockout_stages = {'LAST_32','LAST_16','QUARTER_FINALS','SEMI_FINALS','THIRD_PLACE','FINAL'}

    def render_grid(matches, tab_key):
        if not matches:
            st.markdown('<div class="empty-state"><div class="empty-icon">📅</div>No matches found.</div>', unsafe_allow_html=True)
            return
        cols = st.columns(3)
        for i, m in enumerate(matches):
            with cols[i % 3]:
                finished = m['status'] == 'FINISHED'
                live     = m['status'] in ('IN_PLAY','PAUSED')
                tc       = get_team_color(m['home'], other_team=m['away'])
                accent   = hex_to_rgba(tc, 0.35)

                if finished:
                    winner_side = match_winner(m)
                    home_cls = 'card-winner' if winner_side == 'home' else 'card-loser' if winner_side == 'away' else ''
                    away_cls = 'card-winner' if winner_side == 'away' else 'card-loser' if winner_side == 'home' else ''
                    hs_disp, hp, aws_disp, ap = score_parts(m)
                    hp_html = f'<span class="card-score-pens">({hp})</span>' if hp is not None else ''
                    ap_html = f'<span class="card-score-pens">({ap})</span>' if ap is not None else ''
                    score_html = f'<div class="card-score-nums">{hp_html}<span class="card-score-num">{hs_disp}</span><span class="card-score-sep">–</span><span class="card-score-num">{aws_disp}</span>{ap_html}</div>'
                    badge = '<span class="badge-ft">PENS</span>' if m.get('went_to_penalties') else '<span class="badge-ft">FT</span>'
                elif live:
                    home_cls = away_cls = ''
                    score_html = '<div class="card-vs" style="color:#4ade80">LIVE</div>'
                    badge = '<span class="badge-live">● LIVE</span>'
                else:
                    home_cls = away_cls = ''
                    score_html = '<div class="card-vs">VS</div>'
                    badge = '<span class="badge-upcoming">Upcoming</span>'

                st.markdown(f"""
                <div class="match-card" style="border-left:3px solid {accent}">
                    <div class="card-comp">{fmt_stage(m['stage'])}</div>
                    <div class="card-body">
                        <div class="card-team-home {home_cls}">{m['home']}</div>
                        <div class="card-score-block">{score_html}</div>
                        <div class="card-team-away {away_cls}">{m['away']}</div>
                    </div>
                    <div class="card-footer">
                        <span class="card-time">{fmt_date_local(m['date'])}</span>
                        {badge}
                    </div>
                </div>
                """, unsafe_allow_html=True)

                if st.button("View match →", key=f"btn_{tab_key}_{m['id']}_{i}", use_container_width=True):
                    st.session_state.selected_match = m
                    st.session_state.page = 'match'
                    st.rerun()

    tab_today, tab_all, tab_group, tab_knockout = st.tabs([
        "📅  Today", "🌍  All Matches", "⚽  Group Stage", "🏆  Knockout"
    ])

    with tab_today:
        today_matches = [f for f in fixtures if get_match_local_date(f['date']) == today]
        if today_matches:
            render_grid(today_matches, "today")
        else:
            upcoming = [f for f in fixtures if f['status'] != 'FINISHED']
            if upcoming:
                nearest     = min((get_match_local_date(f['date']) for f in upcoming if get_match_local_date(f['date'])), default=None)
                near_matches = [f for f in upcoming if get_match_local_date(f['date']) == nearest]
                st.markdown(f"<div style='color:#3d4f6b;font-size:0.78rem;margin-bottom:16px'>No matches today — next matchday: {nearest.strftime('%a %d %b') if nearest else ''}</div>", unsafe_allow_html=True)
                render_grid(near_matches, "today")
            else:
                render_grid([], "today")

    with tab_all:
        by_date = {}
        for f in fixtures:
            d = get_match_local_date(f['date'])
            if d: by_date.setdefault(d, []).append(f)
        for d in sorted(by_date.keys()):
            is_today  = d == today
            label_cls = 'date-group-today' if is_today else ''
            st.markdown(f'<div class="date-group {label_cls}">{"Today · " if is_today else ""}{d.strftime("%A %d %B")}</div>', unsafe_allow_html=True)
            render_grid(by_date[d], f"all_{d}")

    with tab_group:
        render_grid([f for f in fixtures if f['stage'] == 'GROUP_STAGE'], "group")

    with tab_knockout:
        view_mode = st.segmented_control(
            "View", ["🏆 Bracket", "📋 List"], default="🏆 Bracket",
            label_visibility="collapsed", key="ko_view_mode",
        )
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        if view_mode == "📋 List":
            ko = [f for f in fixtures if f['stage'] in knockout_stages]
            if ko:
                by_stage = {}
                for f in ko: by_stage.setdefault(fmt_stage(f['stage']), []).append(f)
                for s, ms in by_stage.items():
                    st.markdown(f'<div class="date-group">{s}</div>', unsafe_allow_html=True)
                    render_grid(ms, f"ko_{s}")
            else:
                render_grid([], "knockout")
        else:
            render_bracket_view(fixtures)
            third_place = [f for f in fixtures if f['stage'] == 'THIRD_PLACE']
            if third_place:
                render_third_place_card(third_place[0])

# ── FINISHED MATCH ─────────────────────────────────────────────────────────
def show_finished_match(m, data):
    sim    = data['simulation']
    hs     = data['home_stats']
    aws    = data['away_stats']
    events = data.get('events') or {}
    home_name = data.get('home_name', m['home'])
    away_name = data.get('away_name', m['away'])

    home_score   = m['home_score']
    away_score   = m['away_score']
    winner_side  = match_winner(m)
    winner       = home_name if winner_side == 'home' else away_name if winner_side == 'away' else None
    result_text  = f"{winner} won on penalties" if (winner and m.get('went_to_penalties')) else f"{winner} won" if winner else "Match drawn"
    actual_score = f"{home_score}-{away_score}"
    venue        = events.get('venue', '')
    stage_label  = events.get('stage', fmt_stage(m['stage']))

    c1_color = get_team_color(home_name, other_team=away_name)
    c2_color = get_team_color(away_name, other_team=home_name)
    hs_color = '#4ade80' if winner_side == 'home' else '#f87171' if winner_side == 'away' else '#ffffff'
    as_color = '#4ade80' if winner_side == 'away' else '#f87171' if winner_side == 'home' else '#ffffff'
    hs_score, hp, aws_score, ap = score_parts(m)
    hp_html = f'<span class="hero-pens">({hp})</span>' if hp is not None else ''
    ap_html = f'<span class="hero-pens">({ap})</span>' if ap is not None else ''

    st.markdown(f"""
    <div class="match-hero" style="border-top:3px solid {c1_color}">
        <div class="hero-meta">{stage_label}{f' · {venue}' if venue else ''} · {fmt_date_local(m['date'])}</div>
        <div class="hero-teams">{home_name} <span class="hero-vs">vs</span> {away_name}</div>
        <div class="hero-score">
            {hp_html}<span style="color:{hs_color}">{hs_score}</span>
            <span class="hero-score-sep"> – </span>
            <span style="color:{as_color}">{aws_score}</span>{ap_html}
        </div>
        {'<div class="hero-meta" style="margin-top:-8px;margin-bottom:16px">Decided on penalties</div>' if m.get('went_to_penalties') else ''}
        <div class="hero-badges">
            {hero_badge(winner_side, 'home')}
            <span class="hero-result">{result_text}</span>
            {hero_badge(winner_side, 'away')}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Goal scorers ──
    home_ev    = events.get(home_name, {})
    away_ev    = events.get(away_name, {})
    home_goals = home_ev.get('goals', [])
    away_goals = away_ev.get('goals', [])
    home_reds  = home_ev.get('red_cards', [])
    away_reds  = away_ev.get('red_cards', [])

    if home_goals or away_goals or home_reds or away_reds:
        sec_header("Goal Scorers & Key Events")
        col1, col2 = st.columns(2)

        def render_scorers(col, team_name, goals, reds):
            with col:
                st.markdown(f'<div style="font-size:0.78rem;font-weight:700;color:#3d4f6b;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:12px">{team_name}</div>', unsafe_allow_html=True)
                if not goals and not reds:
                    st.markdown('<div class="no-goals">No goals</div>', unsafe_allow_html=True)
                for g in goals:
                    st.markdown(f'<div class="goal-row"><span class="goal-minute">{g["minute"]}\'</span><span>⚽</span><span class="goal-player">{g["player"]}</span></div>', unsafe_allow_html=True)
                for r in reds:
                    st.markdown(f'<div class="goal-row"><span class="red-minute">{r["minute"]}\'</span><span>🟥</span><span class="goal-player" style="color:#f87171">{r["player"]}</span></div>', unsafe_allow_html=True)

        render_scorers(col1, home_name, home_goals, home_reds)
        render_scorers(col2, away_name, away_goals, away_reds)

        # Timeline
        all_ev = []
        for g in home_goals: all_ev.append({'m': g['minute'] or 0, 'team':'home', 'type':'goal', 'p': g['player']})
        for g in away_goals: all_ev.append({'m': g['minute'] or 0, 'team':'away', 'type':'goal', 'p': g['player']})
        for r in home_reds:  all_ev.append({'m': r['minute'] or 0, 'team':'home', 'type':'red',  'p': r['player']})
        for r in away_reds:  all_ev.append({'m': r['minute'] or 0, 'team':'away', 'type':'red',  'p': r['player']})
        all_ev.sort(key=lambda x: x['m'])

        dots = ''
        for ev in all_ev:
            pct = min(ev['m'] / 95 * 100, 97)
            if ev['type'] == 'goal':
                color = c1_color if ev['team'] == 'home' else c2_color
                top   = '6px' if ev['team'] == 'home' else '22px'
                dots += '<div title="{} {}\'" style="position:absolute;left:{}%;top:{};width:10px;height:10px;background:{};border-radius:50%;transform:translateX(-50%);box-shadow:0 0 6px {}66"></div>'.format(ev['p'], ev['m'], pct, top, color, color)
            else:
                dots += '<div title="{} {} {}\'" style="position:absolute;left:{}%;top:12px;width:3px;height:16px;background:#f87171;transform:translateX(-50%)"></div>'.format(ev['p'], '🟥', ev['m'], pct)

        st.markdown(f"""
        <div class="timeline-wrap">
            <div style="font-size:0.65rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#3d4f6b;margin-bottom:6px">Match Timeline</div>
            <div style="display:flex;gap:16px;font-size:0.68rem;color:#3d4f6b;margin-bottom:8px">
                <span>● <span style="color:{c1_color}">{home_name}</span></span>
                <span>● <span style="color:{c2_color}">{away_name}</span></span>
                <span style="color:#f87171">| Red card</span>
            </div>
            <div class="timeline-bar">
                <div style="position:absolute;left:47.4%;top:0;bottom:0;width:1px;background:#131e30"></div>
                {dots}
            </div>
            <div class="timeline-labels"><span>0'</span><span>HT</span><span>90'</span></div>
        </div>
        """, unsafe_allow_html=True)

        if home_goals or away_goals:
            ht_h  = len([g for g in home_goals if (g['minute'] or 0) <= 45])
            ht_a  = len([g for g in away_goals if (g['minute'] or 0) <= 45])
            sh_h  = home_score - ht_h
            sh_a  = away_score - ht_a
            first = sorted(home_goals + away_goals, key=lambda x: x['minute'] or 999)

            sec_header("First Half vs Second Half")
            c1, c2, c3, c4 = st.columns(4)
            with c1: st.markdown(stat_box(f"{ht_h}–{ht_a}", "Half Time"), unsafe_allow_html=True)
            with c2: st.markdown(stat_box(f"{sh_h}–{sh_a}", "Second Half"), unsafe_allow_html=True)
            with c3: st.markdown(stat_box("1st Half" if (ht_h+ht_a) >= (sh_h+sh_a) else "2nd Half", "Most Goals"), unsafe_allow_html=True)
            with c4:
                if first:
                    st.markdown(stat_box(f"{first[0]['minute']}'", f"First Goal · {first[0]['player']}"), unsafe_allow_html=True)

    # ── Form + stats ──
    sec_header("Form & Statistical Comparison")
    st.plotly_chart(chart_stats_comparison(home_name, away_name, hs, aws),
                    use_container_width=True, config={'displayModeBar': False})
    render_form_blocks(home_name, away_name, hs, aws)

    # ── Form momentum ──
    sec_header("Form Momentum")
    st.markdown('<div style="background:#0d1526;border-left:2px solid #1e3a5f;border-radius:0 10px 10px 0;padding:12px 16px;margin-bottom:16px;font-size:0.82rem;color:#4b5a75;line-height:1.7">Form momentum measures how confidently each team was playing going into this match — scored directly from recent results weighted by recency. A positive score boosts their predicted attacking output in the simulation.</div>', unsafe_allow_html=True)
    render_momentum_cards(home_name, away_name, sim)

    # ── Key factors ──
    render_key_factors(home_name, away_name, hs, aws, sim)

    # ── Prediction retrospective ──
    sec_header("What the Model Predicted")
    p1, pd_, p2 = sim['team1_win_pct'], sim['draw_pct'], sim['team2_win_pct']
    predicted_winner = (
        home_name if p1 > p2 and p1 > pd_
        else away_name if p2 > p1 and p2 > pd_
        else "a draw"
    )
    was_correct   = (predicted_winner == winner) or (predicted_winner == "a draw" and winner is None)
    acc_color     = '#4ade80' if was_correct else '#f87171'
    acc_text      = '✅ Correct prediction' if was_correct else '❌ Incorrect prediction'
    top_pred      = sim['top_scores'][0][0] if sim['top_scores'] else '—'
    score_correct = top_pred == actual_score

    st.markdown(f"""
    <div class="insight-box">
        The model gave <strong>{home_name}</strong> a <strong>{p1}% win probability</strong>,
        <strong>{away_name}</strong> <strong>{p2}%</strong>, with a <strong>{pd_}% draw chance</strong>.
        Elo ratings: <strong>{home_name} {sim.get('elo_home','-')}</strong> vs
        <strong>{away_name} {sim.get('elo_away','-')}</strong>.
        Most likely score predicted: <strong>{top_pred}</strong>.
        Actual result: <strong>{actual_score}</strong>. &nbsp;
        <span style="color:{acc_color};font-weight:700">{acc_text}</span>
        {'&nbsp;·&nbsp;<span style="color:#4ade80;font-weight:700">✅ Exact score predicted</span>' if score_correct else ''}
    </div>
    """, unsafe_allow_html=True)

    render_donut_with_boxes(home_name, away_name, p1, pd_, p2)
    render_confidence_meter(home_name, away_name, p1, pd_, p2)

    sec_header("Score Probability Heatmap")
    st.markdown('<div class="heatmap-wrap">', unsafe_allow_html=True)
    col1, col2 = st.columns([3, 1])
    with col1:
        st.plotly_chart(chart_score_heatmap(home_name, away_name,
            sim.get('score_dist', {}), actual_score),
            use_container_width=True, config={'displayModeBar': False})
    with col2:
        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
        st.markdown(f"""
        <div style="font-size:0.72rem;color:#3d4f6b;line-height:1.8">
            Each cell shows the probability of that exact scoreline across 50,000 simulations.<br><br>
            <span style="color:#e2e8f0;font-weight:700">Columns</span> = {home_name} goals<br>
            <span style="color:#e2e8f0;font-weight:700">Rows</span> = {away_name} goals<br><br>
            Brighter = more likely.<br><br>
            {'<span style="color:#4ade80;font-weight:700">✓ Green border = actual result</span>' if actual_score else ''}
        </div>
        """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ── UPCOMING MATCH ─────────────────────────────────────────────────────────
def show_upcoming_match(m, data):
    sim = data['simulation']
    hs  = data['home_stats']
    aws = data['away_stats']
    home_name = data.get('home_name', m['home'])
    away_name = data.get('away_name', m['away'])

    c1_color = get_team_color(home_name, other_team=away_name)
    c2_color = get_team_color(away_name, other_team=home_name)
    p1, pd_, p2 = sim['team1_win_pct'], sim['draw_pct'], sim['team2_win_pct']
    xg1, xg2   = sim['team1_xg'], sim['team2_xg']

    st.markdown(f"""
    <div class="match-hero" style="border-top:3px solid {c1_color}">
        <div class="hero-meta">{fmt_stage(m['stage'])} · {fmt_date_local(m['date'])}</div>
        <div class="hero-teams">{home_name} <span class="hero-vs">vs</span> {away_name}</div>
        <div style="margin-top:8px;color:#3d4f6b;font-size:0.82rem">
            Elo: <span style="color:#94a3b8;font-weight:700">{home_name} {sim.get('elo_home','-')}</span>
            &nbsp;·&nbsp;
            <span style="color:#94a3b8;font-weight:700">{away_name} {sim.get('elo_away','-')}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    sec_header("Win Probability · 50,000 Simulations")
    render_donut_with_boxes(home_name, away_name, p1, pd_, p2)
    render_confidence_meter(home_name, away_name, p1, pd_, p2)

    sec_header("Expected Goals (xG)")
    col1, col2 = st.columns(2)
    with col1: st.markdown(stat_box(xg1, f"{home_name} xG"), unsafe_allow_html=True)
    with col2: st.markdown(stat_box(xg2, f"{away_name} xG"), unsafe_allow_html=True)
    total_xg = xg1 + xg2 if (xg1 + xg2) > 0 else 1
    st.markdown(f"""
    <div style="display:flex;border-radius:6px;overflow:hidden;height:6px;margin:8px 0 4px 0">
        <div style="width:{xg1/total_xg*100}%;background:{c1_color}"></div>
        <div style="width:{xg2/total_xg*100}%;background:{c2_color}"></div>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:0.65rem;color:#3d4f6b;margin-bottom:8px">
        <span>{home_name}</span><span>{away_name}</span>
    </div>
    """, unsafe_allow_html=True)

    sec_header("Score Probability Heatmap")
    st.markdown('<div class="heatmap-wrap">', unsafe_allow_html=True)
    col1, col2 = st.columns([3, 1])
    with col1:
        st.plotly_chart(chart_score_heatmap(home_name, away_name, sim.get('score_dist', {})),
                        use_container_width=True, config={'displayModeBar': False})
    with col2:
        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
        st.markdown(f"""
        <div style="font-size:0.72rem;color:#3d4f6b;line-height:1.8">
            Each cell shows the probability of that exact scoreline across 50,000 simulations.<br><br>
            <span style="color:#e2e8f0;font-weight:700">Columns</span> = {home_name} goals<br>
            <span style="color:#e2e8f0;font-weight:700">Rows</span> = {away_name} goals<br><br>
            Brighter = more likely.
        </div>
        """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    sec_header("Form & Statistical Comparison")
    st.plotly_chart(chart_stats_comparison(home_name, away_name, hs, aws),
                    use_container_width=True, config={'displayModeBar': False})
    render_form_blocks(home_name, away_name, hs, aws)

    sec_header("Form Momentum")
    st.markdown('<div style="background:#0d1526;border-left:2px solid #1e3a5f;border-radius:0 10px 10px 0;padding:12px 16px;margin-bottom:16px;font-size:0.82rem;color:#4b5a75;line-height:1.7">Form momentum scores each team\'s recent run of results weighted by recency — a positive score boosts their predicted attacking output in the simulation.</div>', unsafe_allow_html=True)
    render_momentum_cards(home_name, away_name, sim)

    render_key_factors(home_name, away_name, hs, aws, sim)

    sec_header("AI Insight")
    stronger     = home_name if p1 > p2 else away_name
    stronger_pct = max(p1, p2)
    st.markdown(f"""
    <div class="insight-box">
        <strong>{home_name}</strong> (Elo {sim.get('elo_home','-')}) vs
        <strong>{away_name}</strong> (Elo {sim.get('elo_away','-')}).
        Elo-based win probability: <strong>{sim.get('elo_win_prob','-')}%</strong> for {home_name}.
        After applying form momentum, defensive strength, and attacking output,
        the full model gives <strong>{stronger}</strong> a <strong>{stronger_pct}%</strong> win probability
        across 50,000 simulations, with an expected <strong>{xg1} – {xg2}</strong> scoreline.
        Most likely result: <strong>{sim['top_scores'][0][0]}</strong> ({sim['top_scores'][0][1]}% of simulations).
    </div>
    """, unsafe_allow_html=True)

# ── MATCH ROUTER ───────────────────────────────────────────────────────────
def show_match():
    m = st.session_state.selected_match
    if not m:
        st.session_state.page = 'home'
        st.rerun()

    if st.button("← Back to fixtures"):
        st.session_state.page = 'home'
        st.rerun()

    with st.spinner("Loading match data..."):
        try:
            r = requests.get(
                f"{BACKEND}/match/{m['home_id']}/{m['away_id']}",
                timeout=20
            )
            data = r.json()
        except:
            st.error("Failed to load match data.")
            return

    if m['status'] == 'FINISHED':
        show_finished_match(m, data)
    else:
        show_upcoming_match(m, data)

# ── ROUTER ─────────────────────────────────────────────────────────────────
if st.session_state.page == 'home':
    show_home()
elif st.session_state.page == 'match':
    show_match()
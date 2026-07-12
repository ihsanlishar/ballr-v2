import os
import json
import time
import threading
import requests
from dotenv import load_dotenv

from elo import get_elo, AVERAGE_ELO

load_dotenv()

API_KEY = os.getenv('FOOTBALL_DATA_API_KEY')
SERPAPI_KEY = os.getenv('SERPAPI_KEY')
BASE_URL = 'https://api.football-data.org/v4'
HEADERS = {'X-Auth-Token': API_KEY}

# ── Single-flight TTL cache ──────────────────────────────────────────────────
# football-data.org's free tier caps requests per minute. A plain TTL cache
# (the old approach) only prevents *repeat* calls once something is cached —
# it does nothing to stop a "cache stampede": if the cache is cold or has
# just expired and 6+ people load the page in the same second, every one of
# them sees a cache miss and fires its own upstream call simultaneously,
# blowing through the rate limit instantly. This wraps each cache-miss in a
# per-key lock, so the first caller fetches while everyone else waiting on
# that same key blocks briefly and then reuses that one result — turning a
# burst of N simultaneous requests into exactly 1 upstream call.
#
# It also falls back to the last good cached value if the upstream call
# fails (e.g. a 429 rate-limit response) instead of raising — so a brief
# rate-limit hit shows slightly stale data rather than a blank page.
def singleflight_ttl_cache(ttl):
    def decorator(func):
        store = {}                       # key -> (value, expires_at)
        locks = {}                       # key -> threading.Lock
        locks_guard = threading.Lock()   # protects the `locks` dict itself

        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))

            entry = store.get(key)
            if entry and entry[1] > time.time():
                return entry[0]

            with locks_guard:
                key_lock = locks.setdefault(key, threading.Lock())

            with key_lock:
                # Re-check after acquiring the lock — another thread may have
                # already refreshed this key while we were waiting on it.
                entry = store.get(key)
                if entry and entry[1] > time.time():
                    return entry[0]
                try:
                    value = func(*args, **kwargs)
                    store[key] = (value, time.time() + ttl)
                    return value
                except Exception:
                    if entry:
                        return entry[0]  # serve stale data rather than fail
                    raise  # nothing cached at all yet — nothing to fall back to

        wrapper.cache_clear = lambda: store.clear()
        return wrapper
    return decorator

# ── Goal scorer cache: permanent, disk-backed ────────────────────────────────
# A finished match's goal scorers never change, so there's no reason to ever
# expire this — and no reason to lose it on every restart/redeploy either.
# Instead of an in-memory TTLCache (which resets to empty every time the
# process restarts, silently re-triggering SerpAPI calls), this cache is
# written to a JSON file so it survives restarts within the same container.
#
# Note: if your host uses an ephemeral filesystem across *redeploys*
# (Railway's free/hobby tier does, unless you attach a persistent volume),
# this file will still reset on redeploy — but it protects you from the far
# more common case of simple process restarts/crashes.
EVENTS_CACHE_FILE = os.path.join(os.path.dirname(__file__), 'match_events_cache.json')
_events_cache_lock = threading.Lock()

def _load_events_cache():
    try:
        with open(EVENTS_CACHE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_events_cache(cache_dict):
    # Write to a temp file then atomically replace, so a crash mid-write
    # can't corrupt the cache file.
    tmp_path = EVENTS_CACHE_FILE + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(cache_dict, f)
    os.replace(tmp_path, EVENTS_CACHE_FILE)

_events_disk_cache = _load_events_cache()

COMP_WEIGHTS = {
    'FIFA World Cup':           1.0,
    'UEFA Champions League':    0.90,
    'UEFA Europa League':       0.75,
    'European Championship':    0.95,
    'Primera Division':         0.85,
    'Premier League':           0.85,
    'Bundesliga':               0.85,
    'Serie A':                  0.85,
    'Ligue 1':                  0.85,
    'Eredivisie':               0.75,
    'Primeira Liga':            0.75,
    'Championship':             0.60,
    'Copa Libertadores':        0.80,
}
DEFAULT_COMP_WEIGHT = 0.65

# ── Recent defensive form boost ──────────────────────────────────────────────
# As competition gets more elite (knockout rounds), a team's most recent
# defensive form is a better predictor of how they'll defend NOW than their
# average across all their matches — teams sit deeper, take fewer risks, and
# tighten up compared to earlier group-stage matches. The existing recency
# weighting (0.85 ** i) already favors recent games generally; this adds an
# EXTRA boost specifically to the defensive side (goals conceded, clean
# sheets) for a team's most recent matches, on top of that existing decay.
# Does not touch the attacking side (goals scored) — this is specifically
# about defensive solidity trending recently, not general form.
#
# WINDOW SIZE — confirmed via backtest (see backtest_defense_boost.py) that
# football-data.org's free tier only returns THIS tournament's matches per
# team (group stage + whatever knockout rounds have happened), so most
# national teams have only 4-5 total finished matches on record at this
# point in the competition. A window of 5 (the original value) covered
# literally 100% of every team's data, which made the boost a mathematical
# no-op — scaling every weight in a weighted average by the same factor
# doesn't change the result at all. Set below the typical sample size so a
# genuine "most recent N" vs. "the rest" split actually exists.
RECENT_DEFENSE_WINDOW = 3   # how many of the most recent matches get the boost
RECENT_DEFENSE_BOOST  = 0.5 # +50% extra weight on defensive metrics within that window

# ── Opponent-strength (goals quality) adjustment ─────────────────────────────
# A goal's value as a signal of true attacking/defensive quality depends on
# who it was scored against. Norway's 7 goals against Iraq shouldn't count
# the same as 7 against France. We already have Elo ratings (elo.py, now
# live-scraped), so we reuse them here to reweight each historical match's
# goals-for and goals-against contribution by opponent strength, on top of
# the existing competition/recency weighting.
#
# QUALITY_SCALE controls how strong the effect is: at the cap (an opponent
# 400 Elo points — roughly a bottom-tier vs top-tier gap — above or below
# average), goals-for weight moves by ±QUALITY_SCALE and goals-against
# weight moves by the mirror amount in the opposite direction. Capped so a
# single extreme mismatch (e.g. a friendly against a very weak side) can't
# dominate a team's whole rolling average.
QUALITY_SCALE = 0.35
QUALITY_ELO_CAP = 400  # Elo points, symmetric around AVERAGE_ELO

def _goal_quality_multipliers(opponent_name):
    """
    Returns (gf_multiplier, ga_multiplier) for a match against opponent_name.
    - Strong opponent (Elo above average): gf weighted UP, ga weighted DOWN
      (goals scored against a good team mean more; goals conceded to a good
      team are less damning).
    - Weak opponent: the reverse.
    Neutral (average-strength opponent) => both multipliers are 1.0.
    """
    opp_elo = get_elo(opponent_name)
    diff = max(-QUALITY_ELO_CAP, min(opp_elo - AVERAGE_ELO, QUALITY_ELO_CAP))
    strength_factor = diff / QUALITY_ELO_CAP  # range: -1.0 to 1.0

    gf_multiplier = 1 + strength_factor * QUALITY_SCALE
    ga_multiplier = 1 - strength_factor * QUALITY_SCALE
    return gf_multiplier, ga_multiplier

@singleflight_ttl_cache(ttl=300)
def get_fixtures():
    r = requests.get(f'{BASE_URL}/competitions/WC/matches', headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json().get('matches', [])

@singleflight_ttl_cache(ttl=300)
def get_team_stats(team_id):
    r = requests.get(
        f'{BASE_URL}/teams/{team_id}/matches?limit=20&status=FINISHED',
        headers=HEADERS, timeout=15
    )
    r.raise_for_status()
    return r.json()

@singleflight_ttl_cache(ttl=300)
def get_standings():
    r = requests.get(f'{BASE_URL}/competitions/WC/standings', headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

@singleflight_ttl_cache(ttl=300)
def get_top_scorers():
    r = requests.get(f'{BASE_URL}/competitions/WC/scorers', headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

def parse_team_form(matches_data, team_id, apply_recent_defense_boost=True):
    """
    apply_recent_defense_boost: when True (default), a team's most recent
    RECENT_DEFENSE_WINDOW matches get extra weight specifically on the
    defensive metrics (conceded_per_game, clean_sheet_rate). Exposed as a
    toggle so old vs. new behavior can be A/B compared directly (see
    backtest_defense_boost.py) rather than just trusted on faith.
    """
    matches  = matches_data.get('matches', [])
    finished = [m for m in matches if m['status'] == 'FINISHED']
    finished = sorted(finished, key=lambda m: m['utcDate'], reverse=True)

    if not finished:
        return _default_stats()

    results              = []
    weighted_gf          = []
    weighted_ga          = []
    raw_gf               = []
    total_weight_gf      = 0
    total_weight_ga      = 0
    weighted_clean_sheets = 0.0

    for i, m in enumerate(finished):
        home = m['homeTeam']['id'] == team_id
        score = m['score']['fullTime']
        gf = score['home'] if home else score['away']
        ga = score['away'] if home else score['home']
        if gf is None or ga is None:
            continue

        opponent_name = m['awayTeam']['name'] if home else m['homeTeam']['name']

        comp_name = m.get('competition', {}).get('name', '')
        comp_w    = COMP_WEIGHTS.get(comp_name, DEFAULT_COMP_WEIGHT)
        recency_w = 0.85 ** i
        base_weight = comp_w * recency_w

        gf_quality_mult, ga_quality_mult = _goal_quality_multipliers(opponent_name)
        gf_weight = base_weight * gf_quality_mult
        ga_weight = base_weight * ga_quality_mult

        if apply_recent_defense_boost and i < RECENT_DEFENSE_WINDOW:
            ga_weight *= (1 + RECENT_DEFENSE_BOOST)

        total_weight_gf += gf_weight
        total_weight_ga += ga_weight

        weighted_gf.append(gf * gf_weight)
        weighted_ga.append(ga * ga_weight)
        raw_gf.append(gf)

        if ga == 0:
            weighted_clean_sheets += ga_weight

        if gf > ga:   results.append('W')
        elif gf == ga: results.append('D')
        else:          results.append('L')

    if not results or total_weight_gf == 0 or total_weight_ga == 0:
        return _default_stats()

    n   = len(results)
    wpg = sum(weighted_gf) / total_weight_gf
    cpg = sum(weighted_ga) / total_weight_ga
    # Weighted clean sheet rate — uses the same (quality + recency +
    # defense-boost) weights as conceded_per_game, rather than a flat
    # count/n, so a recent clean sheet against a strong side counts more
    # than an old one against a weak side.
    clean_sheet_rate = weighted_clean_sheets / total_weight_ga

    # WC-only form for display
    wc_matches = [m for m in finished
                  if m.get('competition', {}).get('name') == 'FIFA World Cup']
    wc_form = []
    for m in wc_matches[:5]:
        home = m['homeTeam']['id'] == team_id
        score = m['score']['fullTime']
        gf = score['home'] if home else score['away']
        ga = score['away'] if home else score['home']
        if gf is None or ga is None: continue
        if gf > ga:    wc_form.append('W')
        elif gf == ga: wc_form.append('D')
        else:          wc_form.append('L')

    wins  = results.count('W')
    draws = results.count('D')
    losses = results.count('L')

    return {
        'wins':                wins,
        'draws':               draws,
        'losses':              losses,
        'played':              n,
        'win_rate':            round(wins / n, 3),
        'goals_per_game':      round(wpg, 3),
        'goals_per_game_raw':  round(sum(raw_gf) / len(raw_gf), 3),
        'conceded_per_game':   round(cpg, 3),
        'clean_sheet_rate':    round(clean_sheet_rate, 3),
        'gd_per_game':         round(wpg - cpg, 3),
        'form_string':         ''.join(results[:5]),
        'wc_form':             ''.join(wc_form) or ''.join(results[:5]),
        'sample_size':         n,
    }

def _default_stats():
    return {
        'wins': 0, 'draws': 0, 'losses': 0, 'played': 0,
        'win_rate': 0.33, 'goals_per_game': 1.2, 'goals_per_game_raw': 1.2,
        'conceded_per_game': 1.2, 'clean_sheet_rate': 0.2,
        'gd_per_game': 0.0, 'form_string': '', 'wc_form': '',
        'sample_size': 0,
    }

def _fuzzy_team_match(label, team_name):
    """True if label and team_name plausibly refer to the same team, even
    if formatted slightly differently (e.g. Google adding extra words)."""
    a = (label or '').lower().strip()
    b = (team_name or '').lower().strip()
    if not a or not b:
        return False
    return a == b or a in b or b in a

def get_match_events(home_team, away_team):
    """
    Fetch goal scorers from Google via SerpAPI.
    Cached permanently to disk — a finished match's scorers never change, so
    once we have a good result there's no reason to ever re-fetch it, even
    across restarts. Failed/empty lookups are NOT cached, so a match whose
    data hasn't appeared on Google yet will simply be retried next time.

    Returns fixed 'home'/'away' keys (in addition to the original
    Google-labeled keys, kept for reference) — the caller should use
    events['home']/events['away'], NOT look up by team name. Matching
    Google's own team label against our team name via exact string
    equality was fragile (any formatting difference between the two
    sources would silently break the lookup); this resolves home/away via
    fuzzy substring matching, with a positional fallback (Google's own
    team order) if fuzzy matching can't confidently tell them apart.
    """
    cache_key = f"{home_team}|{away_team}"

    with _events_cache_lock:
        if cache_key in _events_disk_cache:
            return _events_disk_cache[cache_key]

    if not SERPAPI_KEY:
        return None

    try:
        r = requests.get(
            'https://serpapi.com/search.json',
            params={
                'q': f"{home_team} vs {away_team} 2026 World Cup",
                'api_key': SERPAPI_KEY,
                'engine': 'google',
                'device': 'desktop'
            },
            timeout=10
        )
        data = r.json()
        spotlight = data.get('sports_results', {}).get('game_spotlight', {})
        if not spotlight:
            return None

        result = {}
        team_blocks = []  # [(google_label, team_data), ...] in Google's own order

        for team in spotlight.get('teams', []):
            name  = team.get('name', '')
            goals = []
            for scorer in team.get('goal_summary', []):
                player = scorer.get('player', {}).get('name', '')
                for g in scorer.get('goals', []):
                    minute = g.get('in_game_time', {}).get('minute')
                    goals.append({'player': player, 'minute': minute})

            red_cards = []
            for card in team.get('red_cards_summary', []):
                player = card.get('player', {}).get('name', '')
                for c in card.get('cards', []):
                    minute = c.get('in_game_time', {}).get('minute')
                    red_cards.append({'player': player, 'minute': minute})

            team_data = {
                'goals':     sorted(goals, key=lambda x: x['minute'] or 0),
                'red_cards': red_cards,
            }
            result[name] = team_data  # kept for reference/debugging
            team_blocks.append((name, team_data))

        # Resolve home/away via fuzzy name matching first.
        home_block = next((td for label, td in team_blocks if _fuzzy_team_match(label, home_team)), None)
        away_block = next((td for label, td in team_blocks if _fuzzy_team_match(label, away_team)), None)

        # Fallback: if fuzzy matching didn't confidently resolve both sides,
        # trust Google's own listed order (this is what the old code
        # silently assumed everywhere, just made explicit here as a
        # fallback rather than the primary strategy).
        if home_block is None and len(team_blocks) > 0:
            home_block = team_blocks[0][1]
        if away_block is None and len(team_blocks) > 1:
            away_block = team_blocks[1][1]

        result['home'] = home_block or {'goals': [], 'red_cards': []}
        result['away'] = away_block or {'goals': [], 'red_cards': []}
        result['venue'] = spotlight.get('venue', '')
        result['stage'] = spotlight.get('stage', '')

        with _events_cache_lock:
            _events_disk_cache[cache_key] = result
            _save_events_cache(_events_disk_cache)

        return result

    except Exception:
        return None
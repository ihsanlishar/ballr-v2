import os
import requests
from cachetools import TTLCache, cached
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv('FOOTBALL_DATA_API_KEY')
SERPAPI_KEY = os.getenv('SERPAPI_KEY')
BASE_URL = 'https://api.football-data.org/v4'
HEADERS = {'X-Auth-Token': API_KEY}

# Standard cache — 5 min TTL
cache = TTLCache(maxsize=128, ttl=300)

# Goal scorer cache — 24hr TTL (never waste SerpAPI calls)
events_cache = TTLCache(maxsize=128, ttl=86400)

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

@cached(cache)
def get_fixtures():
    r = requests.get(f'{BASE_URL}/competitions/WC/matches', headers=HEADERS)
    return r.json().get('matches', [])

@cached(cache)
def get_team_stats(team_id):
    r = requests.get(
        f'{BASE_URL}/teams/{team_id}/matches?limit=20&status=FINISHED',
        headers=HEADERS
    )
    return r.json()

@cached(cache)
def get_standings():
    r = requests.get(f'{BASE_URL}/competitions/WC/standings', headers=HEADERS)
    return r.json()

@cached(cache)
def get_top_scorers():
    r = requests.get(f'{BASE_URL}/competitions/WC/scorers', headers=HEADERS)
    return r.json()

def parse_team_form(matches_data, team_id):
    matches  = matches_data.get('matches', [])
    finished = [m for m in matches if m['status'] == 'FINISHED']
    finished = sorted(finished, key=lambda m: m['utcDate'], reverse=True)

    if not finished:
        return _default_stats()

    results        = []
    weighted_gf    = []
    weighted_ga    = []
    clean_sheets   = 0
    total_weight   = 0

    for i, m in enumerate(finished):
        home = m['homeTeam']['id'] == team_id
        score = m['score']['fullTime']
        gf = score['home'] if home else score['away']
        ga = score['away'] if home else score['home']
        if gf is None or ga is None:
            continue

        comp_name = m.get('competition', {}).get('name', '')
        comp_w    = COMP_WEIGHTS.get(comp_name, DEFAULT_COMP_WEIGHT)
        recency_w = 0.85 ** i
        weight    = comp_w * recency_w
        total_weight += weight

        weighted_gf.append(gf * weight)
        weighted_ga.append(ga * weight)

        if ga == 0:
            clean_sheets += 1

        if gf > ga:   results.append('W')
        elif gf == ga: results.append('D')
        else:          results.append('L')

    if not results or total_weight == 0:
        return _default_stats()

    n   = len(results)
    wpg = sum(weighted_gf) / total_weight
    cpg = sum(weighted_ga) / total_weight

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
        'wins':              wins,
        'draws':             draws,
        'losses':            losses,
        'played':            n,
        'win_rate':          round(wins / n, 3),
        'goals_per_game':    round(wpg, 3),
        'conceded_per_game': round(cpg, 3),
        'clean_sheet_rate':  round(clean_sheets / n, 3),
        'gd_per_game':       round(wpg - cpg, 3),
        'form_string':       ''.join(results[:5]),
        'wc_form':           ''.join(wc_form) or ''.join(results[:5]),
        'sample_size':       n,
    }

def _default_stats():
    return {
        'wins': 0, 'draws': 0, 'losses': 0, 'played': 0,
        'win_rate': 0.33, 'goals_per_game': 1.2,
        'conceded_per_game': 1.2, 'clean_sheet_rate': 0.2,
        'gd_per_game': 0.0, 'form_string': '', 'wc_form': '',
        'sample_size': 0,
    }

@cached(events_cache)
def get_match_events(home_team, away_team):
    """Fetch goal scorers from Google via SerpAPI. Cached 24hrs."""
    try:
        if not SERPAPI_KEY:
            return None
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

            result[name] = {
                'goals':     sorted(goals, key=lambda x: x['minute'] or 0),
                'red_cards': red_cards,
            }

        result['venue'] = spotlight.get('venue', '')
        result['stage'] = spotlight.get('stage', '')
        return result

    except:
        return None
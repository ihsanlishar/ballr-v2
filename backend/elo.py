import os
import json
import time
import threading
import requests

# ── Static fallback Elo ratings (World Cup 2026, June 2026 snapshot) ────────
# Used in two cases: (1) the live scrape has never succeeded yet on this
# deployment, or (2) a team name comes back from the scrape that we can't
# confidently map to a canonical name (see NAME_MAP below) — in that case we
# keep serving this team's static value rather than risk mixing in a
# mismatched rating under the wrong key.
ELO_RATINGS = {
    'France':               2003,
    'Spain':                1983,
    'England':              1953,
    'Portugal':             1942,
    'Brazil':               1934,
    'Argentina':            1928,
    'Netherlands':          1912,
    'Germany':              1898,
    'Belgium':              1871,
    'Colombia':             1858,
    'Uruguay':              1845,
    'Mexico':               1820,
    'United States':        1798,
    'Morocco':              1790,
    'Japan':                1784,
    'Senegal':              1756,
    'Croatia':              1748,
    'Switzerland':          1743,
    'Australia':            1728,
    'Norway':               1724,
    'Sweden':               1718,
    'Turkey':               1698,
    'Ecuador':              1672,
    'South Korea':          1665,
    'Canada':               1658,
    'Austria':              1645,
    'Ivory Coast':          1632,
    'Egypt':                1618,
    'Algeria':              1612,
    'Ghana':                1598,
    'Iran':                 1587,
    'Paraguay':             1572,
    'Serbia':               1568,
    'South Africa':         1542,
    'Tunisia':              1538,
    'Poland':               1534,
    'Qatar':                1498,
    'Saudi Arabia':         1487,
    'Czechia':              1482,
    'Panama':               1463,
    'Bosnia-Herzegovina':   1458,
    'Scotland':             1452,
    'Jordan':               1438,
    'New Zealand':          1412,
    'Iraq':                 1398,
    'Haiti':                1372,
    'Cape Verde Islands':   1368,
    'Curaçao':              1342,
    'Uzbekistan':           1338,
    'Congo DR':             1402,
}

AVERAGE_ELO = 1600

# ── Country code reconciliation ──────────────────────────────────────────────
# Confirmed by live testing: eloratings.net's World.tsv identifies teams by a
# 2-letter code (column index 2), NOT a full name — e.g. row 1 was
# '1  1  ES  2177  ...' where 'ES' is Spain and 2177 is the rating. This maps
# each code to this app's canonical team name. Almost all of these are
# standard ISO 3166-1 alpha-2 codes; England and Scotland are NOT real ISO
# countries (the UK is one ISO entry, 'GB'), so eloratings.net uses its own
# codes for those — confirmed 'EN' = England from live data; 'SC' for
# Scotland is a reasonable same-pattern guess but NOT yet independently
# confirmed. Scoped to just this tournament's 48 teams rather than every
# country in the world, since that's all this app needs.
#
# Any code that comes back from the scrape but ISN'T in this map is skipped
# entirely (see _normalize_name) — that team simply keeps its static
# fallback rating rather than risk being silently dropped or mismatched.
CODE_TO_NAME = {
    'FR': 'France',
    'ES': 'Spain',
    'EN': 'England',
    'PT': 'Portugal',
    'BR': 'Brazil',
    'AR': 'Argentina',
    'NL': 'Netherlands',
    'DE': 'Germany',
    'BE': 'Belgium',
    'CO': 'Colombia',
    'UY': 'Uruguay',
    'MX': 'Mexico',
    'US': 'United States',
    'MA': 'Morocco',
    'JP': 'Japan',
    'SN': 'Senegal',
    'HR': 'Croatia',
    'CH': 'Switzerland',
    'AU': 'Australia',
    'NO': 'Norway',
    'SE': 'Sweden',
    'TR': 'Turkey',
    'EC': 'Ecuador',
    'KR': 'South Korea',
    'CA': 'Canada',
    'AT': 'Austria',
    'CI': 'Ivory Coast',
    'EG': 'Egypt',
    'DZ': 'Algeria',
    'GH': 'Ghana',
    'IR': 'Iran',
    'PY': 'Paraguay',
    'RS': 'Serbia',
    'ZA': 'South Africa',
    'TN': 'Tunisia',
    'PL': 'Poland',
    'QA': 'Qatar',
    'SA': 'Saudi Arabia',
    'CZ': 'Czechia',
    'PA': 'Panama',
    'BA': 'Bosnia-Herzegovina',
    'SC': 'Scotland',  # unconfirmed — same-pattern guess, verify against live output
    'JO': 'Jordan',
    'NZ': 'New Zealand',
    'IQ': 'Iraq',
    'HT': 'Haiti',
    'CV': 'Cape Verde Islands',
    'CW': 'Curaçao',
    'UZ': 'Uzbekistan',
    'CD': 'Congo DR',
}


def _normalize_name(raw_code):
    """Map a scraped team code to this app's canonical name, or None if
    there's no confident mapping (caller should skip it rather than guess)."""
    return CODE_TO_NAME.get(raw_code.strip())


def _parse_world_tsv(text):
    """
    Parse eloratings.net's World.tsv into {canonical_team_name: rating}.

    Confirmed by live testing: tab-separated, no header row, 2-letter team
    code in column index 2 (e.g. 'ES', 'AR', 'FR') and current rating in
    column index 3 (0-indexed). Defensive by design — any row that doesn't
    parse cleanly is skipped rather than allowed to throw or insert garbage.
    """
    ratings = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        cols = line.split('\t')
        if len(cols) < 4:
            continue

        name = _normalize_name(cols[2])
        if name is None:
            continue  # unmapped code — leave this team on its static fallback

        try:
            rating = float(cols[3])
        except ValueError:
            continue

        # Sanity bound — real Elo ratings for national teams sit well within
        # this range. Anything outside it means we've misread the column
        # layout (e.g. site changed format), so skip rather than trust it.
        if not (500 <= rating <= 2600):
            continue

        ratings[name] = round(rating)

    return ratings

# ── Live ratings cache (disk-backed, 6-hour TTL) ─────────────────────────────
# Timer-based rather than event-driven on purpose: it reuses the same
# lock-and-cache pattern already proven in football_api.py, and a knockout
# round's matches are hours apart at minimum — a 6-hour refresh window will
# always have picked up a finished match's new rating well before the next
# one kicks off. This trades a small amount of freshness for a lot fewer
# moving parts / failure modes than hooking into match-finished events.
ELO_CACHE_FILE = os.path.join(os.path.dirname(__file__), 'elo_live_cache.json')
ELO_TTL_SECONDS = 6 * 60 * 60  # 6 hours
ELO_SOURCE_URL = 'https://www.eloratings.net/World.tsv'

_elo_cache_lock = threading.Lock()
_live_ratings_memo = None       # in-process memo so we don't re-read disk every call
_live_ratings_memo_time = 0.0


def _load_elo_cache_from_disk():
    try:
        with open(ELO_CACHE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_elo_cache_to_disk(cache_dict):
    tmp_path = ELO_CACHE_FILE + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(cache_dict, f)
    os.replace(tmp_path, ELO_CACHE_FILE)


def _scrape_live_ratings():
    """Fetch and parse the live ratings file. Raises on any failure —
    callers are responsible for catching and falling back."""
    resp = requests.get(ELO_SOURCE_URL, timeout=15)
    resp.raise_for_status()
    ratings = _parse_world_tsv(resp.text)

    # Require a plausible minimum number of successfully-parsed teams before
    # trusting this scrape at all — protects against a partial/garbled
    # response being treated as a full, valid ratings table.
    if len(ratings) < 20:
        raise ValueError(f'Only parsed {len(ratings)} teams from World.tsv — refusing to trust this scrape')

    return ratings


def get_live_elo_ratings():
    """
    Returns the best available {team_name: rating} dict:
    1. Fresh (< 6h old) in-process memo, if present — avoids disk I/O on
       every single call within the same request burst.
    2. Fresh disk cache, if present.
    3. A new scrape, on cache miss/expiry — falls back to stale disk cache
       or the static ELO_RATINGS dict if the scrape fails.

    Teams not present in the returned dict simply aren't overridden by the
    caller (get_elo falls back to ELO_RATINGS for those).
    """
    global _live_ratings_memo, _live_ratings_memo_time

    now = time.time()
    if _live_ratings_memo is not None and (now - _live_ratings_memo_time) < ELO_TTL_SECONDS:
        return _live_ratings_memo

    with _elo_cache_lock:
        # Re-check after acquiring lock — another thread may have refreshed.
        now = time.time()
        if _live_ratings_memo is not None and (now - _live_ratings_memo_time) < ELO_TTL_SECONDS:
            return _live_ratings_memo

        disk_cache = _load_elo_cache_from_disk()
        if disk_cache and (now - disk_cache.get('scraped_at', 0)) < ELO_TTL_SECONDS:
            _live_ratings_memo = disk_cache['ratings']
            _live_ratings_memo_time = disk_cache['scraped_at']
            return _live_ratings_memo

        try:
            fresh_ratings = _scrape_live_ratings()
            _save_elo_cache_to_disk({'ratings': fresh_ratings, 'scraped_at': now})
            _live_ratings_memo = fresh_ratings
            _live_ratings_memo_time = now
            return fresh_ratings
        except Exception:
            # Scrape failed — prefer stale disk cache over nothing, since
            # slightly-outdated live ratings are still better than falling
            # all the way back to the hardcoded static snapshot.
            if disk_cache and disk_cache.get('ratings'):
                _live_ratings_memo = disk_cache['ratings']
                _live_ratings_memo_time = disk_cache.get('scraped_at', now)
                return _live_ratings_memo
            # Nothing usable at all — signal callers to use ELO_RATINGS.
            return {}


def get_elo(team_name):
    """Get Elo rating for a team: live scrape if available for this team,
    otherwise the static fallback, otherwise the global average."""
    live = get_live_elo_ratings()
    if team_name in live:
        return live[team_name]
    return ELO_RATINGS.get(team_name, AVERAGE_ELO)


def elo_win_probability(elo_a, elo_b):
    """
    Expected win probability for team A vs team B.
    Standard Elo formula used in football analytics.
    """
    return 1 / (1 + 10 ** ((elo_b - elo_a) / 400))


def elo_strength_ratio(home_team, away_team):
    """
    Returns a multiplier for home team's attacking strength
    relative to away team based on Elo difference.
    Capped at ±20% so it doesn't dominate the prediction.
    """
    elo_h = get_elo(home_team)
    elo_a = get_elo(away_team)
    diff  = elo_h - elo_a

    # Every 100 Elo points = ~5% adjustment, capped at ±20%
    ratio = 1.0 + (diff / 100) * 0.05
    return max(0.80, min(ratio, 1.20))


if __name__ == '__main__':
    # Standalone diagnostic — run with `python elo.py` (needs real internet
    # access, so run this locally or via Railway's shell, not in a
    # network-restricted sandbox). Prints exactly what the scraper sees at
    # each stage, so a bad column-layout guess or a naming mismatch is
    # immediately visible instead of silently falling back to static data.
    print(f"Fetching: {ELO_SOURCE_URL}")
    try:
        resp = requests.get(ELO_SOURCE_URL, timeout=15)
        print(f"HTTP status: {resp.status_code}")
        print(f"Response length: {len(resp.text)} chars")

        raw_lines = resp.text.splitlines()
        print(f"\nFirst 5 raw lines (to sanity-check column layout):")
        for line in raw_lines[:5]:
            print(f"  {line!r}")

        parsed = _parse_world_tsv(resp.text)
        print(f"\nParsed {len(parsed)} teams successfully.")

        if len(parsed) < 20:
            print("WARNING: fewer than 20 teams parsed — this would trigger the "
                  "sanity check and fall back to static ratings in production. "
                  "The column layout (name=col index 2, rating=col index 3) is "
                  "likely wrong for this file. Check the raw lines printed above.")
        else:
            print("Looks healthy — sample of parsed ratings:")
            sample_teams = list(parsed.items())[:10]
            for name, rating in sample_teams:
                print(f"  {name}: {rating}")

        print(f"\nSpecific lookups:")
        for team in ['Switzerland', 'Colombia', 'Argentina', 'Egypt', 'France', 'Norway']:
            in_scrape = parsed.get(team)
            static    = ELO_RATINGS.get(team, AVERAGE_ELO)
            print(f"  {team}: scraped={in_scrape!r}  static_fallback={static}")

    except Exception as e:
        print(f"\nSCRAPE FAILED: {type(e).__name__}: {e}")
        print("This is exactly the failure mode that makes get_elo() silently "
              "fall back to the static ELO_RATINGS dict in production — safe, "
              "but means live updates aren't happening. Fix the underlying "
              "issue (URL, network, or column layout) and re-run.")

    print(f"\n--- Testing full get_elo() / get_live_elo_ratings() path ---")
    live = get_live_elo_ratings()
    print(f"get_live_elo_ratings() returned {len(live)} teams.")
    print(f"get_elo('Switzerland') = {get_elo('Switzerland')}")
    print(f"get_elo('Colombia')    = {get_elo('Colombia')}")
import os
import sys
import json
import datetime
import threading
from flask import Flask, jsonify
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

from football_api import (
    get_fixtures, get_team_stats, get_standings,
    get_top_scorers, parse_team_form, get_match_events
)
from monte_carlo import run_simulation

app = Flask(__name__)

# ── Permanent cache for match predictions ────────────────────────────────────
# A finished match's prediction inputs (team form, Elo, etc.) and the
# resulting simulation will never change again, so there's no reason to ever
# recompute them — every future viewer of that match, forever, should get
# the exact same instant response with zero additional football-data.org
# calls.
#
# As of this version, we ALSO freeze predictions for matches that haven't
# been played yet. Reason: get_team_stats() rolls forward as new matches
# finish (each team's "last 20 finished matches" window shifts), which was
# silently changing pre-match predictions on every page load even though
# nothing about the actual matchup changed. Now a not-yet-played match is
# predicted once and locked until it goes FINISHED, at which point it's
# refreshed exactly once with final data and locked permanently.
#
# IMPORTANT — backward compatibility with your existing cache file:
# Entries written by the previous version of this code have no 'status'
# key. We treat the presence of 'events' (which the old code only ever set
# for FINISHED matches) as proof that an old-format entry is already a
# genuine finished-match result, so it is NOT recomputed/overwritten. This
# means every prediction you've already generated and shown to users keeps
# displaying exactly as it does today — this change only governs behavior
# for matches predicted from now onward.
#
# This also does not change API call volume: get_fixtures() and
# get_team_stats() were already TTL-cached (single-flight, 5 min) before
# this change. All this layer avoids is redundant recomputation of
# run_simulation(), which is pure CPU and never called the API to begin
# with. Disk-backed so it survives restarts.
MATCH_CACHE_FILE = os.path.join(os.path.dirname(__file__), 'finished_match_cache.json')
_match_cache_lock = threading.Lock()

def _load_match_cache():
    try:
        with open(MATCH_CACHE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_match_cache(cache_dict):
    tmp_path = MATCH_CACHE_FILE + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(cache_dict, f)
    os.replace(tmp_path, MATCH_CACHE_FILE)

def _is_already_frozen(cached_entry):
    """
    True if this cache entry should never be recomputed again.

    - New-format entries: explicit status == 'FINISHED'.
    - Old-format entries (no 'status' key at all, from before this change):
      the old code only ever populated 'events' for FINISHED matches, so a
      non-None 'events' value proves it's a genuine finished result. This
      keeps every previously-generated prediction displaying exactly as it
      already does — nothing pre-existing gets recomputed or overwritten.
    """
    if cached_entry.get('status') == 'FINISHED':
        return True
    if 'status' not in cached_entry and cached_entry.get('events') is not None:
        return True
    return False

_finished_match_cache = _load_match_cache()

@app.route('/fixtures')
def fixtures():
    try:
        matches = get_fixtures()
    except Exception:
        # No fixtures cached anywhere yet and the upstream call failed (e.g.
        # rate-limited) — return an empty list rather than a 500, so the
        # frontend shows "no matches" instead of crashing outright.
        return jsonify([])

    result = []
    for m in matches:
        score    = m.get('score', {}) or {}
        duration = score.get('duration', 'REGULAR')
        reg      = score.get('regularTime') or score.get('fullTime') or {}
        extra    = score.get('extraTime') or {}
        pens     = score.get('penalties') or {}

        home_score = reg.get('home')
        away_score = reg.get('away')

        # If the match went to extra time (with or without a shootout), the
        # "played" score is regulation + extra time. The API's fullTime field
        # adds penalty goals on top of that for shootout matches, so we build
        # the real score from regularTime/extraTime instead of using fullTime
        # directly — otherwise penalty goals get counted as if they were
        # normal goals scored during the match.
        if duration in ('EXTRA_TIME', 'PENALTY_SHOOTOUT') and extra.get('home') is not None:
            home_score = (home_score or 0) + (extra.get('home') or 0)
            away_score = (away_score or 0) + (extra.get('away') or 0)

        result.append({
            'id':                 m['id'],
            'home':               m['homeTeam']['name'],
            'away':               m['awayTeam']['name'],
            'home_id':            m['homeTeam']['id'],
            'away_id':            m['awayTeam']['id'],
            'date':               m['utcDate'],
            'status':             m['status'],
            'home_score':         home_score,
            'away_score':         away_score,
            'went_to_penalties':  duration == 'PENALTY_SHOOTOUT',
            'home_penalties':     pens.get('home'),
            'away_penalties':     pens.get('away'),
            'winner':             score.get('winner'),
            'stage':              m['stage'],
        })
    return jsonify(result)

@app.route('/match/<int:home_id>/<int:away_id>')
def match(home_id, away_id):
    cache_key = f"{home_id}-{away_id}"

    # Figure out the match's current status first using fixtures — this is
    # cheap (fixtures is already cached and shared across all users) and
    # lets us decide whether a cached entry is safe to keep serving as-is.
    try:
        fixtures_list = get_fixtures()
    except Exception:
        fixtures_list = []

    match_info = next((
        f for f in fixtures_list
        if f['homeTeam']['id'] == home_id and f['awayTeam']['id'] == away_id
    ), None)
    if not match_info:
        match_info = next((
            f for f in fixtures_list
            if f['homeTeam']['id'] == away_id and f['awayTeam']['id'] == home_id
        ), None)

    current_status = match_info.get('status') if match_info else None

    with _match_cache_lock:
        cached = _finished_match_cache.get(cache_key)
        if cached is not None:
            # Serve the frozen snapshot unless the match has just gone
            # FINISHED and our cached copy was generated pre-match — that
            # one transition needs exactly one refresh to fold in the real
            # result and events. Already-frozen entries (old finished
            # results included) are never recomputed.
            if _is_already_frozen(cached) or current_status != 'FINISHED':
                return jsonify(cached)

    home_name = match_info['homeTeam']['name'] if match_info else None
    away_name = match_info['awayTeam']['name'] if match_info else None

    try:
        home_data = get_team_stats(home_id)
        away_data = get_team_stats(away_id)
    except Exception:
        # Upstream is failing and we have no fixtures-derived names either —
        # nothing sensible to compute. Return a clearly-empty response
        # rather than a 500 so the frontend can show a friendly message.
        return jsonify({
            'home_stats': None, 'away_stats': None, 'simulation': None,
            'events': None, 'home_name': home_name, 'away_name': away_name,
        })

    home_stats = parse_team_form(home_data, home_id)
    away_stats = parse_team_form(away_data, away_id)

    if not match_info:
        # Last resort — scan team match history
        home_name = str(home_id)
        away_name = str(away_id)
        for m in home_data.get('matches', []):
            if m['homeTeam']['id'] == home_id:
                home_name = m['homeTeam']['name']
                break
            elif m['awayTeam']['id'] == home_id:
                home_name = m['awayTeam']['name']
                break
        for m in away_data.get('matches', []):
            if m['homeTeam']['id'] == away_id:
                away_name = m['homeTeam']['name']
                break
            elif m['awayTeam']['id'] == away_id:
                away_name = m['awayTeam']['name']
                break

    # Group stage allows draws; every knockout round (Round of 32 through
    # the Final, including the third-place playoff) always produces a
    # winner via extra time / penalties, so those get win-vs-win-only
    # probabilities instead of a win/draw/win split.
    is_knockout = bool(match_info) and match_info.get('stage') != 'GROUP_STAGE'

    simulation = run_simulation(home_name, away_name, home_stats, away_stats, is_knockout=is_knockout)

    events = None
    if current_status == 'FINISHED':
        events = get_match_events(home_name, away_name)

    result = {
        'home_stats':        home_stats,
        'away_stats':        away_stats,
        'simulation':        simulation,
        'events':            events,
        'home_name':         home_name,
        'away_name':         away_name,
        'status':            current_status,
        'generated_at':      datetime.datetime.utcnow().isoformat() + 'Z',
        'prediction_locked': current_status != 'FINISHED',
    }

    with _match_cache_lock:
        _finished_match_cache[cache_key] = result
        _save_match_cache(_finished_match_cache)

    return jsonify(result)

@app.route('/standings')
def standings():
    try:
        return jsonify(get_standings())
    except Exception:
        return jsonify({})

@app.route('/top-scorers')
def top_scorers():
    try:
        return jsonify(get_top_scorers())
    except Exception:
        return jsonify({})

if __name__ == '__main__':
    app.run(
        debug=False,
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5002))
    )
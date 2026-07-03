import os
import sys
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

@app.route('/fixtures')
def fixtures():
    matches = get_fixtures()
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
    home_data = get_team_stats(home_id)
    away_data = get_team_stats(away_id)

    home_stats = parse_team_form(home_data, home_id)
    away_stats = parse_team_form(away_data, away_id)

    # Get names and status directly from fixtures
    fixtures   = get_fixtures()
    match_info = next((
        f for f in fixtures
        if f['homeTeam']['id'] == home_id and f['awayTeam']['id'] == away_id
    ), None)

    # If not found try reverse (for when called with away/home swapped)
    if not match_info:
        match_info = next((
            f for f in fixtures
            if f['homeTeam']['id'] == away_id and f['awayTeam']['id'] == home_id
        ), None)

    if match_info:
        home_name = match_info['homeTeam']['name']
        away_name = match_info['awayTeam']['name']
        status    = match_info.get('status')
    else:
        # Last resort — scan team match history
        home_name = str(home_id)
        away_name = str(away_id)
        status    = None
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

    simulation = run_simulation(home_name, away_name, home_stats, away_stats)

    events = None
    if status == 'FINISHED':
        events = get_match_events(home_name, away_name)

    return jsonify({
        'home_stats': home_stats,
        'away_stats': away_stats,
        'simulation': simulation,
        'events':     events,
        'home_name':  home_name,
        'away_name':  away_name,
    })

@app.route('/standings')
def standings():
    return jsonify(get_standings())

@app.route('/top-scorers')
def top_scorers():
    return jsonify(get_top_scorers())

if __name__ == '__main__':
    app.run(
        debug=False,
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5002))
    )
"""
Run this locally: python3 test_algorithm_ideas.py

Tests BOTH proposed ideas against real data BEFORE any production code
changes — same "prove it before you ship it" approach as the defense-boost
backtest. Uses your existing backtest_cache.json (fixtures + team stats),
so this makes ZERO new API calls, assuming that cache file is still
present and valid from earlier tonight.

If backtest_cache.json is missing, this will fall back to fetching fresh
(paced, same as backtest_defense_boost.py) — see that script's header if
you need to regenerate it.

IDEA #1 — Stage-based scoring dampening
Tests the PREMISE directly against real results: do knockout matches
(Round of 32, Round of 16 — the only knockout rounds finished so far)
actually show fewer goals per match than group stage? This is a pure data
comparison, no prediction math involved yet.

IDEA #2 — Wider Elo cap
Currently elo_strength_ratio() caps the Elo-based multiplier at ±20%.
Tests prediction accuracy against the 24 known knockout results at
several different cap values (15%, 20%, 25%, 30%, 35%) to see whether a
wider cap would have called more winners correctly, using the REAL
run_simulation() pipeline (temporarily patched to swap in each cap, then
restored) rather than a reimplementation — so results reflect actual
production behavior, not an approximation of it.
"""
import sys
import os
import json
import time
sys.path.insert(0, os.path.dirname(__file__))

from football_api import get_fixtures, get_team_stats, parse_team_form
import monte_carlo
import elo

REQUEST_DELAY_SECONDS = 7
BACKTEST_CACHE_FILE = os.path.join(os.path.dirname(__file__), 'backtest_cache.json')

def _load_backtest_cache():
    try:
        with open(BACKTEST_CACHE_FILE, 'r') as f:
            data = json.load(f)
            if not data.get('complete'):
                return None
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def _save_backtest_cache(cache_dict):
    cache_dict['complete'] = True
    tmp_path = BACKTEST_CACHE_FILE + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(cache_dict, f)
    os.replace(tmp_path, BACKTEST_CACHE_FILE)

_cache = _load_backtest_cache()

if _cache is not None:
    print(f"Using local cache — zero new API calls this run.\n")
    all_matches = _cache['fixtures']
    stats_cache = _cache['team_stats']
else:
    print("No valid local cache found — this run WILL call football-data.org, paced.\n")
    all_matches = get_fixtures()
    stats_cache = {}

finished_all = [m for m in all_matches if m['status'] == 'FINISHED']
knockout_finished = [m for m in finished_all if m['stage'] != 'GROUP_STAGE']
group_finished = [m for m in finished_all if m['stage'] == 'GROUP_STAGE']

print("=" * 60)
print("IDEA #1 — Does scoring actually drop in knockout matches?")
print("=" * 60)

def avg_goals(matches):
    totals = []
    for m in matches:
        h, a = m['score']['fullTime']['home'], m['score']['fullTime']['away']
        if h is not None and a is not None:
            totals.append(h + a)
    return (sum(totals) / len(totals), len(totals)) if totals else (0, 0)

group_avg, group_n = avg_goals(group_finished)
knockout_avg, knockout_n = avg_goals(knockout_finished)

# Break down by specific stage too, since LAST_32 and LAST_16 might differ
by_stage = {}
for m in knockout_finished:
    by_stage.setdefault(m['stage'], []).append(m)

print(f"Group stage:      {group_avg:.2f} goals/match  (n={group_n})")
print(f"All knockout:     {knockout_avg:.2f} goals/match  (n={knockout_n})")
for stage, matches in by_stage.items():
    avg, n = avg_goals(matches)
    print(f"  {stage}:  {avg:.2f} goals/match  (n={n})")

diff_pct = ((knockout_avg - group_avg) / group_avg * 100) if group_avg else 0
print(f"\nDifference: {diff_pct:+.1f}% ({'fewer' if diff_pct < 0 else 'more'} goals in knockout matches)")
if abs(diff_pct) < 5:
    print("VERDICT: Effect is small (<5%) in the data so far — dampening likely wouldn't")
    print("move predictions much. Sample size is also still fairly small (n={}).".format(knockout_n))
elif diff_pct < 0:
    print(f"VERDICT: Real drop observed — a dampening factor around {abs(diff_pct):.0f}% would be")
    print("data-justified, not guessed. Worth implementing.")
else:
    print("VERDICT: Knockout matches are NOT showing fewer goals in your actual data —")
    print("this premise doesn't hold up here. Don't implement dampening based on guesswork;")
    print("this specific dataset doesn't support it.")

print("\n" + "=" * 60)
print("IDEA #2 — Would a wider Elo cap have predicted more winners correctly?")
print("=" * 60)

def get_cached_team_data(team_id):
    key = str(team_id)
    if key in stats_cache:
        return stats_cache[key]
    time.sleep(REQUEST_DELAY_SECONDS)
    try:
        stats_cache[key] = get_team_stats(team_id)
    except Exception as e:
        if '429' in str(e):
            time.sleep(65)
            stats_cache[key] = get_team_stats(team_id)
        else:
            raise
    return stats_cache[key]

CAPS_TO_TEST = [0.15, 0.20, 0.25, 0.30, 0.35]  # 0.20 is current production value
original_elo_strength_ratio = monte_carlo.elo_strength_ratio

def make_capped_ratio(cap):
    def capped(home_team, away_team):
        elo_h = elo.get_elo(home_team)
        elo_a = elo.get_elo(away_team)
        diff = elo_h - elo_a
        ratio = 1.0 + (diff / 100) * 0.05
        return max(1 - cap, min(ratio, 1 + cap))
    return capped

results_by_cap = {}

for cap in CAPS_TO_TEST:
    monte_carlo.elo_strength_ratio = make_capped_ratio(cap)
    correct = 0
    total = 0
    for m in knockout_finished:
        home_id, away_id = m['homeTeam']['id'], m['awayTeam']['id']
        home_name, away_name = m['homeTeam']['name'], m['awayTeam']['name']
        score = m['score']['fullTime']
        if score['home'] is None or score['away'] is None:
            continue
        actual_winner = home_name if score['home'] > score['away'] else (
            away_name if score['away'] > score['home'] else 'Draw'
        )
        try:
            home_data = get_cached_team_data(home_id)
            away_data = get_cached_team_data(away_id)
        except Exception:
            continue

        home_stats = parse_team_form(home_data, home_id)
        away_stats = parse_team_form(away_data, away_id)
        sim = monte_carlo.run_simulation(home_name, away_name, home_stats, away_stats)

        p1, pd_, p2 = sim['team1_win_pct'], sim['draw_pct'], sim['team2_win_pct']
        predicted = (
            home_name if p1 > p2 and p1 > pd_
            else away_name if p2 > p1 and p2 > pd_
            else 'Draw'
        )
        total += 1
        if predicted == actual_winner:
            correct += 1

    acc = correct / total * 100 if total else 0
    results_by_cap[cap] = (correct, total, acc)
    marker = "  <- current production value" if cap == 0.20 else ""
    print(f"  Cap ±{int(cap*100)}%: {correct}/{total} correct ({acc:.1f}%){marker}")

monte_carlo.elo_strength_ratio = original_elo_strength_ratio  # restore

best_cap = max(results_by_cap, key=lambda c: results_by_cap[c][2])
best_acc = results_by_cap[best_cap][2]
current_acc = results_by_cap[0.20][2]

print(f"\nBest cap tested: ±{int(best_cap*100)}% ({best_acc:.1f}% accuracy)")
print(f"Current production (±20%): {current_acc:.1f}% accuracy")
if best_acc > current_acc:
    print(f"VERDICT: A wider cap (±{int(best_cap*100)}%) beat current production by "
          f"{best_acc - current_acc:.1f} points on this data. Worth implementing.")
elif best_acc == current_acc:
    print("VERDICT: No cap tested beat current production — widening the cap wouldn't help here.")
else:
    print("VERDICT: Current production cap already outperforms every alternative tested.")

if _cache is None:
    _save_backtest_cache({'fixtures': all_matches, 'team_stats': stats_cache})
    print(f"\nSaved fresh data to {BACKTEST_CACHE_FILE} — future runs will be free.")

print("\nReminder: small sample sizes (n={}) mean these are directional signals,".format(knockout_n))
print("not statistically certain conclusions — treat accordingly.")

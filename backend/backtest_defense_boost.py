"""
Run this locally: python3 backtest_defense_boost.py

Compares prediction accuracy WITH vs WITHOUT the recent-defense boost
(RECENT_DEFENSE_WINDOW / RECENT_DEFENSE_BOOST in football_api.py), against
every currently-finished World Cup match. Uses your existing cached data —
get_fixtures() and get_team_stats() are both already TTL-cached, so this
adds effectively zero extra load on your rate limit if you've loaded the
app recently.

IMPORTANT CAVEAT — read this before trusting the numbers:
This is a rough sanity check, not a rigorous backtest. get_team_stats()
returns each team's last 20 FINISHED matches as of RIGHT NOW — which for
an early group-stage match includes results that happened AFTER that
match. A true backtest would need each team's rolling stats as they stood
BEFORE each match being tested (point-in-time snapshots), which this app
doesn't currently store. So treat this as directional evidence ("does the
boost move accuracy in the right direction on the matches we can check"),
not proof of a specific accuracy number. Given tonight's time constraints,
this is the most useful check available without building a full
point-in-time data pipeline.

API USAGE: this script's own data (fixtures + team stats) is cached to a
local file (backtest_cache.json) the first time it runs. Every re-run
after that reads from disk instead of calling football-data.org again —
so you can re-run this as many times as you want while iterating without
touching your rate limit further. Delete backtest_cache.json if you
genuinely want a fresh pull (e.g. new matches have finished since).

Scoped to KNOCKOUT matches only (Round of 32 onward) — this is what the
defense-boost feature actually targets, and it cuts the number of unique
teams (and therefore API calls) roughly in half compared to testing every
group-stage match too.

Paced at one call every 7 seconds to stay safely under football-data.org's
free-tier per-minute limit. This means the FIRST run (before the cache
exists) will take a few minutes — that's expected and intentional, it's
the tradeoff for not hitting 429s again.
"""
import sys
import os
import json
import time
sys.path.insert(0, os.path.dirname(__file__))

from football_api import get_fixtures, get_team_stats, parse_team_form
from monte_carlo import run_simulation

REQUEST_DELAY_SECONDS = 7  # paced to stay under free-tier rate limits

BACKTEST_CACHE_FILE = os.path.join(os.path.dirname(__file__), 'backtest_cache.json')

def _load_backtest_cache():
    try:
        with open(BACKTEST_CACHE_FILE, 'r') as f:
            data = json.load(f)
            # Reject caches from the old, broken (rate-limited/partial) run —
            # those don't have this marker.
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
    print(f"Using local cache ({BACKTEST_CACHE_FILE}) — zero new API calls this run.")
    print("(Delete this file if you want to pull fresh data from football-data.org.)\n")
    all_matches = _cache['fixtures']
    stats_cache = _cache['team_stats']
else:
    print("No valid local cache found — this run WILL call football-data.org.")
    print(f"Paced at 1 call every {REQUEST_DELAY_SECONDS}s to respect the rate limit —")
    print("this will take a few minutes. That's expected.\n")
    print("Fetching fixtures...")
    all_matches = get_fixtures()
    stats_cache = {}

finished = [m for m in all_matches if m['status'] == 'FINISHED']
knockout_finished = [m for m in finished if m['stage'] != 'GROUP_STAGE']
print(f"Found {len(finished)} finished matches total, {len(knockout_finished)} of them knockout-stage.")
print(f"Testing against knockout matches only.\n")
finished = knockout_finished

results_old = {'correct': 0, 'total': 0}
results_new = {'correct': 0, 'total': 0}
disagreements = []
diagnostics = []

def get_cached_team_data(team_id):
    key = str(team_id)  # string key so this matches JSON round-tripping from disk
    if key in stats_cache:
        return stats_cache[key]

    # Only paces/retries on an ACTUAL network call — never delays a cache hit.
    time.sleep(REQUEST_DELAY_SECONDS)
    try:
        stats_cache[key] = get_team_stats(team_id)
    except Exception as e:
        if '429' in str(e):
            print(f"    Rate limited on team {team_id} — waiting 65s and retrying once...")
            time.sleep(65)
            stats_cache[key] = get_team_stats(team_id)  # let this raise if it fails again
        else:
            raise
    return stats_cache[key]

for m in finished:
    home_id = m['homeTeam']['id']
    away_id = m['awayTeam']['id']
    home_name = m['homeTeam']['name']
    away_name = m['awayTeam']['name']

    score = m['score']['fullTime']
    if score['home'] is None or score['away'] is None:
        continue
    actual_winner = home_name if score['home'] > score['away'] else (
        away_name if score['away'] > score['home'] else 'Draw'
    )
    is_knockout = m['stage'] != 'GROUP_STAGE'

    try:
        home_data = get_cached_team_data(home_id)
        away_data = get_cached_team_data(away_id)
    except Exception as e:
        print(f"  Skipping {home_name} vs {away_name} — data fetch failed: {e}")
        continue

    # OLD behavior — boost disabled
    home_stats_old = parse_team_form(home_data, home_id, apply_recent_defense_boost=False)
    away_stats_old = parse_team_form(away_data, away_id, apply_recent_defense_boost=False)
    sim_old = run_simulation(home_name, away_name, home_stats_old, away_stats_old, is_knockout=is_knockout)

    # NEW behavior — boost enabled (the default)
    home_stats_new = parse_team_form(home_data, home_id, apply_recent_defense_boost=True)
    away_stats_new = parse_team_form(away_data, away_id, apply_recent_defense_boost=True)
    sim_new = run_simulation(home_name, away_name, home_stats_new, away_stats_new, is_knockout=is_knockout)

    def predicted_winner(sim):
        p1, pd_, p2 = sim['team1_win_pct'], sim['draw_pct'], sim['team2_win_pct']
        if is_knockout:
            return home_name if p1 > p2 else away_name
        if p1 > p2 and p1 > pd_: return home_name
        if p2 > p1 and p2 > pd_: return away_name
        return 'Draw'

    pred_old = predicted_winner(sim_old)
    pred_new = predicted_winner(sim_new)

    # ── Deep diagnostics ─────────────────────────────────────────────────
    # Track this even when the winner didn't flip — the question isn't
    # just "did the pick change" but "did anything move at all, and by
    # how much." A boost that never flips a winner could mean either (a)
    # it's genuinely too weak to matter, or (b) it's a no-op that never
    # changes anything, or (c) most teams' recent form window already
    # covers almost their whole sample (small international schedules),
    # diluting the boost's relative effect. This tells us which.
    win_pct_delta = sim_new['team1_win_pct'] - sim_old['team1_win_pct']
    cpg_delta_home = home_stats_new['conceded_per_game'] - home_stats_old['conceded_per_game']
    cpg_delta_away = away_stats_new['conceded_per_game'] - away_stats_old['conceded_per_game']
    cs_delta_home = home_stats_new['clean_sheet_rate'] - home_stats_old['clean_sheet_rate']
    cs_delta_away = away_stats_new['clean_sheet_rate'] - away_stats_old['clean_sheet_rate']

    diagnostics.append({
        'match':          f"{home_name} vs {away_name}",
        'actual':         actual_winner,
        'pred_old':       pred_old,
        'pred_new':       pred_new,
        'flipped':        pred_old != pred_new,
        'win_pct_old':    sim_old['team1_win_pct'],
        'win_pct_new':    sim_new['team1_win_pct'],
        'win_pct_delta':  round(win_pct_delta, 3),
        'cpg_delta_home': round(cpg_delta_home, 4),
        'cpg_delta_away': round(cpg_delta_away, 4),
        'cs_delta_home':  round(cs_delta_home, 4),
        'cs_delta_away':  round(cs_delta_away, 4),
        'home_sample':    home_stats_new['sample_size'],
        'away_sample':    away_stats_new['sample_size'],
    })

    results_old['total'] += 1
    results_new['total'] += 1
    if pred_old == actual_winner:
        results_old['correct'] += 1
    if pred_new == actual_winner:
        results_new['correct'] += 1

    if pred_old != pred_new:
        disagreements.append({
            'match': f"{home_name} vs {away_name}",
            'actual': actual_winner,
            'old_predicted': pred_old,
            'new_predicted': pred_new,
        })

# Save whatever we fetched this run so every future run reads from disk
# instead of calling football-data.org again.
if _cache is None:
    _save_backtest_cache({'fixtures': all_matches, 'team_stats': stats_cache})
    print(f"Saved results to {BACKTEST_CACHE_FILE} — future runs will be free.\n")

print("=" * 60)
print("RESULTS")
print("=" * 60)
old_acc = results_old['correct'] / results_old['total'] * 100 if results_old['total'] else 0
new_acc = results_new['correct'] / results_new['total'] * 100 if results_new['total'] else 0
print(f"OLD (no defense boost): {results_old['correct']}/{results_old['total']} correct ({old_acc:.1f}%)")
print(f"NEW (with defense boost): {results_new['correct']}/{results_new['total']} correct ({new_acc:.1f}%)")
print(f"Difference: {new_acc - old_acc:+.1f} percentage points")

print(f"\nMatches where the boost changed the predicted winner ({len(disagreements)}):")
for d in disagreements:
    marker_old = "✓" if d['old_predicted'] == d['actual'] else "✗"
    marker_new = "✓" if d['new_predicted'] == d['actual'] else "✗"
    print(f"  {d['match']}: actual={d['actual']} | old={d['old_predicted']}{marker_old} -> new={d['new_predicted']}{marker_new}")

print("\n" + "=" * 60)
print("DEEP DIAGNOSTICS — is the boost doing ANYTHING, even if it never flips a winner?")
print("=" * 60)

print(f"\nPer-match breakdown (win% = home team's win probability, old vs new):")
print(f"{'Match':<38} {'Old%':>7} {'New%':>7} {'Δwin%':>8} {'ΔCPG(h)':>9} {'ΔCPG(a)':>9}")
for d in diagnostics:
    print(f"{d['match']:<38} {d['win_pct_old']:>7.1f} {d['win_pct_new']:>7.1f} "
          f"{d['win_pct_delta']:>+8.3f} {d['cpg_delta_home']:>+9.4f} {d['cpg_delta_away']:>+9.4f}")

zero_delta_count = sum(1 for d in diagnostics if abs(d['win_pct_delta']) < 0.001)
nonzero_deltas = [abs(d['win_pct_delta']) for d in diagnostics if abs(d['win_pct_delta']) >= 0.001]

print(f"\nMatches with LITERALLY ZERO win% change: {zero_delta_count} / {len(diagnostics)}")
if nonzero_deltas:
    print(f"Among matches that DID move at all ({len(nonzero_deltas)}):")
    print(f"  smallest move: {min(nonzero_deltas):.4f} percentage points")
    print(f"  largest move:  {max(nonzero_deltas):.4f} percentage points")
    print(f"  average move:  {sum(nonzero_deltas)/len(nonzero_deltas):.4f} percentage points")
else:
    print("NONE of the matches moved at all, even fractionally. This points to a real")
    print("no-op, not just 'too weak to flip a winner' — worth checking the boost is")
    print("actually wired into the calculation (see conceded_per_game deltas above —")
    print("if THOSE are also all zero, the boost isn't reaching parse_team_form at all).")

# Sample-size / window-coverage check — are teams' histories short enough that
# the boost window (RECENT_DEFENSE_WINDOW games) covers most/all of their data,
# diluting any differential effect between "recent" and "rest of history"?
print(f"\nSample size check (is the recent-form window swallowing most of each team's history?):")
sample_sizes = sorted(set([d['home_sample'] for d in diagnostics] + [d['away_sample'] for d in diagnostics]))
print(f"  Sample sizes seen across all teams: {sample_sizes}")
print(f"  (RECENT_DEFENSE_WINDOW is currently 5 — if most teams have sample_size <= 8-10,")
print(f"   the 'recent window' covers most/all of their history, which would make the")
print(f"   boost apply almost uniformly across the whole dataset instead of creating a")
print(f"   meaningful recent-vs-older contrast.)")

print("\nReminder: this is a directional sanity check, not a rigorous point-in-time")
print("backtest — see the caveat in this script's header comment.")
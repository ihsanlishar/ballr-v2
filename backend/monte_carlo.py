import numpy as np
from scipy.stats import poisson
from elo import get_elo, elo_strength_ratio, elo_win_probability

def form_momentum(stats):
    """
    Derive a sentiment-style score directly from recent form.
    Replaces Watson NLU — no API needed, never fails.
    Range: roughly -0.6 to +0.8
    """
    form = stats.get('wc_form') or stats.get('form_string', '')
    if not form:
        return 0.0

    wins   = form.count('W')
    draws  = form.count('D')
    losses = form.count('L')
    n      = len(form)

    # Weighted points (recency matters — first char is most recent)
    score = 0.0
    for i, r in enumerate(form):
        recency = 0.85 ** i
        if r == 'W':   score += 1.0  * recency
        elif r == 'D': score += 0.2  * recency
        else:          score -= 0.6  * recency

    # Normalise to roughly -1 to +1
    max_possible = sum(0.85 ** i for i in range(n))
    score = score / max_possible if max_possible > 0 else 0.0

    # Blend with win rate for stability
    wr_bonus = (stats.get('win_rate', 0.33) - 0.33) * 0.5
    score = score + wr_bonus

    return round(max(-1.0, min(score, 1.0)), 3)

def dixon_coles_correction(home_goals, away_goals, lam1, lam2, rho=-0.13):
    """
    Dixon-Coles correction for low-scoring games.
    Adjusts probability of 0-0, 1-0, 0-1, 1-1 which Poisson over/under-predicts.
    rho = -0.13 is the standard fitted value from football literature.
    """
    if home_goals > 1 or away_goals > 1:
        return 1.0

    if home_goals == 0 and away_goals == 0:
        return 1 - lam1 * lam2 * rho
    elif home_goals == 1 and away_goals == 0:
        return 1 + lam2 * rho
    elif home_goals == 0 and away_goals == 1:
        return 1 + lam1 * rho
    elif home_goals == 1 and away_goals == 1:
        return 1 - rho
    return 1.0

def run_simulation(home_team, away_team, home_stats, away_stats, n=50000, is_knockout=False):
    """
    Full prediction model:
    1. Base attack rate from weighted goals per game
    2. Elo anchoring — adjusts for team quality difference
    3. Defensive pressure — clean sheet rate suppresses opponent
    4. Win rate factor — consistent winners convert better
    5. GD anchor — sustained dominance gets small boost
    6. Form momentum — recent run of results (replaces NLU)
    7. Dixon-Coles correction — fixes 1-1 over-prediction

    is_knockout: when True, a drawn-after-90 result isn't a valid final
    outcome (extra time / penalties resolve it), so the draw probability
    mass is redistributed proportionally into each team's win% rather than
    displayed as a standalone outcome. E.g. raw 40% / 20% draw / 40% becomes
    a clean 50% / 50%. This does not model penalty-shootout skill — it's a
    proportional split, chosen deliberately for simplicity over a shootout
    model with more moving parts and negligible practical difference.
    """

    # ── 1. Base rates ──────────────────────────────────────────────────────
    lam1 = home_stats['goals_per_game']
    lam2 = away_stats['goals_per_game']

    # ── 2. Elo anchoring ───────────────────────────────────────────────────
    elo_ratio_h = elo_strength_ratio(home_team, away_team)
    elo_ratio_a = elo_strength_ratio(away_team, home_team)
    lam1 *= elo_ratio_h
    lam2 *= elo_ratio_a

    # ── 3. Defensive pressure ──────────────────────────────────────────────
    def defensive_factor(cs_rate):
        # cs_rate 0.0 → 1.10 (bad defense), 0.5 → 0.85 (solid)
        return 1.10 - (cs_rate * 0.5)

    lam1 *= defensive_factor(away_stats['clean_sheet_rate'])
    lam2 *= defensive_factor(home_stats['clean_sheet_rate'])

    # ── 4. Win rate factor ─────────────────────────────────────────────────
    def win_rate_factor(wr):
        # wr 0.2 → 0.93, wr 0.5 → 1.0, wr 0.8 → 1.07
        return 0.93 + (wr * 0.14)

    lam1 *= win_rate_factor(home_stats['win_rate'])
    lam2 *= win_rate_factor(away_stats['win_rate'])

    # ── 5. Goal difference anchor ──────────────────────────────────────────
    lam1 *= (1 + np.clip(home_stats['gd_per_game'] * 0.03, -0.09, 0.09))
    lam2 *= (1 + np.clip(away_stats['gd_per_game'] * 0.03, -0.09, 0.09))

    # ── 6. Form momentum ───────────────────────────────────────────────────
    mom1 = form_momentum(home_stats)
    mom2 = form_momentum(away_stats)
    lam1 *= (1 + mom1 * 0.06)
    lam2 *= (1 + mom2 * 0.06)

    # ── Clamp to realistic range ───────────────────────────────────────────
    lam1 = float(np.clip(lam1, 0.3, 4.0))
    lam2 = float(np.clip(lam2, 0.3, 4.0))

    # ── 7. Dixon-Coles corrected simulation ───────────────────────────────
    max_goals = 8
    home_wins = draws = away_wins = 0
    score_dist = {}

    # Pre-compute Poisson probabilities
    p1 = [poisson.pmf(g, lam1) for g in range(max_goals + 1)]
    p2 = [poisson.pmf(g, lam2) for g in range(max_goals + 1)]

    total_prob = 0.0
    raw_probs  = {}

    for g1 in range(max_goals + 1):
        for g2 in range(max_goals + 1):
            prob = p1[g1] * p2[g2] * dixon_coles_correction(g1, g2, lam1, lam2)
            raw_probs[(g1, g2)] = prob
            total_prob += prob

    # Normalise and run
    for (g1, g2), prob in raw_probs.items():
        prob_norm = prob / total_prob
        expected  = prob_norm * n

        if g1 > g2:   home_wins += expected
        elif g1 == g2: draws    += expected
        else:          away_wins += expected

        if g1 <= 5 and g2 <= 5:
            key = f'{g1}-{g2}'
            score_dist[key] = round(prob_norm * 100, 2)

    total = home_wins + draws + away_wins

    team1_win_pct = home_wins / total * 100
    draw_pct      = draws     / total * 100
    team2_win_pct = away_wins / total * 100

    if is_knockout:
        # A draw isn't a valid final outcome in a knockout match — split the
        # draw probability mass proportionally into each team's existing
        # win/loss ratio rather than showing a standalone draw percentage.
        decisive_total = home_wins + away_wins
        if decisive_total > 0:
            team1_win_pct = home_wins / decisive_total * 100
            team2_win_pct = away_wins / decisive_total * 100
        else:
            # Degenerate edge case (near-impossible in practice): no
            # decisive outcome at all in the raw simulation. Fall back to
            # an even split rather than dividing by zero.
            team1_win_pct = team2_win_pct = 50.0
        draw_pct = 0.0

    # Top 5 most likely scores
    top_scores = sorted(score_dist.items(), key=lambda x: x[1], reverse=True)[:5]

    # Elo-based win probability for reference
    elo_h  = get_elo(home_team)
    elo_a  = get_elo(away_team)
    elo_wp = elo_win_probability(elo_h, elo_a)

    return {
        'team1_win_pct': round(team1_win_pct, 1),
        'draw_pct':      round(draw_pct, 1),
        'team2_win_pct': round(team2_win_pct, 1),
        'team1_xg':      round(lam1, 2),
        'team2_xg':      round(lam2, 2),
        'team1_lambda':  round(lam1, 3),
        'team2_lambda':  round(lam2, 3),
        'top_scores':    top_scores,
        'score_dist':    score_dist,
        'elo_home':      elo_h,
        'elo_away':      elo_a,
        'elo_win_prob':  round(elo_wp * 100, 1),
        'home_momentum': mom1,
        'away_momentum': mom2,
        'is_knockout':   is_knockout,
    }
# Current World Cup 2026 Elo ratings (eloratings.net, June 2026)
# Higher = stronger. Average international team ~1500.

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

def get_elo(team_name):
    """Get Elo rating for a team, fallback to average if not found."""
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
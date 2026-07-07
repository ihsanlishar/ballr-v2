"""
Run this locally: python3 check_api_tier.py

Checks what your football-data.org plan actually returns for a finished
match — specifically whether shots, xG, possession, or other advanced
stats are included. No guessing: if a field isn't in this printout, your
plan doesn't have it, regardless of what their marketing page says.

Uses your existing FOOTBALL_DATA_API_KEY from .env — no new API calls
beyond what this script itself makes (2 calls total: one to find a
finished match, one to inspect it).
"""
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv('FOOTBALL_DATA_API_KEY')
BASE_URL = 'https://api.football-data.org/v4'
HEADERS = {'X-Auth-Token': API_KEY}

print("Step 1: Finding a finished World Cup match to inspect...")
r = requests.get(f'{BASE_URL}/competitions/WC/matches', headers=HEADERS, timeout=15)
r.raise_for_status()
matches = r.json().get('matches', [])
finished = [m for m in matches if m['status'] == 'FINISHED']

if not finished:
    print("No finished matches found — can't inspect further. Try again once at least one match has finished.")
else:
    sample = finished[-1]  # most recent finished match
    match_id = sample['id']
    print(f"Using match: {sample['homeTeam']['name']} vs {sample['awayTeam']['name']} (id={match_id})")

    print(f"\nStep 2: Fetching full match detail from /v4/matches/{match_id} ...")
    r2 = requests.get(f'{BASE_URL}/matches/{match_id}', headers=HEADERS, timeout=15)
    r2.raise_for_status()
    detail = r2.json()

    print("\nTop-level fields returned:")
    for key in detail.keys():
        print(f"  - {key}")

    print("\nFull raw response (look for 'statistics', 'shots', 'possession', 'xg', etc.):")
    print(json.dumps(detail, indent=2))

    advanced_keywords = ['shot', 'possession', 'xg', 'expected', 'statistic', 'pass', 'corner', 'foul']
    found_advanced = []
    full_text_lower = json.dumps(detail).lower()
    for kw in advanced_keywords:
        if kw in full_text_lower:
            found_advanced.append(kw)

    print("\n--- VERDICT ---")
    if found_advanced:
        print(f"Found possible advanced-stat keywords in the response: {found_advanced}")
        print("Look at the raw JSON above near these words to confirm what's actually populated (vs. just a key name with null/empty value).")
    else:
        print("No advanced stat fields (shots/xG/possession/etc.) found anywhere in the response.")
        print("Your current plan does not expose this data — options 3 and 4 aren't viable via this API tonight.")

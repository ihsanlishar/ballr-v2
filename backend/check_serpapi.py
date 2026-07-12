"""
Run this locally: python3 check_serpapi.py

Diagnoses why goal scorers/match events aren't showing up for ANY finished
match. Two very different possible causes, needing very different fixes:

1. AUTH/QUOTA ERROR — SerpAPI itself rejects the request (bad key, monthly
   search credits exhausted, etc). This shows up as an explicit "error"
   field in SerpAPI's JSON response. FIXABLE — top up credits or fix the
   key.

2. GOOGLE JUST DOESN'T SHOW THE SPORTS BOX ANYMORE — Google's live sports
   scorecard ("sports_results.game_spotlight") is designed to appear for
   LIVE or VERY recently finished games, and commonly disappears from
   search results once enough time has passed. If SerpAPI's response comes
   back completely successful but simply has no sports_results at all,
   that's this case — and it's NOT fixable by any code change, since the
   whole approach depends on Google still showing that widget days/weeks
   after a match ends.

This makes exactly ONE real SerpAPI call (your quota is precious — this
won't loop or retry), against a match that's already definitely finished,
and prints the full raw response so we can see which of the two is
actually happening instead of guessing.
"""
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

SERPAPI_KEY = os.getenv('SERPAPI_KEY')

if not SERPAPI_KEY:
    print("SERPAPI_KEY not found in your LOCAL .env file.")
    print("(This only checks your local environment — you confirmed Railway has it")
    print(" set separately, so this local check is just to let this script run at all.)")
    exit(1)

# A real match from your tournament that's definitely finished and should
# have plenty of Google coverage.
HOME_TEAM = "Switzerland"
AWAY_TEAM = "Colombia"
QUERY = f"{HOME_TEAM} vs {AWAY_TEAM} 2026 World Cup"

print(f"Querying SerpAPI for: \"{QUERY}\"")
print(f"Using key ending in: ...{SERPAPI_KEY[-6:]}\n")

r = requests.get(
    'https://serpapi.com/search.json',
    params={
        'q': QUERY,
        'api_key': SERPAPI_KEY,
        'engine': 'google',
        'device': 'desktop'
    },
    timeout=15
)

print(f"HTTP status: {r.status_code}\n")

try:
    data = r.json()
except Exception as e:
    print(f"Response wasn't valid JSON at all: {e}")
    print("Raw text:", r.text[:500])
    exit(1)

# Check for an explicit SerpAPI error first — this is the auth/quota case.
if 'error' in data:
    print("=" * 60)
    print("VERDICT: SerpAPI returned an explicit ERROR.")
    print("=" * 60)
    print(f"Error message: {data['error']}")
    print("\nThis is case #1 — auth or quota issue. Check your SerpAPI dashboard")
    print("for remaining search credits, and confirm the key on Railway matches")
    print("your actual account key exactly (no extra spaces/truncation).")
    exit(0)

# No explicit error — check whether the sports box is actually there.
spotlight = data.get('sports_results', {}).get('game_spotlight', {})
search_metadata = data.get('search_metadata', {})
print(f"Search metadata status: {search_metadata.get('status', 'unknown')}")
print(f"Top-level keys in response: {list(data.keys())}")
print(f"'sports_results' present: {'sports_results' in data}")
print(f"'game_spotlight' populated: {bool(spotlight)}")

if spotlight:
    print("\n" + "=" * 60)
    print("VERDICT: Sports box WAS found — events pipeline should work.")
    print("=" * 60)
    print("If real matches are still showing no events despite this, the bug")
    print("is likely in caching (a None got frozen in before this point) rather")
    print("than in the SerpAPI call itself.")
    print("\nSample of what was found:")
    print(json.dumps(spotlight, indent=2)[:800])
else:
    print("\n" + "=" * 60)
    print("VERDICT: Request succeeded, but NO sports box in the response.")
    print("=" * 60)
    print("This is case #2 — Google is not showing a live sports scorecard for")
    print("this query right now. This is a known Google behavior: the sports")
    print("box is tied to live/very-recent games and commonly stops appearing")
    print("once enough time has passed after the match. If this is happening")
    print("for every match you check, goal-scorer data via this method may only")
    print("ever work in a narrow window right after a match ends — not for")
    print("browsing older results later. This is not fixable by changing the")
    print("code; it would need a different data source entirely.")
    print("\nFull response keys for reference:", list(data.keys()))

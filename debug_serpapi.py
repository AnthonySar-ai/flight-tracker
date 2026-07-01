import json
import os
import requests

SERPAPI_KEY = os.environ["SERPAPI_KEY"]

params = {
    "engine":        "google_flights",
    "departure_id":  "NCE",
    "arrival_id":    "BEY",
    "outbound_date": "2026-08-01",
    "return_date":   "2026-08-15",
    "currency":      "EUR",
    "hl":            "en",
    "type":          "1",
    "api_key":       SERPAPI_KEY,
}

data = requests.get("https://serpapi.com/search", params=params, timeout=30).json()

print("=== TOP-LEVEL KEYS ===")
print(list(data.keys()))

all_flights = data.get("best_flights", []) + data.get("other_flights", [])
print(f"\n=== TOTAL FLIGHT RESULTS: {len(all_flights)} ===")

if all_flights:
    print("\n=== FIRST FLIGHT OBJECT (full) ===")
    print(json.dumps(all_flights[0], indent=2))

"""
Flight Price Tracker
Route:   Nice (NCE) → Beirut (BEY), roundtrip
Stay:    14 nights

Tracks two seasonal windows every year:
  AUGUST      — departs Aug 1, 7, 14, 21  (returns 14 days later)
  DEC/JAN     — departs Dec 13, 18, 20, 23 (returns 14 days later, early Jan)

Runs every Monday via GitHub Actions.
Uses ~32 SerpAPI calls/month — well within the 250/month free tier.
Data accumulates forever in data/flights.csv and data/flights.db
"""

import os
import requests
from datetime import date, timedelta
from store_data import save_flights

SERPAPI_KEY = os.environ["SERPAPI_KEY"]
SERPAPI_URL = "https://serpapi.com/search"

ORIGIN      = "NCE"
DESTINATION = "BEY"
STAY_DAYS   = 14  # 2-week trip


def target_departures_for_year(year):
    """
    Returns the specific departure dates we care about for a given year.
    August: 1st, 7th, 14th, 21st
    December (→ early Jan return): 13th, 18th, 20th, 23rd
    """
    august_days   = [1, 7, 14, 21]
    december_days = [13, 18, 20, 23]

    departures = []
    for d in august_days:
        departures.append(date(year, 8, d))
    for d in december_days:
        departures.append(date(year, 12, d))
    return departures


def get_dates_to_track():
    """
    Build the full list of (depart, return) pairs to query this week.
    Always tracks the current year AND next year so we capture prices
    as far ahead as possible from day one.
    """
    today = date.today()
    pairs = []

    for year in [today.year, today.year + 1]:
        for depart in target_departures_for_year(year):
            # Only track dates that are still in the future
            if depart > today:
                ret = depart + timedelta(days=STAY_DAYS)
                pairs.append((depart, ret))

    return pairs


def search_flights(depart_date, return_date):
    """Query SerpAPI Google Flights for one roundtrip."""
    params = {
        "engine":           "google_flights",
        "departure_id":     ORIGIN,
        "arrival_id":       DESTINATION,
        "outbound_date":    depart_date.strftime("%Y-%m-%d"),
        "return_date":      return_date.strftime("%Y-%m-%d"),
        "currency":         "EUR",
        "hl":               "en",
        "type":             "1",           # 1 = roundtrip
        "api_key":          SERPAPI_KEY,
    }
    resp = requests.get(SERPAPI_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_results(data, depart_date, return_date, checked_at):
    """Flatten SerpAPI response into a list of clean record dicts."""
    records = []
    all_flights = data.get("best_flights", []) + data.get("other_flights", [])

    for flight in all_flights:
        price = flight.get("price")
        if price is None:
            continue

        legs = flight.get("flights", [])
        if not legs:
            continue

        airlines  = sorted({leg.get("airline", "") for leg in legs if leg.get("airline")})
        out_dep   = legs[0].get("departure_airport", {}).get("time", "")
        out_arr   = legs[-1].get("arrival_airport", {}).get("time", "")
        out_dur   = flight.get("total_duration", "")
        out_stops = len(legs) - 1

        ret_info  = flight.get("return_flights", {}) or {}
        ret_legs  = ret_info.get("flights", [])
        ret_dep   = ret_legs[0].get("departure_airport", {}).get("time", "") if ret_legs else ""
        ret_arr   = ret_legs[-1].get("arrival_airport", {}).get("time", "") if ret_legs else ""
        ret_dur   = ret_info.get("total_duration", "")
        ret_stops = len(ret_legs) - 1 if ret_legs else ""

        season = "August" if depart_date.month == 8 else "DecJan"

        records.append({
            "checked_at":    checked_at,
            "season":        season,
            "depart_date":   depart_date.strftime("%Y-%m-%d"),
            "return_date":   return_date.strftime("%Y-%m-%d"),
            "price_eur":     float(price),
            "airlines":      ", ".join(airlines),
            "out_stops":     out_stops,
            "out_dep_time":  out_dep,
            "out_arr_time":  out_arr,
            "out_duration":  str(out_dur),
            "ret_stops":     ret_stops,
            "ret_dep_time":  ret_dep,
            "ret_arr_time":  ret_arr,
            "ret_duration":  str(ret_dur),
        })

    return records


def main():
    from datetime import datetime
    checked_at = date.today().strftime("%Y-%m-%d")
    print(f"[{datetime.utcnow().isoformat()}] Flight tracker starting...")

    date_pairs  = get_dates_to_track()
    all_records = []

    print(f"  Tracking {len(date_pairs)} departure dates this run:")
    for depart, ret in date_pairs:
        print(f"  NCE→BEY  depart {depart}  return {ret} ...")
        try:
            data    = search_flights(depart, ret)
            records = parse_results(data, depart, ret, checked_at)
            all_records.extend(records)
            print(f"    → {len(records)} offers found")
        except requests.HTTPError as e:
            print(f"    ⚠ HTTP {e.response.status_code}: {e.response.text[:200]}")
        except Exception as e:
            print(f"    ⚠ Error: {e}")

    save_flights(all_records)
    print(f"Done. {len(all_records)} total records saved.")


if __name__ == "__main__":
    main()

"""
Flight Price Tracker — NCE → BEY roundtrip
Tracks:
  AUGUST   — first 4 Saturdays, return 2 weeks later (Sat + Sun options)
  XMAS     — Saturday before Dec 24 (shifted back if Dec 23+), return Sat+Sun 2 weeks later
  Exception: 2028 Christmas → Dec 16 (Dec 24 is Sunday, would arrive Dec 23)

Captures: price, airlines, flight numbers, times, duration, layover, stops.
Disruption signals: airline_count, zero-result logging, price_change_pct.
Runs twice a week via GitHub Actions (Mon + Thu).

Return leg strategy (Option 3 — credit efficient):
  For each date pair, ONE extra API call is made using the departure_token
  of the cheapest outbound flight. The return leg data is applied to ALL
  outbound rows for that date pair.

  FIX: The second (return leg) call must NOT include type=1 or any date
  parameters — only engine, departure_token, currency, hl, and api_key.
  Passing type=1 alongside departure_token causes a 400 Bad Request.
"""

import os
import requests
from datetime import date, timedelta
from store_data import save_flights, log_no_results

SERPAPI_KEY = os.environ["SERPAPI_KEY"]
SERPAPI_URL = "https://serpapi.com/search"
ORIGIN      = "NCE"
DESTINATION = "BEY"


def get_august_departures(year):
    """First 4 Saturdays of August."""
    d = date(year, 8, 1)
    while d.weekday() != 5:
        d += timedelta(days=1)
    sats = []
    while d.month == 8 and len(sats) < 4:
        sats.append(d)
        d += timedelta(weeks=1)
    return sats


def get_christmas_departure(year):
    """
    Saturday before Dec 24.
    If that Saturday falls on Dec 23 or later, shift back one week.
    """
    dec24 = date(year, 12, 24)
    days_back = (dec24.weekday() + 2) % 7
    if days_back == 0:
        days_back = 7
    sat = dec24 - timedelta(days=days_back)
    if sat.day >= 23:
        sat -= timedelta(weeks=1)
    return sat


def get_dates_to_track():
    today = date.today()
    pairs = []

    for year in [today.year, today.year + 1]:
        for dep in get_august_departures(year):
            if dep <= today:
                continue
            ret_sat = dep + timedelta(weeks=2)
            ret_sun = ret_sat + timedelta(days=1)
            pairs.append((dep, ret_sat, "August"))
            pairs.append((dep, ret_sun, "August"))

        dep = get_christmas_departure(year)
        if dep > today:
            ret_sat = dep + timedelta(weeks=2)
            ret_sun = ret_sat + timedelta(days=1)
            pairs.append((dep, ret_sat, "DecJan"))
            pairs.append((dep, ret_sun, "DecJan"))

    return pairs


def search_outbound(depart_date, return_date):
    """First API call — fetches outbound flights for a date pair."""
    params = {
        "engine":        "google_flights",
        "departure_id":  ORIGIN,
        "arrival_id":    DESTINATION,
        "outbound_date": depart_date.strftime("%Y-%m-%d"),
        "return_date":   return_date.strftime("%Y-%m-%d"),
        "currency":      "EUR",
        "hl":            "en",
        "type":          "1",
        "api_key":       SERPAPI_KEY,
    }
    resp = requests.get(SERPAPI_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def search_return_leg(departure_token, depart_date, return_date):
    """
    Second API call — uses departure_token to fetch return flights.

    Must include the same departure_id, arrival_id, outbound_date and
    return_date from the first call alongside the departure_token.
    Confirmed by SerpAPI support — omitting these causes a 400 error.
    Do NOT include type here.
    """
    params = {
        "engine":          "google_flights",
        "departure_id":    ORIGIN,
        "arrival_id":      DESTINATION,
        "outbound_date":   depart_date.strftime("%Y-%m-%d"),
        "return_date":     return_date.strftime("%Y-%m-%d"),
        "departure_token": departure_token,
        "currency":        "EUR",
        "hl":              "en",
        "api_key":         SERPAPI_KEY,
    }
    resp = requests.get(SERPAPI_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def format_duration(minutes):
    if not minutes:
        return ""
    try:
        m = int(minutes)
        return f"{m // 60}h{m % 60:02d}"
    except Exception:
        return str(minutes)


def clean_airline_name(name):
    return str(name).strip().strip('"').strip("'").strip()


def extract_return_info(departure_token, depart_date, return_date):
    """
    Fetches return flights using departure_token and returns a dict with
    the cheapest return leg's details. Returns an empty dict on failure.
    Called ONCE per date pair, not once per outbound result.
    """
    try:
        data = search_return_leg(departure_token, depart_date, return_date)
    except Exception as e:
        print(f"      ⚠ Return leg API call failed: {e}")
        return {}

    ret_flights = data.get("best_flights", []) + data.get("other_flights", [])
    if not ret_flights:
        print(f"      ⚠ Return leg call returned zero results")
        return {}

    # Pick the cheapest return option
    ret_flights.sort(key=lambda f: f.get("price") or 999999)
    best = ret_flights[0]
    legs = best.get("flights", [])

    ret_airlines    = []
    ret_flight_nums = []
    for leg in legs:
        a  = clean_airline_name(leg.get("airline", ""))
        fn = leg.get("flight_number", "")
        if a:
            ret_airlines.append(a)
        if fn:
            ret_flight_nums.append(fn)

    ret_stops       = len(legs) - 1 if legs else 0
    ret_dep_time    = legs[0].get("departure_airport", {}).get("time", "") if legs else ""
    ret_arr_time    = legs[-1].get("arrival_airport", {}).get("time", "") if legs else ""
    ret_dur_min     = best.get("total_duration", "")
    ret_layover_min = sum(lay.get("duration", 0) for lay in best.get("layovers", []))

    return {
        "ret_airlines":     ", ".join(dict.fromkeys(ret_airlines)),
        "ret_flight_nums":  ", ".join(ret_flight_nums),
        "ret_stops":        ret_stops,
        "ret_dep_time":     ret_dep_time,
        "ret_arr_time":     ret_arr_time,
        "ret_duration":     str(ret_dur_min),
        "ret_duration_fmt": format_duration(ret_dur_min),
        "ret_layover_min":  ret_layover_min if ret_stops > 0 else "",
        "ret_layover_fmt":  format_duration(ret_layover_min) if ret_stops > 0 else "",
    }


def parse_results(data, depart_date, return_date, season, checked_at):
    records = []
    all_flights = data.get("best_flights", []) + data.get("other_flights", [])
    all_airlines_this_date = set()

    if not all_flights:
        return records, all_airlines_this_date

    valid_flights = [f for f in all_flights if f.get("price") is not None and f.get("flights")]
    if not valid_flights:
        return records, all_airlines_this_date

    # ONE extra API call for the return leg using cheapest outbound token
    cheapest_outbound = min(valid_flights, key=lambda f: f.get("price", 999999))
    cheapest_token    = cheapest_outbound.get("departure_token", "")

    ret_info = {}
    if cheapest_token:
        print(f"      → Fetching return leg via departure_token (1 extra call)...")
        ret_info = extract_return_info(cheapest_token, depart_date, return_date)
        if ret_info:
            print(f"      ✓ Return leg captured: {ret_info.get('ret_airlines','')} {ret_info.get('ret_dep_time','')}")
        else:
            print(f"      ⚠ Return leg empty — will store blank fields")

    for flight in valid_flights:
        legs = flight.get("flights", [])

        out_airlines    = []
        out_flight_nums = []
        out_dep_time    = legs[0].get("departure_airport", {}).get("time", "")
        out_arr_time    = legs[-1].get("arrival_airport", {}).get("time", "")
        out_dur_min     = flight.get("total_duration", "")
        out_stops       = len(legs) - 1
        out_layover_min = sum(lay.get("duration", 0) for lay in flight.get("layovers", []))

        for leg in legs:
            a  = clean_airline_name(leg.get("airline", ""))
            fn = leg.get("flight_number", "")
            if a:
                out_airlines.append(a)
                all_airlines_this_date.add(a)
            if fn:
                out_flight_nums.append(fn)

        seen = set()
        out_airlines_dedup = []
        for a in out_airlines:
            if a not in seen:
                seen.add(a)
                out_airlines_dedup.append(a)

        records.append({
            "checked_at":       checked_at,
            "season":           season,
            "depart_date":      depart_date.strftime("%Y-%m-%d"),
            "return_date":      return_date.strftime("%Y-%m-%d"),
            "price_eur":        float(flight.get("price")),
            "airlines":         ", ".join(out_airlines_dedup),
            "out_flight_nums":  ", ".join(out_flight_nums),
            "out_stops":        out_stops,
            "out_dep_time":     out_dep_time,
            "out_arr_time":     out_arr_time,
            "out_duration":     str(out_dur_min),
            "out_duration_fmt": format_duration(out_dur_min),
            "out_layover_min":  out_layover_min if out_stops > 0 else "",
            "out_layover_fmt":  format_duration(out_layover_min) if out_stops > 0 else "",
            "ret_airlines":     ret_info.get("ret_airlines", ""),
            "ret_flight_nums":  ret_info.get("ret_flight_nums", ""),
            "ret_stops":        ret_info.get("ret_stops", ""),
            "ret_dep_time":     ret_info.get("ret_dep_time", ""),
            "ret_arr_time":     ret_info.get("ret_arr_time", ""),
            "ret_duration":     ret_info.get("ret_duration", ""),
            "ret_duration_fmt": ret_info.get("ret_duration_fmt", ""),
            "ret_layover_min":  ret_info.get("ret_layover_min", ""),
            "ret_layover_fmt":  ret_info.get("ret_layover_fmt", ""),
            "airline_count":    len(all_airlines_this_date),
            "price_change_pct": "",
        })

    return records, all_airlines_this_date


def main():
    from datetime import datetime
    checked_at  = date.today().strftime("%Y-%m-%d")
    print(f"[{datetime.utcnow().isoformat()}] Flight tracker starting...")

    pairs       = get_dates_to_track()
    all_records = []

    print(f"  Tracking {len(pairs)} depart/return combinations:")
    for depart, ret, season in pairs:
        depart_str = depart.strftime("%Y-%m-%d")
        ret_str    = ret.strftime("%Y-%m-%d")
        print(f"  [{season}] NCE→BEY  {depart_str} → {ret_str} ...")
        try:
            data = search_outbound(depart, ret)
            records, airlines_seen = parse_results(data, depart, ret, season, checked_at)
            if not records:
                print(f"    ⚠ ZERO results — logging disruption signal")
                log_no_results(checked_at, depart_str, ret_str)
            else:
                all_records.extend(records)
                print(f"    → {len(records)} offers | {len(airlines_seen)} airlines: {', '.join(sorted(airlines_seen))}")
        except requests.HTTPError as e:
            print(f"    ⚠ HTTP {e.response.status_code}: {e.response.text[:200]}")
        except Exception as e:
            print(f"    ⚠ Error: {e}")

    save_flights(all_records)
    print(f"Done. {len(all_records)} total records saved.")


if __name__ == "__main__":
    main()
    
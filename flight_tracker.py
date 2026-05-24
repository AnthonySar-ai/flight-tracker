"""
Flight Price Tracker — NCE → BEY roundtrip
Tracks August and December/January windows, 14-night stay.
Captures: price, airlines, flight numbers, times, duration, layover, stops.
Disruption signals: airline_count, zero-result logging, price_change_pct.
"""

import os
import requests
from datetime import date, timedelta
from store_data import save_flights, log_no_results

SERPAPI_KEY = os.environ["SERPAPI_KEY"]
SERPAPI_URL = "https://serpapi.com/search"

ORIGIN      = "NCE"
DESTINATION = "BEY"
STAY_DAYS   = 14


def target_departures_for_year(year):
    august_days   = [1, 7, 14, 21]
    december_days = [13, 18, 20, 23]
    departures = []
    for d in august_days:
        departures.append(date(year, 8, d))
    for d in december_days:
        departures.append(date(year, 12, d))
    return departures


def get_dates_to_track():
    today = date.today()
    pairs = []
    for year in [today.year, today.year + 1]:
        for depart in target_departures_for_year(year):
            if depart > today:
                pairs.append((depart, depart + timedelta(days=STAY_DAYS)))
    return pairs


def search_flights(depart_date, return_date):
    params = {
        "engine":           "google_flights",
        "departure_id":     ORIGIN,
        "arrival_id":       DESTINATION,
        "outbound_date":    depart_date.strftime("%Y-%m-%d"),
        "return_date":      return_date.strftime("%Y-%m-%d"),
        "currency":         "EUR",
        "hl":               "en",
        "type":             "1",
        "api_key":          SERPAPI_KEY,
    }
    resp = requests.get(SERPAPI_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def format_duration(minutes):
    """Convert minutes to h:mm format."""
    if not minutes:
        return ""
    try:
        m = int(minutes)
        return f"{m // 60}h{m % 60:02d}"
    except:
        return str(minutes)


def parse_results(data, depart_date, return_date, checked_at):
    records = []
    all_flights = data.get("best_flights", []) + data.get("other_flights", [])
    all_airlines_this_date = set()

    for flight in all_flights:
        price = flight.get("price")
        if price is None:
            continue
        legs = flight.get("flights", [])
        if not legs:
            continue

        # ── Outbound leg ──────────────────────────────────────────────────
        out_airlines     = []
        out_flight_nums  = []
        out_dep_time     = legs[0].get("departure_airport", {}).get("time", "")
        out_arr_time     = legs[-1].get("arrival_airport", {}).get("time", "")
        out_dur_min      = flight.get("total_duration", "")
        out_stops        = len(legs) - 1
        out_layover_min  = sum(
            lay.get("duration", 0)
            for lay in flight.get("layovers", [])
        )

        for leg in legs:
            airline = leg.get("airline", "")
            fn      = leg.get("flight_number", "")
            if airline:
                out_airlines.append(airline)
                all_airlines_this_date.add(airline)
            if fn:
                out_flight_nums.append(fn)

        # ── Return leg ────────────────────────────────────────────────────
        ret_info        = flight.get("return_flights", {}) or {}
        ret_legs        = ret_info.get("flights", [])
        ret_airlines    = []
        ret_flight_nums = []
        ret_dep_time    = ret_legs[0].get("departure_airport", {}).get("time", "") if ret_legs else ""
        ret_arr_time    = ret_legs[-1].get("arrival_airport", {}).get("time", "") if ret_legs else ""
        ret_dur_min     = ret_info.get("total_duration", "")
        ret_stops       = len(ret_legs) - 1 if ret_legs else ""
        ret_layover_min = sum(
            lay.get("duration", 0)
            for lay in ret_info.get("layovers", [])
        )

        for leg in ret_legs:
            airline = leg.get("airline", "")
            fn      = leg.get("flight_number", "")
            if airline:
                ret_airlines.append(airline)
            if fn:
                ret_flight_nums.append(fn)

        season = "August" if depart_date.month == 8 else "DecJan"

        records.append({
            "checked_at":        checked_at,
            "season":            season,
            "depart_date":       depart_date.strftime("%Y-%m-%d"),
            "return_date":       return_date.strftime("%Y-%m-%d"),
            "price_eur":         float(price),
            "airlines":          ", ".join(dict.fromkeys(out_airlines)),  # deduplicated, ordered
            # Outbound
            "out_flight_nums":   ", ".join(out_flight_nums),
            "out_stops":         out_stops,
            "out_dep_time":      out_dep_time,
            "out_arr_time":      out_arr_time,
            "out_duration":      str(out_dur_min),
            "out_duration_fmt":  format_duration(out_dur_min),
            "out_layover_min":   out_layover_min if out_stops > 0 else "",
            "out_layover_fmt":   format_duration(out_layover_min) if out_stops > 0 else "",
            # Return
            "ret_airlines":      ", ".join(dict.fromkeys(ret_airlines)),
            "ret_flight_nums":   ", ".join(ret_flight_nums),
            "ret_stops":         ret_stops,
            "ret_dep_time":      ret_dep_time,
            "ret_arr_time":      ret_arr_time,
            "ret_duration":      str(ret_dur_min),
            "ret_duration_fmt":  format_duration(ret_dur_min),
            "ret_layover_min":   ret_layover_min if ret_legs and ret_stops > 0 else "",
            "ret_layover_fmt":   format_duration(ret_layover_min) if ret_legs and ret_stops and int(str(ret_stops) or 0) > 0 else "",
            # Disruption signals
            "airline_count":     len(all_airlines_this_date),
            "price_change_pct":  "",  # filled by store_data
        })

    return records, all_airlines_this_date


def main():
    from datetime import datetime
    checked_at  = date.today().strftime("%Y-%m-%d")
    print(f"[{datetime.utcnow().isoformat()}] Flight tracker starting...")

    date_pairs  = get_dates_to_track()
    all_records = []

    print(f"  Tracking {len(date_pairs)} departure dates:")
    for depart, ret in date_pairs:
        depart_str = depart.strftime("%Y-%m-%d")
        ret_str    = ret.strftime("%Y-%m-%d")
        print(f"  NCE→BEY  {depart_str} → {ret_str} ...")
        try:
            data    = search_flights(depart, ret)
            records, airlines_seen = parse_results(data, depart, ret, checked_at)

            if not records:
                print(f"    ⚠ ZERO results for {depart_str} — logging as disruption signal")
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

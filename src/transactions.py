import requests
from datetime import datetime, timedelta
from util import load_json_file, save_off_results

INTERESTING_TYPES = {"IL", "DTO", "REL", "CLM", "RET", "TRAD", "SIGN", "DFA"}


def fetch_transactions(days_back=3):
    """
    Fetch recent MLB transactions for all teams.
    Caches to data/transactions.json.
    Returns list of formatted transaction strings.
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)

    url = (
        "https://statsapi.mlb.com/api/v1/transactions"
        f"?startDate={start_date.strftime('%Y-%m-%d')}"
        f"&endDate={end_date.strftime('%Y-%m-%d')}"
        "&sportId=1"
    )

    formatted = []
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            transactions = data.get("transactions", [])

            # Sort by date descending, take most recent 10
            transactions.sort(key=lambda x: x.get("date", ""), reverse=True)

            for t in transactions[:10]:
                type_code = t.get("typeCode", "")
                if type_code not in INTERESTING_TYPES:
                    continue

                team_abbr = t.get("team", {}).get("abbreviation", "")
                person = t.get("person", {}).get("fullName", "")
                desc = t.get("typeDesc", type_code)
                date_str = t.get("date", "")[:10]  # YYYY-MM-DD

                # Format: "CHC: Bellinger - Placed on IL (4/15)"
                if person and team_abbr:
                    last_name = person.split()[-1] if person else ""
                    month_day = ""
                    if date_str:
                        try:
                            d = datetime.strptime(date_str, "%Y-%m-%d")
                            month_day = f" ({d.month}/{d.day})"
                        except Exception:
                            pass
                    formatted.append(f"{team_abbr}: {last_name} - {desc}{month_day}")

                if len(formatted) >= 5:
                    break

    except Exception as e:
        print(f"Error fetching transactions: {e}")

    # Cache with timestamp
    cache = {
        "transactions": formatted,
        "fetched_at": datetime.now().isoformat(),
    }
    save_off_results(cache, "transactions")
    return formatted


def get_cached_or_fetch(refresh_hours=2):
    """
    Return cached transactions if fresh, otherwise fetch new ones.
    """
    cache = load_json_file("transactions.json")
    if cache and cache.get("fetched_at"):
        try:
            fetched = datetime.fromisoformat(cache["fetched_at"])
            age_hours = (datetime.now() - fetched).total_seconds() / 3600
            if age_hours < refresh_hours:
                return cache.get("transactions", [])
        except Exception:
            pass
    return fetch_transactions()

"""Open-Meteo weather forecast client with on-disk TTL cache.

Public API:
    get_forecast(venue_id, lat, lon, game_utc_iso, cache_ttl_minutes=60) -> dict | None

Returns {'temp_f', 'wind_mph', 'wind_dir', 'precip_pct'} or None on any failure.
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.error import URLError, HTTPError

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_PATH = os.path.join(_REPO_ROOT, 'data', 'weather_cache.json')
_ENDPOINT = 'https://api.open-meteo.com/v1/forecast'
_COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']


def _compass_from_degrees(deg):
    """Compass from degrees."""
    if deg is None:
        return None
    idx = int((float(deg) + 22.5) // 45) % 8
    return _COMPASS[idx]


def _parse_iso_utc(iso_str):
    """Parse an ISO timestamp (with or without trailing Z) into a UTC datetime."""
    if not iso_str:
        return None
    s = iso_str.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_cache():
    """Load cache."""
    try:
        if not os.path.isfile(_CACHE_PATH):
            return {}
        with open(_CACHE_PATH, 'r') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_cache(cache):
    """Save cache."""
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f'weather: failed to write cache: {e}')


def _cache_key(venue_id, game_dt_utc):
    """Cache key."""
    return f'{venue_id}:{game_dt_utc.strftime("%Y-%m-%dT%H")}'


def _is_fresh(entry, ttl_minutes):
    """Is fresh."""
    fetched = _parse_iso_utc(entry.get('fetched_at'))
    if fetched is None:
        return False
    return datetime.now(timezone.utc) - fetched < timedelta(minutes=ttl_minutes)


def _fetch_open_meteo(lat, lon):
    """Fetch open meteo."""
    params = {
        'latitude': f'{lat:.4f}',
        'longitude': f'{lon:.4f}',
        'hourly': 'temperature_2m,precipitation_probability,wind_speed_10m,wind_direction_10m',
        'temperature_unit': 'fahrenheit',
        'wind_speed_unit': 'mph',
        'timezone': 'UTC',
        'forecast_days': 16,
    }
    url = f'{_ENDPOINT}?{urllib.parse.urlencode(params)}'
    req = urllib.request.Request(url, headers={'User-Agent': 'mlb-display/1.0'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _pick_hour(payload, game_dt_utc):
    """Pick hour."""
    hourly = payload.get('hourly') or {}
    times = hourly.get('time') or []
    if not times:
        return None
    target = game_dt_utc.strftime('%Y-%m-%dT%H:00')
    # Open-Meteo returns times in the requested timezone (UTC here) as 'YYYY-MM-DDTHH:MM'
    idx = None
    for i, t in enumerate(times):
        if t[:13] == target[:13]:
            idx = i
            break
    if idx is None:
        # Closest hour fallback
        try:
            parsed = [datetime.strptime(t, '%Y-%m-%dT%H:%M').replace(tzinfo=timezone.utc) for t in times]
            idx = min(range(len(parsed)), key=lambda i: abs(parsed[i] - game_dt_utc))
        except ValueError:
            return None

    def _at(field):
        """At."""
        series = hourly.get(field) or []
        return series[idx] if idx < len(series) else None

    temp = _at('temperature_2m')
    wind_mph = _at('wind_speed_10m')
    wind_dir_deg = _at('wind_direction_10m')
    precip = _at('precipitation_probability')

    result = {
        'temp_f': round(temp) if temp is not None else None,
        'wind_mph': round(wind_mph) if wind_mph is not None else None,
        'wind_dir': _compass_from_degrees(wind_dir_deg),
        'precip_pct': int(precip) if precip is not None else None,
    }
    if all(v is None for v in result.values()):
        return None
    return result


def get_forecast(venue_id, lat, lon, game_utc_iso, cache_ttl_minutes=60):
    """Return forecast dict for a game at (lat, lon) starting at game_utc_iso, or None."""
    game_dt = _parse_iso_utc(game_utc_iso)
    if game_dt is None or lat is None or lon is None:
        return None

    cache = _load_cache()
    key = _cache_key(venue_id, game_dt)
    entry = cache.get(key)
    if entry and _is_fresh(entry, cache_ttl_minutes) and 'forecast' in entry:
        return entry['forecast']

    try:
        payload = _fetch_open_meteo(float(lat), float(lon))
    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError, ValueError) as e:
        print(f'weather: fetch failed for venue {venue_id}: {e}')
        return entry.get('forecast') if entry and 'forecast' in entry else None

    forecast = _pick_hour(payload, game_dt)
    if forecast is None:
        return entry.get('forecast') if entry and 'forecast' in entry else None

    cache[key] = {
        'forecast': forecast,
        'fetched_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    _prune_cache(cache)
    _save_cache(cache)
    return forecast


def _prune_cache(cache, keep_days=3):
    """Prune cache."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    stale = []
    for key in list(cache.keys()):
        try:
            _, hour_str = key.split(':', 1)
            dt = datetime.strptime(hour_str, '%Y-%m-%dT%H').replace(tzinfo=timezone.utc)
            if dt < cutoff:
                stale.append(key)
        except (ValueError, AttributeError):
            continue
    for k in stale:
        cache.pop(k, None)

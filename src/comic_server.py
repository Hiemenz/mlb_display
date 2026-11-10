"""Web pages for the comic screen: the QR code on the panel opens a whole story arc.

A Flask blueprint registered on the config server (src/config_server.py), so one
service on one port (config_server_port, default 8080) does both jobs:

    /arc/<YYYY-MM-DD>            every strip of the arc starting that day, in order, "Day x of N"
    /comic/img/<YYYY-MM-DD>      one cached strip image

Both take ?comic=<name> (default peanuts). Strips are served from the local,
gitignored data/comics cache, to your own LAN only (no authentication, like the
config server), so the artwork never goes anywhere else.
"""
import re
from datetime import date

from flask import Blueprint, abort, render_template_string, request, send_file

import fetch_comic as fc

comic_bp = Blueprint('comic', __name__)

_NAME_RE = re.compile(r'^[A-Za-z0-9_-]{1,40}$')

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<style>
  :root { --bg:#f6f4ee; --fg:#1b1b1b; --muted:#666; --rule:#d8d4c8; }
  @media (prefers-color-scheme: dark) { :root { --bg:#16161a; --fg:#eee; --muted:#9a9aa5; --rule:#33333a; } }
  body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.4 system-ui, sans-serif; }
  main { max-width:760px; margin:0 auto; padding:16px; }
  h1 { font-size:1.2rem; margin:0 0 4px; }
  .sub, nav { color:var(--muted); font-size:.9rem; }
  figure { margin:20px 0 0; }
  figcaption { font-size:.9rem; margin-bottom:6px; }
  img { width:100%; height:auto; background:#fff; border:1px solid var(--rule); display:block; }
  nav { display:flex; justify-content:space-between; margin:20px 0; }
  a { color:inherit; }
</style></head>
<body><main>
<h1>{{ title }}</h1>
<div class="sub">{{ n }} strips, {{ first }} to {{ last }}</div>
{% for d, i in strips %}
<figure><figcaption>Day {{ i }} of {{ n }} &middot; {{ d }}</figcaption>
<img src="{{ url_for('comic.strip_image', day=d, comic=comic) }}" alt="Strip {{ i }} of {{ n }}, {{ d }}" loading="lazy"></figure>
{% endfor %}
<nav>
 {% if prev %}<a href="{{ url_for('comic.arc_page', start=prev, comic=comic) }}">&larr; Previous arc</a>{% else %}<span></span>{% endif %}
 {% if nxt %}<a href="{{ url_for('comic.arc_page', start=nxt, comic=comic) }}">Next arc &rarr;</a>{% endif %}
</nav>
</main></body></html>"""


def _comic_name():
    name = request.args.get('comic', 'peanuts')
    if not _NAME_RE.match(name):
        abort(400)
    return name


def _parse_day(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        abort(404)


@comic_bp.route('/arc/<start>')
def arc_page(start):
    comic = _comic_name()
    found = fc.find_arc(fc.load_prefs(comic), _parse_day(start))
    if found is None:
        abort(404)
    ds, prev, nxt = found
    return render_template_string(
        _PAGE, title=f'{comic.title()} story arc', comic=comic, n=len(ds), first=ds[0].isoformat(),
        last=ds[-1].isoformat(), strips=[(d.isoformat(), i + 1) for i, d in enumerate(ds)],
        prev=prev.isoformat() if prev else None, nxt=nxt.isoformat() if nxt else None)


@comic_bp.route('/comic/img/<day>')
def strip_image(day):
    path = fc.LocalCacheSource(_comic_name())._path(_parse_day(day))
    if path is None:
        abort(404)
    return send_file(path)

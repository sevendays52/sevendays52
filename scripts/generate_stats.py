#!/usr/bin/env python3
"""Generate Monochrome Lab SVG cards (dark & light):
- Left: All repository languages (circular donut chart + table)
- Right top: 27-week contribution heatmap (grass)
- Right bottom: Today's push & commit metrics (KST)
"""

from __future__ import annotations

import datetime as dt
import html
import json
import math
import os
import urllib.error
import urllib.request
from pathlib import Path

USERNAME = os.environ.get("GITHUB_USERNAME", "sevendays52")
TOKEN = os.environ.get("METRICS_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
OUT_DIR = Path(os.environ.get("OUT_DIR", "assets"))
TZ_OFFSET_HOURS = int(os.environ.get("TZ_OFFSET_HOURS", "9"))  # Default KST (+09:00)

THEMES = {
    "dark": {
        "bg": "#0d1117",
        "panel": "#161b22",
        "border": "#30363d",
        "divider": "#21262d",
        "text_primary": "#f0f6fc",
        "text_secondary": "#8b949e",
        "text_muted": "#6e7681",
        "track": "#21262d",
        "heat": ["#161b22", "#30363d", "#6e7681", "#9ea7b3", "#f0f6fc"],
    },
    "light": {
        "bg": "#ffffff",
        "panel": "#f6f8fa",
        "border": "#d0d7de",
        "divider": "#eaeef2",
        "text_primary": "#1f2328",
        "text_secondary": "#59636e",
        "text_muted": "#8c959f",
        "track": "#eaeef2",
        "heat": ["#eaeef2", "#d0d7de", "#8c959f", "#59636e", "#1f2328"],
    },
}

DEFAULT_LANG_COLORS = {
    "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a",
    "Python": "#3572A5",
    "C#": "#178600",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "ShaderLab": "#222c37",
    "HLSL": "#aace60",
    "Shell": "#89e051",
    "PowerShell": "#012456",
    "Jupyter Notebook": "#DA5B0B",
    "C++": "#f34b7d",
    "Go": "#00ADD8",
    "Rust": "#dea584",
}

GRAPHQL_USER_QUERY = """
query($login: String!, $todayStart: DateTime!, $todayEnd: DateTime!) {
  user(login: $login) {
    repositories(first: 100, ownerAffiliations: [OWNER], isArchived: false) {
      totalCount
      nodes {
        name
        isPrivate
        pushedAt
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node {
              name
              color
            }
          }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
    todayContributions: contributionsCollection(from: $todayStart, to: $todayEnd) {
      totalCommitContributions
      restrictedContributionsCount
    }
  }
}
"""

GRAPHQL_VIEWER_QUERY = """
query($todayStart: DateTime!, $todayEnd: DateTime!) {
  viewer {
    login
    repositories(first: 100, ownerAffiliations: [OWNER], isArchived: false) {
      totalCount
      nodes {
        name
        isPrivate
        pushedAt
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node {
              name
              color
            }
          }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
    todayContributions: contributionsCollection(from: $todayStart, to: $todayEnd) {
      totalCommitContributions
      restrictedContributionsCount
    }
  }
}
"""


def http_json(url: str, method: str = "GET", body: dict | None = None, token: str = "") -> dict | list:
    headers = {
        "User-Agent": "sevendays52-profile-stats",
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def local_today_bounds(offset_hours: int) -> tuple[dt.timezone, str, str, str]:
    tz = dt.timezone(dt.timedelta(hours=offset_hours))
    now_local = dt.datetime.now(tz)
    today_str = now_local.strftime("%Y-%m-%d")
    start_utc = (
        now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(dt.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    end_utc = (
        now_local.replace(hour=23, minute=59, second=59, microsecond=0)
        .astimezone(dt.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    return tz, today_str, start_utc, end_utc


def parse_iso_local_date(iso_str: str | None, tz: dt.timezone) -> str | None:
    if not iso_str:
        return None
    parsed = dt.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return parsed.astimezone(tz).strftime("%Y-%m-%d")


def fetch_today_push_events(username: str, token: str, tz: dt.timezone, today_str: str) -> tuple[int, int]:
    """Return (push_events_today, push_commits_today) from GitHub Events API."""
    endpoints = (
        [f"https://api.github.com/users/{username}/events?per_page=100", f"https://api.github.com/users/{username}/events/public?per_page=100"]
        if token
        else [f"https://api.github.com/users/{username}/events/public?per_page=100"]
    )
    events: list = []
    for url in endpoints:
        try:
            events = http_json(url, token=token)
            if isinstance(events, list):
                break
        except urllib.error.URLError:
            continue

    pushes_today = 0
    commits_today = 0
    for ev in events:
        if ev.get("type") != "PushEvent":
            continue
        if parse_iso_local_date(ev.get("created_at"), tz) == today_str:
            pushes_today += 1
            payload = ev.get("payload", {})
            commits_today += payload.get("size") or len(payload.get("commits", [])) or 1
    return pushes_today, commits_today


def fetch_via_graphql(username: str, token: str) -> dict:
    tz, today_str, start_utc, end_utc = local_today_bounds(TZ_OFFSET_HOURS)
    target = None
    include_private = False

    if os.environ.get("METRICS_TOKEN"):
        resp = http_json(
            "https://api.github.com/graphql",
            method="POST",
            body={
                "query": GRAPHQL_VIEWER_QUERY,
                "variables": {"todayStart": start_utc, "todayEnd": end_utc},
            },
            token=token,
        )
        viewer = (resp.get("data") or {}).get("viewer")
        if viewer and viewer.get("login", "").lower() == username.lower():
            target = viewer
            include_private = True

    if target is None:
        resp = http_json(
            "https://api.github.com/graphql",
            method="POST",
            body={
                "query": GRAPHQL_USER_QUERY,
                "variables": {"login": username, "todayStart": start_utc, "todayEnd": end_utc},
            },
            token=token,
        )
        if "errors" in resp and not resp.get("data"):
            raise RuntimeError(f"GraphQL error: {resp['errors']}")
        target = resp["data"]["user"]

    repos = target["repositories"]["nodes"]
    lang_totals: dict[str, int] = {}
    lang_colors: dict[str, str] = {}
    last_push: str | None = None
    private_count = 0
    repos_pushed_today = 0

    for repo in repos:
        if repo.get("isPrivate"):
            private_count += 1
        pushed_at = repo.get("pushedAt")
        if pushed_at and (last_push is None or pushed_at > last_push):
            last_push = pushed_at
        if parse_iso_local_date(pushed_at, tz) == today_str:
            repos_pushed_today += 1
        for edge in repo.get("languages", {}).get("edges", []):
            name = edge["node"]["name"]
            size = edge["size"]
            color = edge["node"].get("color") or DEFAULT_LANG_COLORS.get(name, "#8b949e")
            lang_totals[name] = lang_totals.get(name, 0) + size
            lang_colors.setdefault(name, color)

    contrib = target["contributionsCollection"]
    today_contrib = target["todayContributions"]
    today_commits = today_contrib["totalCommitContributions"] + today_contrib["restrictedContributionsCount"]
    pushes_today, _ = fetch_today_push_events(username, token, tz, today_str)
    today_pushes = max(pushes_today, repos_pushed_today)

    weeks = contrib["contributionCalendar"]["weeks"]
    days = [d for w in weeks for d in w["contributionDays"]]
    days_26w = days[-182:]  # 26 weeks * 7 days
    last_7d_commits = sum(d["contributionCount"] for d in days[-7:])
    last_30d_commits = sum(d["contributionCount"] for d in days[-30:])

    return {
        "repo_count": target["repositories"]["totalCount"],
        "private_count": private_count,
        "total_contributions": contrib["contributionCalendar"]["totalContributions"],
        "last_push": parse_iso_local_date(last_push, tz) or "N/A",
        "today_date": today_str,
        "today_pushes": today_pushes,
        "today_commits": today_commits,
        "last_7d_commits": last_7d_commits,
        "last_30d_commits": last_30d_commits,
        "languages": sorted(
            [(name, size, lang_colors.get(name, "#8b949e")) for name, size in lang_totals.items()],
            key=lambda x: -x[1],
        ),
        "days": days_26w,
        "scope": "public + private" if include_private else "public",
    }


def fetch_via_rest(username: str) -> dict:
    tz, today_str, _, _ = local_today_bounds(TZ_OFFSET_HOURS)
    repos = http_json(f"https://api.github.com/users/{username}/repos?per_page=100&type=owner")
    lang_totals: dict[str, int] = {}
    last_push: str | None = None
    repos_pushed_today = 0

    for repo in repos:
        if repo.get("archived"):
            continue
        pushed_at = repo.get("pushed_at")
        if pushed_at and (last_push is None or pushed_at > last_push):
            last_push = pushed_at
        if parse_iso_local_date(pushed_at, tz) == today_str:
            repos_pushed_today += 1
        langs = http_json(repo["languages_url"])
        for name, size in langs.items():
            lang_totals[name] = lang_totals.get(name, 0) + size

    events = http_json(f"https://api.github.com/users/{username}/events/public?per_page=100")
    day_counts: dict[str, int] = {}
    pushes_today = 0
    commits_today = 0
    total_events_commits = 0

    for ev in events:
        if ev.get("type") != "PushEvent":
            continue
        ev_date = parse_iso_local_date(ev.get("created_at"), tz)
        payload = ev.get("payload", {})
        c_count = payload.get("size") or len(payload.get("commits", [])) or 1
        if ev_date:
            day_counts[ev_date] = day_counts.get(ev_date, 0) + c_count
            total_events_commits += c_count
            if ev_date == today_str:
                pushes_today += 1
                commits_today += c_count

    today_date = dt.datetime.now(tz).date()
    days = []
    for offset in range(181, -1, -1):
        d = (today_date - dt.timedelta(days=offset)).isoformat()
        days.append({"date": d, "contributionCount": day_counts.get(d, 0)})

    return {
        "repo_count": len(repos),
        "private_count": 0,
        "total_contributions": total_events_commits,
        "last_push": parse_iso_local_date(last_push, tz) or "N/A",
        "today_date": today_str,
        "today_pushes": max(pushes_today, repos_pushed_today),
        "today_commits": commits_today,
        "last_7d_commits": sum(d["contributionCount"] for d in days[-7:]),
        "last_30d_commits": sum(d["contributionCount"] for d in days[-30:]),
        "languages": sorted(
            [(name, size, DEFAULT_LANG_COLORS.get(name, "#8b949e")) for name, size in lang_totals.items()],
            key=lambda x: -x[1],
        ),
        "days": days,
        "scope": "public",
    }


def format_relative_push(last_push: str, today_date: str) -> str:
    if last_push == "N/A":
        return "N/A"
    try:
        delta = (dt.date.fromisoformat(today_date) - dt.date.fromisoformat(last_push)).days
    except ValueError:
        return last_push
    if delta <= 0:
        return "today"
    if delta == 1:
        return "1d ago"
    return f"{delta}d ago"


def format_pct(ratio: float) -> str:
    pct = ratio * 100
    if pct >= 0.1:
        return f"{pct:.1f}%"
    return "&lt;0.1%"


def heat_level(count: int, max_count: int) -> int:
    if count <= 0:
        return 0
    if max_count <= 1:
        return 4
    ratio = count / max_count
    if ratio <= 0.25:
        return 1
    if ratio <= 0.5:
        return 2
    if ratio <= 0.75:
        return 3
    return 4


def render_languages_svg(stats: dict, theme_name: str) -> str:
    t = THEMES[theme_name]
    width = 392
    pad_x = 26
    inner_w = width - pad_x * 2  # 340px

    languages = stats["languages"]
    total_bytes = sum(size for _, size, _ in languages) or 1

    title_y = 32
    donut_cx = width / 2
    donut_cy = 98
    donut_r = 42
    donut_stroke = 10
    circumference = 2 * math.pi * donut_r

    donut_arcs = []
    cum_len = 0.0
    for name, size, color in languages:
        seg_len = (size / total_bytes) * circumference
        donut_arcs.append(
            f'<circle cx="{donut_cx:.1f}" cy="{donut_cy:.1f}" r="{donut_r}" '
            f'fill="none" stroke="{html.escape(color)}" stroke-width="{donut_stroke}" '
            f'stroke-dasharray="{seg_len:.3f} {circumference:.3f}" '
            f'stroke-dashoffset="{-cum_len:.3f}" '
            f'transform="rotate(-90 {donut_cx:.1f} {donut_cy:.1f})" />'
        )
        cum_len += seg_len

    table_header_y = 170
    table_start_y = 192
    row_h = 22
    table_rows = []
    bar_x = 146
    bar_max_w = 130
    for idx, (name, size, color) in enumerate(languages):
        ry = table_start_y + idx * row_h
        ratio = size / total_bytes
        pct = format_pct(ratio)
        fill_w = max(2.0, ratio * bar_max_w)
        row_line = (
            f'<line x1="0" y1="8" x2="{inner_w}" y2="8" stroke="{t["divider"]}" stroke-opacity="0.6" />'
            if idx < len(languages) - 1
            else ""
        )
        table_rows.append(
            f'<g transform="translate({pad_x}, {ry})">'
            f'<circle cx="4" cy="-3.5" r="3.5" fill="{html.escape(color)}" />'
            f'<text x="14" y="0" fill="{t["text_primary"]}" font-family="-apple-system, BlinkMacSystemFont, \'Segoe UI\', Helvetica, Arial, sans-serif" font-size="11.5" font-weight="500">{html.escape(name)}</text>'
            f'<rect x="{bar_x}" y="-6" width="{bar_max_w}" height="4" rx="2" fill="{t["track"]}" />'
            f'<rect x="{bar_x}" y="-6" width="{fill_w:.1f}" height="4" rx="2" fill="{html.escape(color)}" />'
            f'<text x="{inner_w}" y="0" text-anchor="end" fill="{t["text_secondary"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="11">{pct}</text>'
            f"{row_line}"
            f"</g>"
        )

    height = table_start_y + max(1, len(languages)) * row_h + 18

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none">
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" fill="{t["bg"]}" stroke="{t["border"]}" />

  <text x="{pad_x}" y="{title_y}" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10.5" letter-spacing="1.4">
    ALL LANGUAGES
  </text>

  <g>
    <circle cx="{donut_cx:.1f}" cy="{donut_cy:.1f}" r="{donut_r}" fill="none" stroke="{t["track"]}" stroke-width="{donut_stroke}" />
    {"".join(donut_arcs)}
    <text x="{donut_cx:.1f}" y="{donut_cy + 3:.1f}" text-anchor="middle" fill="{t["text_primary"]}" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif" font-size="20" font-weight="600">{len(languages)}</text>
    <text x="{donut_cx:.1f}" y="{donut_cy + 17:.1f}" text-anchor="middle" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="9" letter-spacing="1.2">LANGS</text>
  </g>

  <g transform="translate({pad_x}, {table_header_y})">
    <text x="0" y="0" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="9.5" letter-spacing="1">LANGUAGE</text>
    <text x="{inner_w}" y="0" text-anchor="end" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="9.5" letter-spacing="1">SHARE</text>
    <line x1="0" y1="7" x2="{inner_w}" y2="7" stroke="{t["divider"]}" />
  </g>

  {"".join(table_rows)}
</svg>
"""


def render_activity_svg(stats: dict, theme_name: str) -> str:
    t = THEMES[theme_name]
    width = 392
    pad_x = 26
    inner_w = width - pad_x * 2  # 340px

    title_y = 32
    grass_y = 50
    days = stats["days"]
    if len(days) < 182:
        days = ([{"date": "", "contributionCount": 0}] * (182 - len(days))) + days
    max_day = max((d["contributionCount"] for d in days), default=1) or 1

    cell = 10
    gap = 3
    grass_w = 26 * (cell + gap) - gap  # 335px
    grass_x = pad_x + (inner_w - grass_w) / 2
    grass_cells = []
    for i, d in enumerate(days):
        col = i // 7
        row = i % 7
        gx = col * (cell + gap)
        gy = row * (cell + gap)
        lvl = heat_level(d["contributionCount"], max_day)
        grass_cells.append(
            f'<rect x="{gx}" y="{gy}" width="{cell}" height="{cell}" rx="2" fill="{t["heat"][lvl]}" />'
        )
    grass_h = 7 * (cell + gap) - gap  # 88px
    legend_y = grass_y + grass_h + 20

    legend_boxes = []
    for lvl in range(5):
        lx = inner_w - 58 + lvl * 12
        legend_boxes.append(f'<rect x="{lx}" y="-8" width="9" height="9" rx="1.5" fill="{t["heat"][lvl]}" />')

    mid_div_y = legend_y + 18
    cadence_title_y = mid_div_y + 26
    cards_y = cadence_title_y + 16
    card_gap = 12
    card_w = (inner_w - card_gap) / 2  # 164px
    card_h = 84
    meta_y = cards_y + card_h + 24
    height = meta_y + 20

    now_local = dt.datetime.now(dt.timezone(dt.timedelta(hours=TZ_OFFSET_HOURS))).strftime("%Y-%m-%d %H:%M")
    tz_label = f"UTC{TZ_OFFSET_HOURS:+d}" if TZ_OFFSET_HOURS != 9 else "KST"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none">
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" fill="{t["bg"]}" stroke="{t["border"]}" />

  <text x="{pad_x}" y="{title_y}" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10.5" letter-spacing="1.4">
    CONTRIBUTION GRAPH (26W)
  </text>

  <g transform="translate({grass_x:.1f}, {grass_y})">
    {"".join(grass_cells)}
  </g>

  <g transform="translate({pad_x}, {legend_y})">
    <text x="0" y="0" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10">7d total: {stats["last_7d_commits"]}</text>
    <text x="{inner_w - 66}" y="0" text-anchor="end" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="9.5">Less</text>
    {"".join(legend_boxes)}
    <text x="{inner_w}" y="0" text-anchor="end" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="9.5">More</text>
  </g>

  <line x1="{pad_x}" y1="{mid_div_y}" x2="{width - pad_x}" y2="{mid_div_y}" stroke="{t["divider"]}" />

  <text x="{pad_x}" y="{cadence_title_y}" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10.5" letter-spacing="1.4">
    RECENT CADENCE
  </text>
  <text x="{width - pad_x}" y="{cadence_title_y}" text-anchor="end" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10">
    1y {stats["total_contributions"]:,} total
  </text>

  <g transform="translate({pad_x}, {cards_y})">
    <rect x="0.5" y="0.5" width="{card_w - 1:.1f}" height="{card_h - 1}" rx="8" fill="{t["panel"]}" stroke="{t["border"]}" />
    <text x="14" y="24" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10" letter-spacing="1.1">LAST PUSH</text>
    <text x="14" y="57" fill="{t["text_primary"]}" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif" font-size="22" font-weight="600">{html.escape(format_relative_push(stats["last_push"], stats["today_date"]))}</text>
    <text x="{card_w - 14:.1f}" y="57" text-anchor="end" fill="{t["text_secondary"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="9.5">{html.escape(stats["last_push"])}</text>

    <g transform="translate({card_w + card_gap:.1f}, 0)">
      <rect x="0.5" y="0.5" width="{card_w - 1:.1f}" height="{card_h - 1}" rx="8" fill="{t["panel"]}" stroke="{t["border"]}" />
      <text x="14" y="24" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10" letter-spacing="1.1">30D ACTIVITY</text>
      <text x="14" y="57" fill="{t["text_primary"]}" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif" font-size="24" font-weight="600">{stats["last_30d_commits"]:,}</text>
      <text x="{card_w - 14:.1f}" y="57" text-anchor="end" fill="{t["text_secondary"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="9.5">events</text>
    </g>
  </g>

  <text x="{width - pad_x}" y="{meta_y}" text-anchor="end" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="9.5">
    synced · {now_local} {tz_label}
  </text>
</svg>
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if TOKEN:
        try:
            stats = fetch_via_graphql(USERNAME, TOKEN)
        except (urllib.error.URLError, RuntimeError) as exc:
            print(f"GraphQL failed ({exc}); falling back to REST API.")
            stats = fetch_via_rest(USERNAME)
    else:
        stats = fetch_via_rest(USERNAME)

    for theme_name in ("dark", "light"):
        lang_path = OUT_DIR / f"lang-{theme_name}.svg"
        act_path = OUT_DIR / f"activity-{theme_name}.svg"
        lang_path.write_text(render_languages_svg(stats, theme_name), encoding="utf-8")
        act_path.write_text(render_activity_svg(stats, theme_name), encoding="utf-8")
        print(
            f"Wrote {lang_path.name} & {act_path.name} (scope={stats['scope']}, repos={stats['repo_count']}, "
            f"private={stats['private_count']}, {len(stats['languages'])} languages, last_push={stats['last_push']})"
        )


if __name__ == "__main__":
    main()

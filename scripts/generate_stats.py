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
import re
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
    "Lua": "#000080",
    "PLpgSQL": "#336790",
    "Kotlin": "#A97BFF",
    "Swift": "#F05138",
    "Shell": "#89e051",
    "PowerShell": "#012456",
    "Jupyter Notebook": "#DA5B0B",
    "C": "#555555",
    "C++": "#f34b7d",
    "Go": "#00ADD8",
    "Rust": "#dea584",
    "Dockerfile": "#384d54",
    "Makefile": "#427819",
    "Wolfram Language": "#dd1100",
}

IGNORED_ARTIFACT_LANGS = {"Batchfile", "NSIS", "Smalltalk", "Mathematica", "PowerShell"}

AGENDA_RULES = [
    (
        "AI Engineering",
        "LLM · OCR · Labeling · Pipelines",
        ("ai", "ocr", "llm", "labeling", "codex", "model", "ml", "agent", "gpt", "diffusion", "vision"),
        {"Python", "Jupyter Notebook"},
    ),
    (
        "Data",
        "Analytics · SQL · Trends",
        ("data", "analysis", "trend", "labeling", "sql", "db", "stats", "metric", "analytics", "crawl", "scrape"),
        {"PLpgSQL", "Wolfram Language", "Python"},
    ),
    (
        "Unity 3D",
        "C# · Shaders · 3D Rigging",
        ("unity", "rig", "avatar", "mesh", "3d", "fps", "game", "horror", "shader", "vr", "ar"),
        {"C#", "ShaderLab", "HLSL", "Lua"},
    ),
    (
        "Virtual Streaming",
        "VTuber IP · Live Platforms",
        ("virtual", "soop", "chzzk", "stream", "vtuber", "avatar", "fan", "live", "broadcast"),
        set(),
    ),
]

GRAPHQL_USER_QUERY = """
query($login: String!, $todayStart: DateTime!, $todayEnd: DateTime!) {
  user(login: $login) {
    repositories(first: 100, ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER], isArchived: false) {
      nodes {
        nameWithOwner
        description
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
    repositoriesContributedTo(first: 100, contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY], includeUserRepositories: true) {
      nodes {
        nameWithOwner
        description
        isPrivate
        isArchived
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
    repositories(first: 100, ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER], isArchived: false) {
      nodes {
        nameWithOwner
        description
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
    repositoriesContributedTo(first: 100, contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY], includeUserRepositories: true) {
      nodes {
        nameWithOwner
        description
        isPrivate
        isArchived
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


def classify_agendas(repo_records: list[tuple[str, set[str]]]) -> list[tuple[str, str, int]]:
    """Count repositories matching each domain agenda using generic keywords and languages."""
    counts = {label: 0 for label, _, _, _ in AGENDA_RULES}
    for text, langs in repo_records:
        for label, _, keywords, lang_triggers in AGENDA_RULES:
            if any(kw in text for kw in keywords) or bool(langs & lang_triggers):
                counts[label] += 1
    results = [(label, subtitle, counts[label]) for label, subtitle, _, _ in AGENDA_RULES]
    results.sort(key=lambda x: -x[2])
    return results


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

    affiliated_nodes = target["repositories"]["nodes"]
    contributed_nodes = [
        n for n in target.get("repositoriesContributedTo", {}).get("nodes", []) if not n.get("isArchived")
    ]
    merged_repos: dict[str, dict] = {}
    for repo in affiliated_nodes + contributed_nodes:
        merged_repos[repo["nameWithOwner"]] = repo

    repos = list(merged_repos.values())
    lang_totals: dict[str, int] = {}
    lang_repo_counts: dict[str, int] = {}
    lang_colors: dict[str, str] = {}
    repo_records: list[tuple[str, set[str]]] = []
    last_push: str | None = None
    private_count = 0
    repos_pushed_today = 0

    for repo in affiliated_nodes:
        pushed_at = repo.get("pushedAt")
        if pushed_at and (last_push is None or pushed_at > last_push):
            last_push = pushed_at
        if parse_iso_local_date(pushed_at, tz) == today_str:
            repos_pushed_today += 1

    for repo in repos:
        if repo.get("isPrivate"):
            private_count += 1
        repo_langs: set[str] = set()
        for edge in repo.get("languages", {}).get("edges", []):
            name = edge["node"]["name"]
            size = edge["size"]
            color = edge["node"].get("color") or DEFAULT_LANG_COLORS.get(name, "#8b949e")
            lang_totals[name] = lang_totals.get(name, 0) + size
            lang_colors.setdefault(name, color)
            if name not in repo_langs:
                lang_repo_counts[name] = lang_repo_counts.get(name, 0) + 1
                repo_langs.add(name)
        text = f"{repo['nameWithOwner']} {repo.get('description') or ''}".lower()
        repo_records.append((text, repo_langs))

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

    # Ensure last_push also reflects contributions on org repos that weren't in affiliated_nodes
    cal_last_active = max((d["date"] for d in days if d["contributionCount"] > 0), default="")
    last_push_local = parse_iso_local_date(last_push, tz) or ""
    effective_last_push = max(last_push_local, cal_last_active) or "N/A"

    languages = [
        (name, lang_repo_counts.get(name, 1), size, lang_colors.get(name, "#8b949e"))
        for name, size in lang_totals.items()
        if name not in IGNORED_ARTIFACT_LANGS
    ]
    languages.sort(key=lambda x: (-x[1], -x[2]))

    return {
        "repo_count": len(repos),
        "private_count": private_count,
        "total_contributions": contrib["contributionCalendar"]["totalContributions"],
        "last_push": effective_last_push,
        "today_date": today_str,
        "today_pushes": today_pushes,
        "today_commits": today_commits,
        "last_7d_commits": last_7d_commits,
        "last_30d_commits": last_30d_commits,
        "agendas": classify_agendas(repo_records),
        "languages": languages,
        "days": days_26w,
        "scope": "public + private + org/collab" if include_private else "public",
    }


def fetch_via_rest(username: str) -> dict:
    tz, today_str, _, _ = local_today_bounds(TZ_OFFSET_HOURS)
    repos = http_json(f"https://api.github.com/users/{username}/repos?per_page=100&type=owner")
    lang_totals: dict[str, int] = {}
    lang_repo_counts: dict[str, int] = {}
    repo_records: list[tuple[str, set[str]]] = []
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
            lang_repo_counts[name] = lang_repo_counts.get(name, 0) + 1
        text = f"{repo.get('full_name', repo['name'])} {repo.get('description') or ''}".lower()
        repo_records.append((text, set(langs.keys())))

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

    languages = [
        (name, lang_repo_counts.get(name, 1), size, DEFAULT_LANG_COLORS.get(name, "#8b949e"))
        for name, size in lang_totals.items()
        if name not in IGNORED_ARTIFACT_LANGS
    ]
    languages.sort(key=lambda x: (-x[1], -x[2]))

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
        "agendas": classify_agendas(repo_records),
        "languages": languages,
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


def estimate_text_width(text: str) -> float:
    w = 0.0
    for ch in text:
        if ch in "iljtIf.,!|:; ":
            w += 4.2
        elif ch in "MWmw@#%&":
            w += 8.6
        elif ch.isupper():
            w += 7.2
        else:
            w += 6.2
    return w


def compute_pill_layout(languages: list[tuple[str, int, int, str]], max_w: float) -> tuple[list[tuple[str, str, float, float, float]], int]:
    """Pack language pill badges cleanly within max_w and return (items, total_height)."""
    pill_h = 22.0
    gap_x = 6.0
    gap_y = 6.0
    cur_x = 0.0
    cur_y = 0.0
    placed: list[tuple[str, str, float, float, float]] = []

    for name, _, _, color in languages:
        pw = round(20.0 + estimate_text_width(name) + 10.0, 1)
        if cur_x > 0 and cur_x + pw > max_w:
            cur_x = 0.0
            cur_y += pill_h + gap_y
        placed.append((name, color, cur_x, cur_y, pw))
        cur_x += pw + gap_x

    total_h = int(cur_y + pill_h) if placed else 0
    return placed, total_h


def render_languages_svg(stats: dict, theme_name: str, fixed_height: int) -> str:
    t = THEMES[theme_name]
    width = 392
    pad_x = 26
    inner_w = width - pad_x * 2  # 340px

    agendas = stats["agendas"]
    max_agenda = max((count for _, _, count in agendas), default=1) or 1

    title_y = 32
    agenda_start_y = 62
    agenda_step = 48

    agenda_rows = []
    bar_shades = [t["heat"][4], t["heat"][3], t["heat"][2], t["heat"][2]]
    for idx, (label, subtitle, count) in enumerate(agendas):
        ay = agenda_start_y + idx * agenda_step
        ratio = count / max_agenda if max_agenda > 0 else 0.0
        fill_w = 0.0 if count == 0 else max(10.0, ratio * (inner_w * 0.9))
        shade = bar_shades[min(idx, len(bar_shades) - 1)]
        agenda_rows.append(
            f'<g transform="translate({pad_x}, {ay})">'
            f'<text x="0" y="0" fill="{t["text_primary"]}" font-family="-apple-system, BlinkMacSystemFont, \'Segoe UI\', Helvetica, Arial, sans-serif" font-size="12" font-weight="600">{html.escape(label)}</text>'
            f'<text x="{inner_w}" y="0" text-anchor="end" fill="{t["text_secondary"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10.5">{count} repos</text>'
            f'<rect x="0" y="9" width="{inner_w}" height="6" rx="3" fill="{t["track"]}" />'
            f'<rect x="0" y="9" width="{fill_w:.1f}" height="6" rx="3" fill="{shade}" />'
            f'<text x="0" y="29" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="9.5">{html.escape(subtitle)}</text>'
            f"</g>"
        )

    mid_div_y = 262
    lang_title_y = 286
    pills_y = 302
    placed_pills, _ = compute_pill_layout(stats["languages"], inner_w)

    pill_nodes = []
    for name, color, px, py, pw in placed_pills:
        pill_nodes.append(
            f'<g transform="translate({px:.1f}, {py:.1f})">'
            f'<rect x="0.5" y="0.5" width="{pw - 1:.1f}" height="21" rx="6" fill="{t["panel"]}" stroke="{t["border"]}" />'
            f'<circle cx="11" cy="11" r="3" fill="{html.escape(color)}" />'
            f'<text x="19" y="14.5" fill="{t["text_primary"]}" font-family="-apple-system, BlinkMacSystemFont, \'Segoe UI\', Helvetica, Arial, sans-serif" font-size="11" font-weight="500">{html.escape(name)}</text>'
            f"</g>"
        )

    height = fixed_height

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none">
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" fill="{t["bg"]}" stroke="{t["border"]}" />

  <text x="{pad_x}" y="{title_y}" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10.5" letter-spacing="1.4">
    AGENDA FOCUS
  </text>
  <text x="{width - pad_x}" y="{title_y}" text-anchor="end" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10">
    {stats["repo_count"]} repos
  </text>

  {"".join(agenda_rows)}

  <line x1="{pad_x}" y1="{mid_div_y}" x2="{width - pad_x}" y2="{mid_div_y}" stroke="{t["divider"]}" />

  <text x="{pad_x}" y="{lang_title_y}" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10.5" letter-spacing="1.4">
    LANGUAGES USED
  </text>
  <text x="{width - pad_x}" y="{lang_title_y}" text-anchor="end" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10">
    {len(stats["languages"])} langs
  </text>

  <g transform="translate({pad_x}, {pills_y})">
    {"".join(pill_nodes)}
  </g>
</svg>
"""


def render_activity_svg(stats: dict, theme_name: str, fixed_height: int) -> str:
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
    legend_y = grass_y + grass_h + 18

    legend_boxes = []
    for lvl in range(5):
        lx = inner_w - 58 + lvl * 12
        legend_boxes.append(f'<rect x="{lx}" y="-8" width="9" height="9" rx="1.5" fill="{t["heat"][lvl]}" />')

    mid_div_y = legend_y + 18
    cadence_title_y = mid_div_y + 24
    cards_y = cadence_title_y + 14
    card_gap = 12
    card_w = (inner_w - card_gap) / 2  # 164px
    card_h = 78

    div2_y = cards_y + card_h + 20
    bars_title_y = div2_y + 24
    bars_y = bars_title_y + 14
    meta_y = fixed_height - 20
    bars_h = max(44, meta_y - 22 - bars_y)

    # Last 16 weeks weekly commit volume bars
    days_16w = days[-112:]
    weekly_totals = [sum(d["contributionCount"] for d in days_16w[w * 7 : (w + 1) * 7]) for w in range(16)]
    max_week = max(weekly_totals, default=1) or 1
    bar_slot = inner_w / 16
    bar_w = max(8.0, bar_slot - 6.0)
    weekly_bars = []
    for w_idx, total in enumerate(weekly_totals):
        bh = 3.0 if total == 0 else max(6.0, (total / max_week) * bars_h)
        bx = w_idx * bar_slot + (bar_slot - bar_w) / 2
        by = bars_h - bh
        fill = t["heat"][0] if total == 0 else (t["heat"][4] if total >= max_week * 0.6 else t["heat"][2])
        weekly_bars.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="2" fill="{fill}" />'
        )

    now_local = dt.datetime.now(dt.timezone(dt.timedelta(hours=TZ_OFFSET_HOURS))).strftime("%Y-%m-%d %H:%M")
    tz_label = f"UTC{TZ_OFFSET_HOURS:+d}" if TZ_OFFSET_HOURS != 9 else "KST"
    height = fixed_height

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
    <text x="14" y="23" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10" letter-spacing="1.1">LAST PUSH</text>
    <text x="14" y="54" fill="{t["text_primary"]}" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif" font-size="22" font-weight="600">{html.escape(format_relative_push(stats["last_push"], stats["today_date"]))}</text>
    <text x="{card_w - 14:.1f}" y="54" text-anchor="end" fill="{t["text_secondary"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="9.5">{html.escape(stats["last_push"])}</text>

    <g transform="translate({card_w + card_gap:.1f}, 0)">
      <rect x="0.5" y="0.5" width="{card_w - 1:.1f}" height="{card_h - 1}" rx="8" fill="{t["panel"]}" stroke="{t["border"]}" />
      <text x="14" y="23" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10" letter-spacing="1.1">30D ACTIVITY</text>
      <text x="14" y="54" fill="{t["text_primary"]}" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif" font-size="24" font-weight="600">{stats["last_30d_commits"]:,}</text>
      <text x="{card_w - 14:.1f}" y="54" text-anchor="end" fill="{t["text_secondary"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="9.5">events</text>
    </g>
  </g>

  <line x1="{pad_x}" y1="{div2_y}" x2="{width - pad_x}" y2="{div2_y}" stroke="{t["divider"]}" />

  <text x="{pad_x}" y="{bars_title_y}" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10.5" letter-spacing="1.4">
    WEEKLY CADENCE (16W)
  </text>

  <g transform="translate({pad_x}, {bars_y})">
    {"".join(weekly_bars)}
  </g>

  <text x="{width - pad_x}" y="{meta_y}" text-anchor="end" fill="{t["text_muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="9.5">
    synced · {now_local} {tz_label}
  </text>
</svg>
"""


def strip_sync_timestamp(svg_text: str) -> str:
    return re.sub(r"synced · [^\n<]+", "synced · TIMESTAMP", svg_text)


def write_svg_if_changed(path: Path, content: str) -> bool:
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if strip_sync_timestamp(old) == strip_sync_timestamp(content):
            return False
    path.write_text(content, encoding="utf-8")
    return True


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

    _, pills_h = compute_pill_layout(stats["languages"], 340)
    lang_min_height = 302 + pills_h + 24
    act_min_height = 476
    fixed_height = max(lang_min_height, act_min_height)

    for theme_name in ("dark", "light"):
        lang_path = OUT_DIR / f"lang-{theme_name}.svg"
        act_path = OUT_DIR / f"activity-{theme_name}.svg"
        lang_changed = write_svg_if_changed(lang_path, render_languages_svg(stats, theme_name, fixed_height))
        act_changed = write_svg_if_changed(act_path, render_activity_svg(stats, theme_name, fixed_height))
        print(
            f"Checked {lang_path.name} (changed={lang_changed}) & {act_path.name} (changed={act_changed}) "
            f"(height={fixed_height}, scope={stats['scope']}, repos={stats['repo_count']}, "
            f"private={stats['private_count']}, {len(stats['languages'])} languages, last_push={stats['last_push']})"
        )


if __name__ == "__main__":
    main()

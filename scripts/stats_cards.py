#!/usr/bin/env python3
"""Generate game-themed GitHub stat cards (SVG) for the profile README.

Uses only public data from the GitHub GraphQL API and the Python standard
library, so the workflow's built-in GITHUB_TOKEN is enough (no personal token).

Usage:
    GITHUB_TOKEN=... python scripts/stats_cards.py <username> <output-dir>

Writes <output-dir>/{player,languages,activity}{,-dark}.svg
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
import urllib.request
from collections import Counter
from html import escape
from pathlib import Path

API = "https://api.github.com/graphql"
ACCENT = "#37F4D3"
THEMES = {
    "": {"bg": "#ffffff", "border": "#d0d7de", "title": "#0b8f7e", "text": "#24292f",
         "muted": "#57606a", "track": "#eaeef2", "bar": "#13b49e"},
    "-dark": {"bg": "#0d1117", "border": "#1f6f66", "title": ACCENT, "text": "#e6edf3",
              "muted": "#8b949e", "track": "#21262d", "bar": ACCENT},
}
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"
W, H = 480, 200


def graphql(query: str, variables: dict, token: str) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"bearer {token}", "Content-Type": "application/json",
        "User-Agent": "profile-stats-cards"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]


def fetch(login: str, token: str) -> dict:
    q_user = """
    query($login: String!, $after: String) {
      user(login: $login) {
        createdAt
        followers { totalCount }
        contributionsCollection {
          contributionYears
          totalCommitContributions totalPullRequestContributions
          totalIssueContributions totalPullRequestReviewContributions
          contributionCalendar { totalContributions
            weeks { contributionDays { date contributionCount weekday } } }
        }
        repositories(first: 100, after: $after, ownerAffiliations: OWNER, isFork: false,
                     privacy: PUBLIC) {
          totalCount
          pageInfo { hasNextPage endCursor }
          nodes { stargazerCount forkCount
            languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
              edges { size node { name color } } } }
        }
      }
    }"""
    repos, after, user = [], None, None
    while True:
        user = graphql(q_user, {"login": login, "after": after}, token)["user"]
        repos += user["repositories"]["nodes"]
        page = user["repositories"]["pageInfo"]
        if not page["hasNextPage"]:
            break
        after = page["endCursor"]

    q_year = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) { contributionsCollection(from: $from, to: $to) {
        contributionCalendar { totalContributions } } }
    }"""
    all_time = 0
    for year in user["contributionsCollection"]["contributionYears"]:
        span = {"login": login, "from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"}
        all_time += graphql(q_year, span, token)["user"]["contributionsCollection"][
            "contributionCalendar"]["totalContributions"]
    return {"user": user, "repos": repos, "all_time": all_time}


def summarise(raw: dict) -> dict:
    user, repos = raw["user"], raw["repos"]
    cc = user["contributionsCollection"]
    days = [d for w in cc["contributionCalendar"]["weeks"] for d in w["contributionDays"]]
    days.sort(key=lambda d: d["date"])

    longest = run = 0
    for d in days:
        run = run + 1 if d["contributionCount"] else 0
        longest = max(longest, run)
    current = 0
    for i, d in enumerate(reversed(days)):
        if d["contributionCount"]:
            current += 1
        elif i > 0:  # today without contributions does not break the streak yet
            break

    weekday = Counter()
    for d in days:
        weekday[d["weekday"]] += d["contributionCount"]
    best_day = max(days, key=lambda d: d["contributionCount"]) if days else None

    langs: Counter = Counter()
    colors = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            langs[e["node"]["name"]] += e["size"]
            colors[e["node"]["name"]] = e["node"]["color"] or "#8b949e"
    total_bytes = sum(langs.values()) or 1

    xp = raw["all_time"]
    level = int(math.sqrt(xp / 10)) + 1          # level n starts at 10*(n-1)^2 XP
    floor_xp, next_xp = 10 * (level - 1) ** 2, 10 * level ** 2
    return {
        "level": level, "xp": xp, "progress": (xp - floor_xp) / max(1, next_xp - floor_xp),
        "next_xp": next_xp,
        "year_total": cc["contributionCalendar"]["totalContributions"],
        "commits": cc["totalCommitContributions"], "prs": cc["totalPullRequestContributions"],
        "issues": cc["totalIssueContributions"], "reviews": cc["totalPullRequestReviewContributions"],
        "repos": user["repositories"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in repos),
        "forks": sum(r["forkCount"] for r in repos),
        "followers": user["followers"]["totalCount"],
        "since": user["createdAt"][:4],
        "longest": longest, "current": current,
        "weekday": [weekday.get(i, 0) for i in range(7)],
        "best_day": best_day,
        "langs": [(n, s / total_bytes, colors[n]) for n, s in langs.most_common(6)],
    }


def card(theme: dict, title: str, body: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(title)}">
<style>
  text {{ font-family: {FONT}; }}
  .t {{ font-size: 15px; font-weight: 700; fill: {theme['title']}; letter-spacing: 1.5px; }}
  .l {{ font-size: 12.5px; fill: {theme['muted']}; }}
  .v {{ font-size: 13px; font-weight: 700; fill: {theme['text']}; }}
  .big {{ font-size: 26px; font-weight: 800; fill: {theme['title']}; }}
  .row {{ opacity: 0; animation: in .5s ease-out forwards; }}
  .grow {{ transform-box: fill-box; transform-origin: left; transform: scaleX(0); animation: grow 1.2s ease-out .3s forwards; }}
  .rise {{ transform-box: fill-box; transform-origin: bottom; transform: scaleY(0); animation: rise .9s ease-out forwards; }}
  @keyframes in {{ to {{ opacity: 1; }} }}
  @keyframes grow {{ to {{ transform: scaleX(1); }} }}
  @keyframes rise {{ to {{ transform: scaleY(1); }} }}
</style>
<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="10" fill="{theme['bg']}" stroke="{theme['border']}"/>
<text x="22" y="32" class="t">{escape(title)}</text>
{body}
</svg>
"""


def fmt(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 10000 else f"{n:,}"


def player_card(s: dict, theme: dict) -> str:
    stats = [("🔥", "Contributions*", s["year_total"]), ("💾", "Commits*", s["commits"]),
             ("🔀", "Pull requests*", s["prs"]), ("📦", "Public repos", s["repos"]),
             ("⭐", "Stars earned", s["stars"]), ("👥", "Followers", s["followers"])]
    rows = []
    for i, (icon, label, value) in enumerate(stats):
        col, line = divmod(i, 3)
        x, y = 22 + col * 226, 98 + line * 26
        rows.append(f'<g class="row" style="animation-delay:{0.15 * i:.2f}s">'
                    f'<text x="{x}" y="{y}" class="l">{icon} {escape(label)}</text>'
                    f'<text x="{x + 204}" y="{y}" class="v" text-anchor="end">{fmt(value)}</text></g>')
    bar_w = 200
    body = f"""
<text x="{W - 22}" y="32" class="l" text-anchor="end">Player since {s['since']}</text>
<text x="22" y="66" class="big">LVL {s['level']}</text>
<text x="{W - 22}" y="48" class="l" text-anchor="end">XP {fmt(s['xp'])} / {fmt(s['next_xp'])}</text>
<rect x="{W - 22 - bar_w}" y="56" width="{bar_w}" height="10" rx="5" fill="{theme['track']}"/>
<rect x="{W - 22 - bar_w}" y="56" width="{max(6, bar_w * s['progress']):.1f}" height="10" rx="5" fill="{theme['bar']}" class="grow"/>
{''.join(rows)}
<text x="22" y="{H - 14}" class="l">* last 12 months · XP = all-time contributions · 🍴 {s['forks']} forks</text>"""
    return card(theme, "PLAYER STATS", body)


def languages_card(s: dict, theme: dict) -> str:
    rows, x0, bar_w = [], 22, W - 44 - 150
    for i, (name, share, color) in enumerate(s["langs"]):
        y = 58 + i * 22
        rows.append(f'<g class="row" style="animation-delay:{0.12 * i:.2f}s">'
                    f'<circle cx="{x0 + 5}" cy="{y - 4}" r="5" fill="{color}"/>'
                    f'<text x="{x0 + 16}" y="{y}" class="v">{escape(name)}</text>'
                    f'<rect x="{x0 + 120}" y="{y - 9}" width="{bar_w}" height="8" rx="4" fill="{theme["track"]}"/>'
                    f'<rect x="{x0 + 120}" y="{y - 9}" width="{max(4, bar_w * share):.1f}" height="8" rx="4" '
                    f'fill="{color}" class="grow"/>'
                    f'<text x="{W - 22}" y="{y}" class="l" text-anchor="end">{share * 100:.1f}%</text></g>')
    if not rows:
        rows.append(f'<text x="22" y="70" class="l">No public language data yet</text>')
    return card(theme, "INVENTORY · TOP LANGUAGES", "".join(rows))


def activity_card(s: dict, theme: dict) -> str:
    names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    peak = max(s["weekday"]) or 1
    bars, base, bw, gap, x0 = [], 158, 26, 12, 22
    for i, v in enumerate(s["weekday"]):
        h = max(2, 90 * v / peak)
        x = x0 + i * (bw + gap)
        fill = theme["bar"] if v == peak and v else theme["muted"]
        bars.append(f'<rect x="{x}" y="{base - h:.1f}" width="{bw}" height="{h:.1f}" rx="4" fill="{fill}" '
                    f'class="rise" style="animation-delay:{0.08 * i:.2f}s"/>'
                    f'<text x="{x + bw / 2}" y="{base + 16}" class="l" text-anchor="middle">{names[i]}</text>')
    best = s["best_day"]
    best_txt = (f'{best["contributionCount"]} on {dt.date.fromisoformat(best["date"]):%d %b %Y}'
                if best and best["contributionCount"] else "-")
    side_x = x0 + 7 * (bw + gap) + 18
    side = f"""
<g class="row" style="animation-delay:.2s"><text x="{side_x}" y="70" class="l">🔥 Current streak</text>
<text x="{side_x}" y="92" class="big">{s['current']}d</text></g>
<g class="row" style="animation-delay:.35s"><text x="{side_x}" y="118" class="l">🏆 Longest (12 mo)</text>
<text x="{side_x}" y="140" class="v">{s['longest']} days</text></g>
<g class="row" style="animation-delay:.5s"><text x="{side_x}" y="164" class="l">⚡ Best day</text>
<text x="{side_x}" y="182" class="v">{escape(best_txt)}</text></g>"""
    return card(theme, "COMBO METER · WEEKLY ACTIVITY", "".join(bars) + side)


def main(argv: list) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is not set")
        return 2
    login, out = argv[1], Path(argv[2])
    out.mkdir(parents=True, exist_ok=True)
    stats = summarise(fetch(login, token))
    for suffix, theme in THEMES.items():
        for name, fn in (("player", player_card), ("languages", languages_card),
                         ("activity", activity_card)):
            (out / f"{name}{suffix}.svg").write_text(fn(stats, theme), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k not in ("langs", "best_day")}))
    print("languages:", [(n, round(p * 100, 1)) for n, p, _ in stats["langs"]])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""
Generates Abdulai Yorli Iddrisu's animated neofetch-style GitHub profile SVGs.

Inspired by Andrew6rant's profile. It:
  1. Converts `photo.jpg` into a colored ASCII-art portrait.
  2. Fetches live GitHub stats (repos, stars, commits, followers, account age)
     via the GitHub GraphQL API.
  3. Renders `dark_mode.svg` and `light_mode.svg`.

Locally:   python today.py            (uses placeholder stats if no token)
In CI:     set env ACCESS_TOKEN + USER_NAME, then run.

Env vars:
  ACCESS_TOKEN  GitHub Personal Access Token (classic) with `read:user`,
                `repo` scopes. In GitHub Actions this is a repo secret.
  USER_NAME     GitHub login (default: yorliabdulai)
"""

from __future__ import annotations
import datetime as _dt
import html
import json
import os
import glob
import urllib.request
import urllib.error
from PIL import Image, ImageOps, ImageEnhance

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_photo():
    """Locate photo.* regardless of case/extension (Linux CI is case-sensitive)."""
    for pat in ("photo.jpg", "photo.jpeg", "photo.png", "photo.JPG",
                "photo.JPEG", "photo.PNG"):
        p = os.path.join(HERE, pat)
        if os.path.exists(p):
            return p
    hits = [f for f in glob.glob(os.path.join(HERE, "photo.*"))
            if f.lower().rsplit(".", 1)[-1] in ("jpg", "jpeg", "png")]
    return hits[0] if hits else os.path.join(HERE, "photo.jpg")


PHOTO = _find_photo()

USER_NAME = os.environ.get("USER_NAME", "yorliabdulai")
# Prefer a user PAT (full contribution data); fall back to the Action's
# built-in GITHUB_TOKEN so stats can work even without creating a PAT.
ACCESS_TOKEN = (os.environ.get("ACCESS_TOKEN")
                or os.environ.get("GH_TOKEN")
                or os.environ.get("GITHUB_TOKEN") or "")

# ---- personal info (edit here) ----------------------------------------------
LINKEDIN = os.environ.get("LINKEDIN", "linkedin.com/in/abdulai-yorli-iddrisu")
MEDIUM = os.environ.get("MEDIUM", "medium.com/@iddrisuabdulaiyorli1")

# --- Portrait config ----------------------------------------------------------
# The portrait is rendered as deterministic colored pixels (SVG <rect>s), NOT
# font-based ASCII. Text ASCII gets distorted by whatever monospace font the
# viewer's browser happens to use; rectangles render pixel-identically
# everywhere, so the face is always faithful.
PORTRAIT_COLS = 74           # horizontal resolution of the portrait
CELL = 5.6                   # px per pixel-cell
BG_DROP = 0.88               # normalized-luminance above this -> transparent bg
# Info-panel text-cell metrics.
CHAR_W = 8.4
CHAR_H = 16.0


# =============================================================================
# GitHub GraphQL stats
# =============================================================================
def _gql(query: str, variables: dict) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": USER_NAME,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"HTTP {e.code} from GitHub API: {body}") from None
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def _placeholder_stats() -> dict:
    return dict(
        repos="—", contributed="—", stars="—", commits="—",
        followers="—", following="—", uptime="live in CI",
        year=_dt.date.today().year, live=False,
    )


def fetch_stats() -> dict:
    """Return a dict of live stats, or placeholder values on any problem.

    Prints clear diagnostics to the Action log so failures are debuggable.
    """
    src = ("ACCESS_TOKEN" if os.environ.get("ACCESS_TOKEN")
           else "GH_TOKEN" if os.environ.get("GH_TOKEN")
           else "GITHUB_TOKEN" if os.environ.get("GITHUB_TOKEN") else None)
    print(f"[stats] user={USER_NAME}  token_source={src}  "
          f"token_present={bool(ACCESS_TOKEN)}")
    if not ACCESS_TOKEN:
        print("[stats] No token in environment -> placeholder '—'. "
              "In the workflow, ensure a token is passed as ACCESS_TOKEN "
              "(secret) or GITHUB_TOKEN.")
        return _placeholder_stats()

    try:
        return _fetch_stats_live()
    except Exception as e:  # noqa: BLE001 - log & degrade, never break the run
        print(f"[stats] API ERROR -> placeholder. Reason: {e}")
        return _placeholder_stats()


def _fetch_stats_live() -> dict:
    # --- Query 1: core public stats (works with any token that reads the user)
    q_core = """
    query($login: String!, $after: String) {
      user(login: $login) {
        createdAt
        followers { totalCount }
        following { totalCount }
        repositories(ownerAffiliations: OWNER, first: 100, after: $after) {
          totalCount
          pageInfo { hasNextPage endCursor }
          nodes { stargazerCount }
        }
      }
    }
    """
    created_at = None
    followers = following = repos_total = stars = 0
    after = None
    while True:
        data = _gql(q_core, {"login": USER_NAME, "after": after})["user"]
        created_at = created_at or data["createdAt"]
        followers = data["followers"]["totalCount"]
        following = data["following"]["totalCount"]
        repo = data["repositories"]
        repos_total = repo["totalCount"]
        stars += sum(n["stargazerCount"] for n in repo["nodes"])
        if repo["pageInfo"]["hasNextPage"]:
            after = repo["pageInfo"]["endCursor"]
        else:
            break

    # --- Query 2: commits (needs read:user scope). Isolated so its failure
    # doesn't wipe out the other stats.
    commits_str = "—"
    try:
        q_c = ("query($login: String!){ user(login: $login){ "
               "contributionsCollection{ totalCommitContributions } } }")
        c = (_gql(q_c, {"login": USER_NAME})["user"]
             ["contributionsCollection"]["totalCommitContributions"])
        commits_str = f"{c:,}"
    except Exception as e:  # noqa: BLE001
        print(f"[stats] commits unavailable (token scope?): {e}")

    # account "uptime"
    start = _dt.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = _dt.datetime.now(_dt.timezone.utc)
    days = (now - start).days
    y, rem = divmod(days, 365)
    m, d = divmod(rem, 30)
    uptime = f"{y}y {m}m {d}d"

    print(f"[stats] OK repos={repos_total} stars={stars} "
          f"commits={commits_str} followers={followers} following={following}")
    return dict(
        repos=f"{repos_total}", contributed="—",
        stars=f"{stars:,}", commits=commits_str,
        followers=f"{followers}", following=f"{following}",
        uptime=uptime, year=now.year, live=True,
    )


# =============================================================================
# ASCII portrait
# =============================================================================
def load_and_crop(path: str) -> Image.Image:
    """Tight head-and-shoulders crop, then enhance so facial features pop."""
    img = Image.open(path).convert("RGB")
    img = ImageOps.exif_transpose(img)          # respect camera orientation
    w, h = img.size
    # Crop to the top ~60% (head + shoulders) and trim a little off the sides
    # so the face fills the frame -> maximum detail per character.
    left, right = int(w * 0.06), int(w * 0.94)
    img = img.crop((left, 0, right, int(h * 0.60)))
    # Feature enhancement: normalize tonal range, boost contrast, sharpen edges.
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Contrast(img).enhance(1.25)
    img = ImageEnhance.Sharpness(img).enhance(1.6)
    return img


def to_pixels(img: Image.Image):
    """Downsample to a grid of hex colors; None marks dropped background."""
    cols = PORTRAIT_COLS
    w, h = img.size
    rows = max(1, round(cols * h / w))          # square cells -> no distortion
    small = img.resize((cols, rows), Image.LANCZOS)

    # Contrast-stretch luminance so the bright studio background is easy to drop.
    lums = []
    for y in range(rows):
        for x in range(cols):
            r, g, b = small.getpixel((x, y))
            lums.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
    lo, hi = min(lums), max(lums)
    span = max(1.0, hi - lo)

    def boost(c):
        return max(0, min(255, int(c * 1.12) + 8))

    grid = []
    for y in range(rows):
        row = []
        for x in range(cols):
            r, g, b = small.getpixel((x, y))
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            norm = (lum - lo) / span
            if norm > BG_DROP:                  # bright studio bg -> transparent
                row.append(None)
            else:
                row.append(f"#{boost(r):02x}{boost(g):02x}{boost(b):02x}")
        grid.append(row)
    return grid


def placeholder_pixels():
    cols = PORTRAIT_COLS
    rows = int(cols * 0.85)
    grid = []
    for y in range(rows):
        row = []
        for x in range(cols):
            nx = (x - cols / 2) / (cols / 2)
            ny = (y - rows / 2) / (rows / 2)
            row.append("#3b4b66" if nx * nx + ny * ny < 0.8 else None)
        grid.append(row)
    return grid


def pixels_to_svg(grid, x0, y0):
    """Render the color grid as SVG rects (deterministic in every browser)."""
    out = []
    c = CELL
    ov = 0.5                                     # overlap kills hairline seams
    for y, row in enumerate(grid):
        yy = y0 + y * c
        for x, col in enumerate(row):
            if col is None:
                continue
            out.append(
                f'<rect x="{x0 + x * c:.2f}" y="{yy:.2f}" '
                f'width="{c + ov:.2f}" height="{c + ov:.2f}" fill="{col}"/>'
            )
    return "".join(out), len(grid)


# =============================================================================
# neofetch info panel
# =============================================================================
def info_lines(stats, accent, dim, text, accent2):
    A, D, T, G = accent, dim, text, accent2
    return [
        [("yorli", A), ("@", T), ("github", A)],
        [("-" * 26, D)],
        [("OS", A), (": ", T), ("Ubuntu Linux / Windows 11", T)],
        [("Host", A), (": ", T), ("KPMG Ghana · Accra", T)],
        [("Role", A), (": ", T), ("Software / Cloud & Infra Engineer", T)],
        [("Uptime", A), (": ", T), (stats["uptime"], T)],
        [("Kernel", A), (": ", T), ("AWS SAA-C03 · KCNA", T)],
        [("Shell", A), (": ", T), ("bash · pwsh · zsh", T)],
        [("Editor", A), (": ", T), ("VS Code · Vim", T)],
        [("", T)],
        [("Languages.Code", A), (": ", T),
         ("TypeScript · Python · Java · Solidity", T)],
        [("Languages.Real", A), (": ", T), ("English · Dagbani · Twi", T)],
        [("Cloud", A), (": ", T), ("AWS (EC2, VPC, S3, RDS, IAM, Route53)", T)],
        [("Infra", A), (": ", T), ("Terraform · Docker · Kubernetes", T)],
        [("Stack", A), (": ", T), ("React · Next.js · Node · Supabase", T)],
        [("Web3", A), (": ", T), ("Solidity · IPFS · Wagmi · NFTs", T)],
        [("", T)],
        [("Repos", A), (": ", T), (stats["repos"], G),
         ("  Stars", A), (": ", T), (stats["stars"], G),
         ("  Followers", A), (": ", T), (stats["followers"], G)],
        [(f"Commits ({stats['year']})", A), (": ", T), (stats["commits"], G),
         ("  Following", A), (": ", T), (stats["following"], G)],
        [("", T)],
        [("LinkedIn", A), (": ", T), (LINKEDIN.replace("linkedin.com/", ""), T)],
        [("Medium", A), (": ", T), (MEDIUM.replace("medium.com/", ""), T)],
    ]


def info_to_svg(lines, x0, y0):
    out = []
    for i, segs in enumerate(lines):
        y = y0 + i * CHAR_H
        spans = "".join(
            f'<tspan fill="{c}">{html.escape(s)}</tspan>' for s, c in segs
        )
        out.append(f'<text x="{x0:.1f}" y="{y:.1f}" class="info">{spans}</text>')
    return "\n".join(out), len(lines)


THEMES = {
    "dark": dict(
        bg="#0d1117", border="#30363d", titlebar="#161b22", title="#c9d1d9",
        accent="#58a6ff", accent2="#3fb950", dim="#484f58", text="#c9d1d9",
        prompt="#3fb950", cursor="#58a6ff",
        red="#ff5f56", yellow="#ffbd2e", green="#27c93f"),
    "light": dict(
        bg="#ffffff", border="#d0d7de", titlebar="#f6f8fa", title="#24292f",
        accent="#0969da", accent2="#1a7f37", dim="#8c959f", text="#24292f",
        prompt="#1a7f37", cursor="#0969da",
        red="#ff5f56", yellow="#ffbd2e", green="#27c93f"),
}


def build_svg(theme_name, grid, stats):
    t = THEMES[theme_name]
    pad, title_h = 24, 40
    top = title_h + 28

    port_x = pad + 6
    port_y = top + 14
    port_svg, n_rows = pixels_to_svg(grid, port_x, port_y)
    port_w = PORTRAIT_COLS * CELL
    port_h = n_rows * CELL

    lines = info_lines(stats, t["accent"], t["dim"], t["text"], t["accent2"])
    n_info = len(lines)
    info_h = n_info * CHAR_H
    info_x = port_x + port_w + 46
    info_y = port_y + max(0.0, (port_h - info_h) / 2)   # center vs portrait
    info_svg, _ = info_to_svg(lines, info_x, info_y)

    max_chars = max(sum(len(s) for s, _ in segs) for segs in lines)
    info_w = max_chars * CHAR_W

    header_y = top - 6
    body_bottom = port_y + max(port_h, info_h)
    prompt_y = body_bottom + 26
    height = int(prompt_y + 40)
    width = max(int(info_x + info_w + pad), 900)

    typed = ("Abdulai Yorli Iddrisu — building reliable cloud "
             "& web systems from Accra.")
    typed_w = len(typed) * CHAR_W

    styles = f"""
    <style>
      .mono {{ font-family:'JetBrains Mono','Fira Code','Cascadia Code','SF Mono',Consolas,monospace; }}
      .ascii{{ font-size:9px; font-family:'JetBrains Mono','Fira Code',Consolas,monospace; }}
      .info {{ font-size:13.5px; }}
      .title{{ fill:{t['title']}; font-size:13px; }}
      .type {{ fill:{t['accent']}; font-size:15px; }}
      .prompt{{ font-size:14px; }}
      .cursor{{ fill:{t['cursor']}; }}
      text {{ dominant-baseline:hanging; }}
    </style>"""

    header = f"""
    <g class="mono">
      <clipPath id="tc-{theme_name}">
        <rect x="{pad}" y="{header_y-4}" width="0" height="24">
          <animate attributeName="width" from="0" to="{typed_w+10:.0f}"
                   dur="2.6s" begin="0.4s" fill="freeze"
                   calcMode="spline" keyTimes="0;1" keySplines="0.2 0 0.1 1"/>
        </rect>
      </clipPath>
      <text x="{pad}" y="{header_y}" class="type"
            clip-path="url(#tc-{theme_name})">{html.escape(typed)}</text>
      <rect x="{pad}" y="{header_y-2}" width="8" height="18" class="cursor">
        <animate attributeName="x" from="{pad}" to="{pad+typed_w:.0f}"
                 dur="2.6s" begin="0.4s" fill="freeze"
                 calcMode="spline" keyTimes="0;1" keySplines="0.2 0 0.1 1"/>
        <animate attributeName="opacity" values="1;1;0;1" dur="1s"
                 begin="3s" repeatCount="indefinite"/>
      </rect>
    </g>"""

    prompt = f"""
    <g class="mono prompt">
      <text x="{pad}" y="{prompt_y}"><tspan fill="{t['prompt']}">yorli@github</tspan><tspan fill="{t['text']}">:</tspan><tspan fill="{t['accent']}">~</tspan><tspan fill="{t['text']}">$ ./contact --lets-build</tspan></text>
      <rect x="{pad + 39*CHAR_W:.0f}" y="{prompt_y-2}" width="8" height="16" class="cursor">
        <animate attributeName="opacity" values="1;1;0;0" dur="1.1s"
                 begin="3.6s" repeatCount="indefinite"/>
      </rect>
    </g>"""

    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}"
     xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="Abdulai Yorli Iddrisu - neofetch terminal profile">
  {styles}
  <rect x="1" y="1" width="{width-2}" height="{height-2}" rx="12"
        fill="{t['bg']}" stroke="{t['border']}" stroke-width="1.5"/>
  <path d="M1 13 a12 12 0 0 1 12 -12 h{width-26} a12 12 0 0 1 12 12 v27 h-{width-2} z"
        fill="{t['titlebar']}"/>
  <circle cx="22" cy="20" r="6" fill="{t['red']}"/>
  <circle cx="42" cy="20" r="6" fill="{t['yellow']}"/>
  <circle cx="62" cy="20" r="6" fill="{t['green']}"/>
  <text x="{width/2:.0f}" y="14" text-anchor="middle" class="mono title"
        style="dominant-baseline:hanging">yorli@github: ~/profile</text>
  {header}
  <g opacity="0">
    <animate attributeName="opacity" from="0" to="1" dur="0.8s"
             begin="2.8s" fill="freeze"/>
    {port_svg}
  </g>
  <g class="mono" opacity="0">
    <animate attributeName="opacity" from="0" to="1" dur="0.8s"
             begin="2.8s" fill="freeze"/>
    {info_svg}
  </g>
  {prompt}
</svg>
"""


def main():
    if os.path.exists(PHOTO):
        grid = to_pixels(load_and_crop(PHOTO))
        print(f"Pixel portrait: {PORTRAIT_COLS}x{len(grid)} "
              f"from {os.path.basename(PHOTO)}")
    else:
        grid = placeholder_pixels()
        print("photo not found - placeholder portrait.")

    stats = fetch_stats()
    print("Stats:", "live" if stats["live"] else "placeholder", stats)

    for name in ("dark", "light"):
        svg = build_svg(name, grid, stats)
        with open(os.path.join(HERE, f"{name}_mode.svg"), "w",
                  encoding="utf-8") as f:
            f.write(svg)
        print(f"wrote {name}_mode.svg")


if __name__ == "__main__":
    main()

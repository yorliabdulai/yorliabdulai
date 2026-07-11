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
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "")

# ---- personal info (edit here) ----------------------------------------------
LINKEDIN = os.environ.get("LINKEDIN", "linkedin.com/in/abdulai-yorli-iddrisu")
MEDIUM = os.environ.get("MEDIUM", "medium.com/@iddrisuabdulaiyorli1")

# --- ASCII rendering config ---------------------------------------------------
# High resolution so the portrait is clearly recognizable as a specific face.
ASCII_COLS = 80
RAMP = " .:-=+*#%@"          # index 0 (dark) .. 9 (light)
# ASCII cell metrics (small font -> the portrait reads photographically).
AW = 5.5                     # ascii char advance (px) at 9px mono
AH = 10.5                    # ascii line height (px)
# Info-panel cell metrics (larger, readable text).
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
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.loads(r.read().decode())
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def fetch_stats() -> dict:
    """Return a dict of live stats, or placeholder values when no token."""
    if not ACCESS_TOKEN:
        return dict(
            repos="—", contributed="—", stars="—", commits="—",
            followers="—", following="—", uptime="live in CI",
            year=_dt.date.today().year, live=False,
        )

    q = """
    query($login: String!, $after: String) {
      user(login: $login) {
        createdAt
        followers { totalCount }
        following { totalCount }
        contributionsCollection { totalCommitContributions }
        repositories(ownerAffiliations: OWNER, first: 100, after: $after) {
          totalCount
          pageInfo { hasNextPage endCursor }
          nodes { stargazerCount }
        }
      }
    }
    """
    created_at = None
    followers = following = commits = repos_total = stars = 0
    after = None
    while True:
        data = _gql(q, {"login": USER_NAME, "after": after})["user"]
        created_at = created_at or data["createdAt"]
        followers = data["followers"]["totalCount"]
        following = data["following"]["totalCount"]
        commits = data["contributionsCollection"]["totalCommitContributions"]
        repo = data["repositories"]
        repos_total = repo["totalCount"]
        stars += sum(n["stargazerCount"] for n in repo["nodes"])
        if repo["pageInfo"]["hasNextPage"]:
            after = repo["pageInfo"]["endCursor"]
        else:
            break

    # account "uptime"
    start = _dt.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = _dt.datetime.now(_dt.timezone.utc)
    days = (now - start).days
    y, rem = divmod(days, 365)
    m, d = divmod(rem, 30)
    uptime = f"{y}y {m}m {d}d"

    return dict(
        repos=f"{repos_total}", contributed="—",
        stars=f"{stars:,}", commits=f"{commits:,}",
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


def to_ascii(img: Image.Image):
    cols = ASCII_COLS
    w, h = img.size
    cell_aspect = AH / AW
    rows = max(1, int(cols * (h / w) / cell_aspect))
    small = img.resize((cols, rows), Image.LANCZOS)

    # First pass: gather luminance so we can contrast-stretch the tonal range.
    lums = []
    for y in range(rows):
        for x in range(cols):
            r, g, b = small.getpixel((x, y))
            lums.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
    lo, hi = min(lums), max(lums)
    span = max(1.0, hi - lo)

    def boost(c):
        return max(0, min(255, int(c * 1.2) + 30))

    grid = []
    for y in range(rows):
        line = []
        for x in range(cols):
            r, g, b = small.getpixel((x, y))
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            norm = (lum - lo) / span                 # 0 = darkest .. 1 = lightest
            # Drop the light studio background so the portrait floats cleanly.
            if norm > 0.85:
                line.append((" ", "#000000"))
                continue
            # Invert: DARK subject/suit -> dense glyphs, LIGHT bg -> blank.
            idx = int((1.0 - norm) * (len(RAMP) - 1))
            ch = RAMP[idx]
            color = f"#{boost(r):02x}{boost(g):02x}{boost(b):02x}"
            line.append((ch, color))
        grid.append(line)
    return grid


def placeholder_grid():
    rows = int(ASCII_COLS * 0.45)
    grid = []
    for y in range(rows):
        line = []
        for x in range(ASCII_COLS):
            nx = (x - ASCII_COLS / 2) / (ASCII_COLS / 2)
            ny = (y - rows / 2) / (rows / 2)
            ch = "#" if nx * nx + ny * ny < 0.85 else " "
            line.append((ch, "#58a6ff"))
        grid.append(line)
    return grid


def ascii_to_svg(grid, x0, y0):
    out = []
    row_w = ASCII_COLS * AW
    for i, row in enumerate(grid):
        y = y0 + i * AH
        spans = "".join(
            f'<tspan fill="{c}">{html.escape(ch)}</tspan>' for ch, c in row
        )
        # textLength locks each row to an exact width so alignment is identical
        # regardless of which monospace font the viewer's browser substitutes.
        out.append(
            f'<text x="{x0:.1f}" y="{y:.1f}" class="ascii" '
            f'textLength="{row_w:.1f}" lengthAdjust="spacingAndGlyphs">'
            f'{spans}</text>'
        )
    return "\n".join(out), len(grid)


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

    ascii_x = pad + 6
    ascii_y = top + 14
    ascii_svg, n_rows = ascii_to_svg(grid, ascii_x, ascii_y)
    ascii_w = ASCII_COLS * AW
    ascii_h = n_rows * AH

    lines = info_lines(stats, t["accent"], t["dim"], t["text"], t["accent2"])
    n_info = len(lines)
    info_h = n_info * CHAR_H
    info_x = ascii_x + ascii_w + 46
    info_y = ascii_y + max(0.0, (ascii_h - info_h) / 2)   # center vs portrait
    info_svg, _ = info_to_svg(lines, info_x, info_y)

    max_chars = max(sum(len(s) for s, _ in segs) for segs in lines)
    info_w = max_chars * CHAR_W

    header_y = top - 6
    body_bottom = ascii_y + max(ascii_h, info_h)
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
  <g class="mono" opacity="0">
    <animate attributeName="opacity" from="0" to="1" dur="0.8s"
             begin="2.8s" fill="freeze"/>
    {ascii_svg}
    {info_svg}
  </g>
  {prompt}
</svg>
"""


def main():
    if os.path.exists(PHOTO):
        grid = to_ascii(load_and_crop(PHOTO))
        print(f"ASCII portrait: {ASCII_COLS}x{len(grid)} from photo.jpg")
    else:
        grid = placeholder_grid()
        print("photo.jpg not found - placeholder portrait. Add photo.jpg.")

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

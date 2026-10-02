"""
Builds the profile README cards as SVGs in the Stratum theme used by
cynickalsoftware.com (IBM Plex, slate-blue palette, hairline readout panels).

    python tools/build.py

Writes assets/dark/*.svg and assets/light/*.svg. README.md picks between them
with <picture> + prefers-color-scheme. Edit CONTENT below and re-run.

Fonts are pulled from Google Fonts: static TTFs to measure text for layout,
and a woff2 subset of exactly the characters used, embedded in each SVG so
the cards render in IBM Plex wherever GitHub shows them. Needs fontTools.
"""

import base64
import html
import pathlib
import re
import urllib.parse
import urllib.request

from fontTools.ttLib import TTFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "tools" / ".cache"
LOGO = ROOT / "tools" / "logo-96.png"

W = 840          # card width; GitHub's profile README column is ~830px
PAD = 24         # inner padding of section frames

# ------------------------------------------------------------------ content

CONTENT = {
    "badge": "Low-latency · Systems · Data",
    "headline": ["Hi, I’m Nick.", "Low-latency systems,", "markets & data."],
    "sub": "aka CyNickal · C / C++ · cynickalsoftware.com",
    "lede": ("I go by the handle CyNickal online. "
             "I spend most of my time on low-latency system design, financial "
             "systems and dataset analysis, and I build hardware DMA tooling "
             "under CyNickal Software."),
    "readout": [
        ("Handle", "CyNickal", False),
        ("GitHub", "CyN1ckal", False),
        ("Languages", "C · C++ · Python", False),
        ("Discord", "cynickal", False),
        ("Email", "cynickal@cynickal.com", True),
        ("Studio", "CyNickal Software", False),
    ],
    "focus": [
        ("Latency", "Low-latency system design",
         "Hot paths, memory access and timing — measured empirically "
         "before anything gets optimised.", "dma_timing"),
        ("Finance", "Financial systems design",
         "Research tooling, trade ledgers and backtesting engines built "
         "for speed and correctness.", "CyNickal-Software-Terminal"),
        ("Data", "Dataset analysis",
         "Pulling structure out of large datasets — cleaning, modelling "
         "and surfacing what matters.", "Python · MySQL"),
    ],
    "stack": [
        ("C++", "Primary", True),
        ("C", "Systems", False),
        ("Python", "Analysis", False),
        ("MySQL", "Database", False),
    ],
    "contact_lede": ("Discord is the fastest way to reach me. For anything "
                     "business-related, email works too — or have a look "
                     "around CyNickal Software."),
}

# ------------------------------------------------------------------ palette
# Mirrors the generated token block in cynickalsoftware.com's stratum CSS.

THEMES = {
    "dark": dict(
        bg0="#0d1116", bg1="#12171e", bg2="#171d26", bg3="#1e2530",
        line="#262e3a", line2="#313848",
        tx="#ccd3dd", txd="#959daa", txf="#798598",
        acc="#6f97c9", ok="#5f8a63", on_acc="#0d1116",
        glow=0.09, shadow=("#000000", 0.55),
    ),
    "light": dict(
        bg0="#e7ebf1", bg1="#f3f5f9", bg2="#ffffff", bg3="#e4e9f0",
        line="#dde3ea", line2="#cbd4de",
        tx="#2a323d", txd="#4f5863", txf="#596777",
        acc="#3d6b9e", ok="#4f7a54", on_acc="#ffffff",
        glow=0.07, shadow=("#1e3250", 0.22),
    ),
}


def mix(a, b, t):
    """Blend hex colour a toward b by t (0..1), like color-mix in srgb."""
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(pa, pb))


# ------------------------------------------------------------------ fonts

UA_WOFF2 = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
FAMILY = {"sans": "IBM Plex Sans", "mono": "IBM Plex Mono"}
STACK = {
    "sans": "'IBM Plex Sans',system-ui,-apple-system,'Segoe UI',sans-serif",
    "mono": "'IBM Plex Mono',ui-monospace,'Cascadia Mono',Consolas,monospace",
}
CSS_URL = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600"
           "&family=IBM+Plex+Mono:wght@400;500;600")


def fetch(url, ua=None):
    req = urllib.request.Request(url, headers={"User-Agent": ua} if ua else {})
    with urllib.request.urlopen(req) as r:
        return r.read()


def faces(css):
    for block in re.findall(r"@font-face\s*{(.*?)}", css, re.S):
        fam = re.search(r"font-family:\s*'([^']+)'", block).group(1)
        wt = int(re.search(r"font-weight:\s*(\d+)", block).group(1))
        url = re.search(r"url\(([^)]+)\)", block).group(1)
        yield fam, wt, url


class Metrics:
    """Advance widths from the static TTFs, for laying out text."""

    def __init__(self):
        CACHE.mkdir(parents=True, exist_ok=True)
        self.fonts = {}
        css = fetch(CSS_URL).decode()   # no UA -> Google serves static TTFs
        for fam, wt, url in faces(css):
            key = ("sans" if "Sans" in fam else "mono", wt)
            path = CACHE / f"{key[0]}-{wt}.ttf"
            if not path.exists():
                path.write_bytes(fetch(url))
            f = TTFont(path)
            self.fonts[key] = (f.getBestCmap(), f["hmtx"].metrics, f["head"].unitsPerEm)

    def width(self, s, fam, wt, size, ls=0.0):
        cmap, hmtx, upm = self.fonts[(fam, wt)]
        adv = sum(hmtx[cmap.get(ord(c), ".notdef")][0] for c in s)
        return adv / upm * size + ls * len(s)


M = Metrics()


def wrap(s, width, fam, wt, size):
    lines, cur = [], ""
    for word in s.split(" "):
        trial = f"{cur} {word}".strip()
        if cur and M.width(trial, fam, wt, size) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + [cur]


# ------------------------------------------------------------------ svg

class Svg:
    """Collects one card's markup plus the characters / faces it uses."""

    used_chars = set()

    def __init__(self, t, w, h):
        self.t, self.w, self.h = t, w, h
        self.parts, self.defs = [], []
        self.faces = set()

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, fam="sans", wt=400, size=14, fill="tx", ls=0.0,
             anchor="start", upper=False):
        s = s.upper() if upper else s
        Svg.used_chars.update(s)
        self.faces.add((fam, wt))
        attrs = f'x="{x:.2f}" y="{y:.2f}" class="{fam}" font-size="{size}" font-weight="{wt}" fill="{self.t.get(fill, fill)}"'
        if ls:
            attrs += f' letter-spacing="{ls:.2f}"'
        if anchor != "start":
            attrs += f' text-anchor="{anchor}"'
        self.add(f"<text {attrs}>{html.escape(s, quote=False)}</text>")

    def frame(self):
        """The bg0 panel every section sits on, so cards read on light GitHub too."""
        t = self.t
        self.add(f'<rect x="0.5" y="0.5" width="{self.w - 1}" height="{self.h - 1}" rx="8" '
                 f'fill="{t["bg0"]}" stroke="{t["line"]}"/>')

    def dot(self, cx, cy, color):
        self.add(f'<circle cx="{cx}" cy="{cy}" r="6" fill="{color}" opacity=".22">'
                 f'<animate attributeName="opacity" values=".22;.05;.22" dur="2.4s" repeatCount="indefinite"/></circle>'
                 f'<circle cx="{cx}" cy="{cy}" r="3" fill="{color}">'
                 f'<animate attributeName="opacity" values="1;.35;1" dur="2.4s" repeatCount="indefinite"/></circle>')

    def section_head(self, num, title):
        self.text(PAD, PAD + 12, f"{num} / {title[0]}", "mono", 500, 10.5, "txf", 1.68, upper=True)
        self.text(PAD, PAD + 42, title[1], "sans", 600, 20, "tx", -0.3)

    def render(self, fontcss):
        css = "".join(fontcss[f] for f in sorted(self.faces) if f in fontcss)
        # The sans subset is one variable file; dedupe the identical rules.
        css = "".join(dict.fromkeys(css.split("\n")))
        css += "".join(f".{k}{{font-family:{v}}}" for k, v in STACK.items())
        return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" fill="none">'
                f"<style>{css}</style><defs>{''.join(self.defs)}</defs>{''.join(self.parts)}</svg>")


# ------------------------------------------------------------------ cards

def hero(t):
    c = CONTENT
    lede = wrap(c["lede"], 420, "sans", 400, 14.5)
    rows = c["readout"]
    rh = 36 + 6 + 33 * len(rows) + 6 + 50
    H = round(max(324 + 24.5 * (len(lede) - 1), 84 + rh) + 36)
    s = Svg(t, W, H)
    s.defs.append(
        f'<clipPath id="clip"><rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="8"/></clipPath>'
        f'<radialGradient id="glow" cx="{W / 2}" cy="-46" r="{W * 0.35}" gradientUnits="userSpaceOnUse" '
        f'gradientTransform="translate({W / 2} -46) scale(2 1.2) translate({-W / 2} 46)">'
        f'<stop offset="0" stop-color="{t["acc"]}" stop-opacity="{t["glow"] * 2.2}"/>'
        f'<stop offset="1" stop-color="{t["acc"]}" stop-opacity="0"/></radialGradient>'
        f'<filter id="shadow" x="-30%" y="-30%" width="160%" height="170%">'
        f'<feDropShadow dx="0" dy="18" stdDeviation="18" flood-color="{t["shadow"][0]}" flood-opacity="{t["shadow"][1]}"/></filter>'
    )
    s.frame()
    s.add(f'<g clip-path="url(#clip)"><rect width="{W}" height="{H}" fill="url(#glow)"/>')

    # nav: logo lockup, page segment, version pill, CTA
    s.add(f'<rect width="{W}" height="52" fill="{t["bg0"]}" opacity=".6"/>'
          f'<line x1="0" y1="52.5" x2="{W}" y2="52.5" stroke="{t["line"]}"/></g>')
    logo = base64.b64encode(LOGO.read_bytes()).decode()
    s.add(f'<image x="22" y="14" width="24" height="24" href="data:image/png;base64,{logo}"/>')
    x = 56
    s.text(x, 31, "CyNickal", "sans", 600, 14, "tx", -0.14)
    x += M.width("CyNickal", "sans", 600, 14, -0.14) + 4
    s.text(x, 31, "Software", "sans", 400, 14, "txd", -0.14)
    x += M.width("Software", "sans", 400, 14, -0.14) + 10
    s.text(x, 31.5, "/", "sans", 400, 15, "txf")
    x += 14
    s.text(x, 31, "Profile", "sans", 600, 14, "tx", -0.14)
    x += M.width("Profile", "sans", 600, 14, -0.14) + 10
    pw = M.width("GITHUB", "mono", 400, 10, 1.0) + 14
    s.add(f'<rect x="{x:.1f}" y="16.5" width="{pw:.1f}" height="19" rx="5" stroke="{t["line"]}"/>')
    s.text(x + 7, 29.5, "GITHUB", "mono", 400, 10, "txd", 1.0)

    cta = "cynickalsoftware.com"
    cw = M.width(cta, "sans", 500, 12.5) + 28
    cx = W - 22 - cw
    s.add(f'<rect x="{cx:.1f}" y="11.5" width="{cw:.1f}" height="29" rx="7" fill="{t["acc"]}" '
          f'fill-opacity=".16" stroke="{t["acc"]}"/>')
    s.text(cx + cw / 2, 30.5, cta, "sans", 500, 12.5, "acc", anchor="middle")

    # left column
    x0, y = 36, 84
    bw = 28 + M.width(c["badge"].upper(), "mono", 500, 10.5, 1.47) + 14
    s.add(f'<rect x="{x0 + .5}" y="{y + .5}" width="{bw:.1f}" height="26" rx="13" '
          f'fill="{t["bg2"]}" fill-opacity=".8" stroke="{t["line2"]}"/>')
    s.dot(x0 + 16, y + 13.5, t["acc"])
    s.text(x0 + 28, y + 17.5, c["badge"], "mono", 500, 10.5, "txd", 1.47, upper=True)

    y = 160
    for line in c["headline"]:
        s.text(x0, y, line, "sans", 600, 36, "tx", -0.9)
        y += 40
    y += 4
    s.text(x0, y, c["sub"], "mono", 400, 11.5, "txf", 0.69)
    y += 34
    for line in lede:
        s.text(x0, y, line, "sans", 400, 14.5, "txd")
        y += 24.5

    # right column: readout card
    rx, ry, rw = 500, 84, W - 36 - 500
    s.add(f'<g filter="url(#shadow)"><rect x="{rx}" y="{ry}" width="{rw}" height="{rh}" rx="8" fill="{t["bg2"]}"/></g>')
    head = mix(t["bg0"], t["bg2"], 0.2)
    s.add(f'<path d="M{rx} {ry + 36}V{ry + 8}a8 8 0 0 1 8 -8H{rx + rw - 8}a8 8 0 0 1 8 8V{ry + 36}Z" fill="{head}"/>'
          f'<line x1="{rx}" y1="{ry + 36.5}" x2="{rx + rw}" y2="{ry + 36.5}" stroke="{t["line"]}"/>')
    s.text(rx + 14, ry + 22, "Profile readout", "mono", 600, 10, "txf", 1.4, upper=True)
    s.text(rx + rw - 14, ry + 22, "Active", "mono", 600, 10, "ok", 1.4, anchor="end", upper=True)
    s.dot(rx + rw - 14 - M.width("ACTIVE", "mono", 600, 10, 1.4) - 9, ry + 18.5, t["ok"])

    yy = ry + 42
    for label, value, acc in rows:
        s.text(rx + 14, yy + 21, label, "sans", 400, 12.5, "txd")
        s.text(rx + rw - 14, yy + 21, value, "mono", 400, 12.5, "acc" if acc else "tx", anchor="end")
        yy += 33

    fy = yy + 6
    s.add(f'<line x1="{rx}" y1="{fy + .5}" x2="{rx + rw}" y2="{fy + .5}" stroke="{t["line"]}"/>')
    s.text(rx + 14, fy + 22, "Focus areas", "sans", 400, 11.5, "txd")
    s.text(rx + rw - 14, fy + 22, "3 / 3", "mono", 400, 11.5, "tx", anchor="end")
    s.add(f'<rect x="{rx + 14}" y="{fy + 31}" width="{rw - 28}" height="4" rx="2" fill="{t["bg0"]}"/>'
          f'<rect x="{rx + 14}" y="{fy + 31}" width="{rw - 28}" height="4" rx="2" fill="{t["acc"]}"/>')
    s.add(f'<rect x="{rx + .5}" y="{ry + .5}" width="{rw - 1}" height="{rh - 1}" rx="8" stroke="{t["line2"]}"/>')
    return s


def focus(t):
    cards = CONTENT["focus"]
    gap = 12
    cw = (W - 2 * PAD - gap * (len(cards) - 1)) / len(cards)
    bodies = [wrap(b, cw - 36, "sans", 400, 13) for _, _, b, _ in cards]
    ch = 90 + 20 * max(map(len, bodies)) + 48
    top = PAD + 66
    s = Svg(t, W, top + ch + PAD)
    s.frame()
    s.section_head("01", ("Focus", "Where I’m currently focused"))
    for i, ((kicker, title, _, ref), body) in enumerate(zip(cards, bodies)):
        x = PAD + i * (cw + gap)
        s.add(f'<rect x="{x + .5:.1f}" y="{top + .5}" width="{cw - 1:.1f}" height="{ch - 1}" rx="8" '
              f'fill="{t["bg2"]}" stroke="{t["line"]}"/>')
        s.text(x + 18, top + 30, f"0{i + 1} · {kicker}", "mono", 500, 10, "acc", 1.4, upper=True)
        s.text(x + 18, top + 56, title, "sans", 600, 16, "tx", -0.2)
        y = top + 84
        for line in body:
            s.text(x + 18, y, line, "sans", 400, 13, "txd")
            y += 20
        s.add(f'<line x1="{x + 1:.1f}" y1="{top + ch - 38.5}" x2="{x + cw - 1:.1f}" y2="{top + ch - 38.5}" stroke="{t["line"]}"/>')
        s.text(x + 18, top + ch - 15, "Ref", "mono", 500, 10, "txf", 1.4, upper=True)
        s.text(x + 52, top + ch - 15, ref, "mono", 400, 11, "tx")
    return s


def stack(t):
    items = CONTENT["stack"]
    cols = 4
    rows = -(-len(items) // cols)
    cell_h = 76
    top = PAD + 66
    gw = W - 2 * PAD
    s = Svg(t, W, top + rows * cell_h + (rows + 1) + PAD)
    s.frame()
    s.section_head("02", ("Stack", "Tech stack"))
    gh = rows * cell_h + rows + 1
    s.defs.append(f'<clipPath id="grid"><rect x="{PAD}" y="{top}" width="{gw}" height="{gh}" rx="8"/></clipPath>')
    s.add(f'<g clip-path="url(#grid)"><rect x="{PAD}" y="{top}" width="{gw}" height="{gh}" fill="{t["line"]}"/>')
    cw = (gw - (cols + 1)) / cols
    for i, (name, label, primary) in enumerate(items):
        r, c = divmod(i, cols)
        x = PAD + 1 + c * (cw + 1)
        y = top + 1 + r * (cell_h + 1)
        s.add(f'<rect x="{x:.2f}" y="{y}" width="{cw:.2f}" height="{cell_h}" fill="{t["bg2"]}"/>')
        s.text(x + 16, y + 36, name, "mono", 500, 22, "tx", -0.44)
        s.text(x + 16, y + 57, label, "mono", 400, 10, "acc" if primary else "txf", 1.4, upper=True)
        if primary:
            s.add(f'<circle cx="{x + cw - 18:.2f}" cy="{y + 18}" r="3" fill="{t["acc"]}"/>')
    s.add("</g>")
    return s


def contact(t):
    lines = wrap(CONTENT["contact_lede"], W - 2 * PAD - 40, "sans", 400, 14.5)
    s = Svg(t, W, round(PAD + 66 + 24.5 * len(lines) - 6 + PAD))
    s.frame()
    s.section_head("03", ("Contact", "Get in touch"))
    y = PAD + 76
    for line in lines:
        s.text(PAD, y, line, "sans", 400, 14.5, "txd")
        y += 24.5
    return s


ICONS = {
    # 16x16 strokes, drawn rather than relying on glyph coverage
    "arrow": "M4 12L12 4M6 4h6v6",
    "mail": "M2.5 4.5h11v8h-11zM2.5 5l5.5 4.5L13.5 5",
    "chat": "M3 3.5h10a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H7l-3 2.5v-2.5H3a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1z",
}


def button(t, label, icon, primary):
    tw = M.width(label, "sans", 600 if primary else 500, 13.5)
    w = round(18 + 16 + 8 + tw + 18)
    s = Svg(t, w, 36)
    fg = t["on_acc"] if primary else t["txd"]
    if primary:
        s.add(f'<rect x=".5" y=".5" width="{w - 1}" height="35" rx="7" fill="{t["acc"]}" stroke="{t["acc"]}"/>'
              f'<line x1="7" y1="1.5" x2="{w - 7}" y2="1.5" stroke="#fff" stroke-opacity=".25"/>')
    else:
        s.add(f'<rect x=".5" y=".5" width="{w - 1}" height="35" rx="7" fill="{t["bg2"]}" stroke="{t["line2"]}"/>')
    s.add(f'<path d="{ICONS[icon]}" transform="translate(18 10)" stroke="{fg}" stroke-width="1.5" '
          f'stroke-linecap="round" stroke-linejoin="round"/>')
    s.text(42, 22.5, label, "sans", 600 if primary else 500, 13.5, fg)
    return s


BUTTONS = {
    "btn-site": ("Visit cynickalsoftware.com", "arrow", True),
    "btn-email": ("cynickal@cynickal.com", "mail", False),
    "btn-discord": ("Discord · cynickal", "chat", False),
}


# ------------------------------------------------------------------ build

def font_css():
    """woff2 subsets of exactly the characters the cards use, as data URIs."""
    text = "".join(sorted(Svg.used_chars))
    css = fetch(CSS_URL + "&text=" + urllib.parse.quote(text), UA_WOFF2).decode()
    out = {}
    for fam, wt, url in faces(css):
        key = ("sans" if "Sans" in fam else "mono", wt)
        data = base64.b64encode(fetch(url)).decode()
        out[key] = (f"@font-face{{font-family:'{fam}';font-weight:{wt};"
                    f"src:url(data:font/woff2;base64,{data}) format('woff2')}}\n")
    # The sans subset is a single variable font; declare it once across the range.
    sans = [k for k in out if k[0] == "sans"]
    if sans and len({out[k].split("src:")[1] for k in sans}) == 1:
        rule = out[sans[0]].replace(f"font-weight:{sans[0][1]}", "font-weight:400 700")
        for k in sans:
            out[k] = rule
    return out


def main():
    cards = {}
    for name, t in THEMES.items():
        cards[name] = {"hero": hero(t), "focus": focus(t), "stack": stack(t), "contact": contact(t)}
        for key, args in BUTTONS.items():
            cards[name][key] = button(t, *args)
    fonts = font_css()
    for name, group in cards.items():
        out = ROOT / "assets" / name
        out.mkdir(parents=True, exist_ok=True)
        for key, svg in group.items():
            (out / f"{key}.svg").write_text(svg.render(fonts), encoding="utf-8")
            print(f"assets/{name}/{key}.svg  {svg.w}x{svg.h}")


if __name__ == "__main__":
    main()

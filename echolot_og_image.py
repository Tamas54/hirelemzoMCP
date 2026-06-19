"""echolot_og_image — dinamikus, tartalom-specifikus OG-kép a story-oldalhoz.

A megosztott story-link előnézete eddig a generikus /static/og-image.png-t
mutatta. A messengerek/AI-crawlerek a `og:image`-et MULTIMODÁLISAN olvassák,
ezért tartalom-specifikus kártya sokkal többet ér: a néző a megosztásból
azonnal látja a TÉMÁT, a politikai-spektrum megoszlást és a forrásszámot.

Megbízhatóság: PNG-t renderelünk (Pillow), mert az SVG-`og:image`-et a
Facebook/Viber/Signal nem renderelik megbízhatóan. A betűtípus a repóba
csomagolt DejaVu (Latin + Cyrillic) → HU/EN/DE/ES/FR/PL/RU/UK/IT lefedve;
ismeretlen glyph (pl. zh) helyén a Pillow tofu-t rak, ami elfogadható fallback.

Az `og_image_bytes()` self-contained: nincs DB- vagy LLM-hívás, csak a hívó
által átadott, már kiszámolt értékekből (cím, L/C/R, forrásszám) rajzol —
így a generálás gyors és cache-elhető.
"""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_OK = True
except Exception:  # pragma: no cover - Pillow hiányában a route kecsesen 404-el
    _PIL_OK = False

_FONT_DIR = Path(__file__).parent / "static" / "fonts"
_FONT_REGULAR = _FONT_DIR / "DejaVuSans.ttf"
_FONT_BOLD = _FONT_DIR / "DejaVuSans-Bold.ttf"

# 1200×630 = a Facebook/Twitter/LinkedIn ajánlott OG-méret (1.91:1).
_W, _H = 1200, 630
_PAD = 72

# Márka-paletta (a night-téma alapján; sötét kártya jól mutat világos és
# sötét chat-háttéren is). NEM a CSS-változókból jön, mert azok nem
# resolválhatók Pillow-ban — ez egy szándékosan stabil, önálló paletta.
_BG = (10, 13, 18)          # #0a0d12 — night bg
_CARD = (17, 22, 30)        # enyhén világosabb panel
_FG = (237, 240, 244)       # near-white főszöveg
_FG_DIM = (148, 158, 170)   # halvány metaszöveg
_ACCENT = (20, 184, 166)    # #14b8a6 — petrol/teal accent (wordmark)
_POL = {
    "L": (194, 90, 90),     # #c25a5a
    "C": (142, 142, 142),   # #8e8e8e
    "R": (77, 126, 200),    # #4d7ec8
}

# Forrásszám-címke nyelvenként (a story-oldal _LBL/i18n mintájára).
_SOURCES_LBL = {
    "hu": "forrás", "en": "sources", "de": "Quellen", "es": "fuentes",
    "fr": "sources", "it": "fonti", "pl": "źródła", "ru": "источников",
    "uk": "джерел", "zh": "来源",
}


@lru_cache(maxsize=8)
def _font(bold: bool, size: int):
    path = _FONT_BOLD if bold else _FONT_REGULAR
    return ImageFont.truetype(str(path), size)


def _text_w(draw, text: str, font) -> float:
    return draw.textlength(text, font=font)


def _wrap(draw, text: str, font, max_w: float, max_lines: int) -> list[str]:
    """Szóhatáron tördel max_w szélességre, max_lines sorra; az utolsó sort
    ellipszissel zárja, ha túlcsordul."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if _text_w(draw, trial, font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    # Utolsó sor ellipszizálása, ha még maradt szó / túl hosszú
    if lines:
        consumed = sum(len(l.split()) for l in lines)
        if consumed < len(words):
            last = lines[-1]
            while _text_w(draw, last + " …", font) > max_w and last:
                last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
            lines[-1] = last + " …"
    return lines or [""]


def og_image_bytes(
    *,
    title: str,
    bias: dict | None = None,
    n_sources: int = 0,
    sphere_label: str = "",
    lang: str = "hu",
) -> bytes | None:
    """Visszaad egy 1200×630 PNG-t (bytes) a story megosztásához, vagy None,
    ha a Pillow nem elérhető (a hívó ekkor a statikus képre eshet vissza).

    Args:
        title: a sztori címe (tördelve, ellipszizálva jelenik meg)
        bias: {"L": %, "C": %, "R": %} politikai-spektrum megoszlás
        n_sources: forrásszám (a forrásszám-chiphez)
        sphere_label: emberi szféra-név (pl. "Világpolitika")
        lang: UI-nyelv (a forrásszám-címkéhez)
    """
    if not _PIL_OK:
        return None

    img = Image.new("RGB", (_W, _H), _BG)
    d = ImageDraw.Draw(img)

    # Bal accent-sáv (márka-jel)
    d.rectangle([0, 0, 10, _H], fill=_ACCENT)

    x = _PAD
    y = _PAD

    # ── Wordmark ──────────────────────────────────────────────────────
    wm_font = _font(True, 30)
    d.text((x, y), "ECHOLOT", font=wm_font, fill=_ACCENT)
    wm_w = _text_w(d, "ECHOLOT", wm_font)
    tag_font = _font(False, 22)
    d.text((x + wm_w + 16, y + 5), "· narrative-divergence",
           font=tag_font, fill=_FG_DIM)

    # Szféra-chip jobbra fent
    if sphere_label:
        chip_font = _font(True, 22)
        chip_txt = sphere_label.upper()
        ctw = _text_w(d, chip_txt, chip_font)
        cx1 = _W - _PAD
        cx0 = cx1 - ctw - 32
        d.rounded_rectangle([cx0, y - 6, cx1, y + 38], radius=10, fill=_CARD)
        d.text((cx0 + 16, y + 2), chip_txt, font=chip_font, fill=_ACCENT)

    # ── Cím (a kártya gerince) ────────────────────────────────────────
    title_font = _font(True, 64)
    title_y = y + 92
    max_w = _W - 2 * _PAD
    lines = _wrap(d, (title or "—").strip(), title_font, max_w, max_lines=3)
    line_h = 78
    for i, line in enumerate(lines):
        d.text((x, title_y + i * line_h), line, font=title_font, fill=_FG)

    # ── Alsó blokk: L/C/R sáv + forrásszám ────────────────────────────
    bias = bias or {}
    L = max(0, int(bias.get("L", 0) or 0))
    C = max(0, int(bias.get("C", 0) or 0))
    R = max(0, int(bias.get("R", 0) or 0))
    total = L + C + R

    bar_h = 56
    bar_y1 = _H - _PAD - bar_h
    bar_y0 = bar_y1 - bar_h
    bar_x0 = x
    bar_x1 = _W - _PAD - 320  # jobb oldalt hely a forrásszám-chipnek
    bar_w = bar_x1 - bar_x0

    seg_font = _font(True, 26)
    if total > 0:
        segs = [("L", L), ("C", C), ("R", R)]
        cx = bar_x0
        for idx, (key, val) in enumerate(segs):
            seg_w = bar_w * (val / total)
            if seg_w < 1:
                continue
            x_end = bar_x1 if idx == len(segs) - 1 else cx + seg_w
            d.rectangle([cx, bar_y0, x_end, bar_y1], fill=_POL[key])
            label = f"{key} {val}%"
            lw = _text_w(d, label, seg_font)
            if seg_w > lw + 16:  # csak ha kifér a feliratot
                d.text((cx + (x_end - cx - lw) / 2, bar_y0 + (bar_h - 32) / 2),
                       label, font=seg_font, fill=(255, 255, 255))
            cx = x_end
    else:
        # nincs klasszifikált megoszlás → semleges placeholder-sáv
        d.rectangle([bar_x0, bar_y0, bar_x1, bar_y1], fill=_CARD)

    # Forrásszám-chip (jobb alsó)
    if n_sources:
        num_font = _font(True, 64)
        lbl_font = _font(False, 28)
        lbl = _SOURCES_LBL.get(lang, _SOURCES_LBL["en"])
        num_txt = str(n_sources)
        ntw = _text_w(d, num_txt, num_font)
        lblw = _text_w(d, lbl, lbl_font)
        block_w = max(ntw, lblw)
        bx1 = _W - _PAD
        d.text((bx1 - ntw, bar_y0 - 4), num_txt, font=num_font, fill=_ACCENT)
        d.text((bx1 - lblw, bar_y0 + 66), lbl, font=lbl_font, fill=_FG_DIM)
        _ = block_w  # (jövőbeli igazításhoz)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

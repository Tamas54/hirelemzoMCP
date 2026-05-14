"""Sphere hierarchy taxonomy for Echolot.

Some spheres are "regional supersets" that subsume specific source-level
sub-spheres (regional_korean ⊃ kr_press_english). When an article is tagged
with both parent and child, downstream dedup logic should:
  - default mode: keep child only (more specific = more informative)
  - collapse_to_parent mode: keep parent only (higher-level rollup)

This module exports:
  PARENT_TO_CHILDREN: dict[str, set[str]]
  CHILD_TO_PARENT:    dict[str, str]   (built from PARENT_TO_CHILDREN)
  dedup_spheres(spheres, *, collapse_to_parent=False) -> list[str]
  is_parent(sphere) -> bool
  is_child(sphere) -> bool
"""

from __future__ import annotations

PARENT_TO_CHILDREN: dict[str, set[str]] = {
    "regional_korean":    {"kr_press_english"},
    "regional_japanese":  {"jp_press_english", "jp_press_native"},
    "regional_chinese":   {"cn_state", "cn_state_aligned", "cn_hk", "cn_tw",
                           "cn_weibo_pulse", "cn_diaspora_analysis"},
    "regional_iranian":   {"iran_regime", "iran_opposition"},
    "regional_israeli":   {"israel_press_center", "israel_press_left",
                           "israel_press_right"},
    "regional_russian":   {"ru_state_media", "ru_opposition", "ru_milblog_pro"},
    "regional_ukrainian": {"ua_front_osint"},
    "regional_us":        {"us_liberal_press", "us_liberal_substack",
                           "us_maga_blog", "us_maga_substack"},
}

CHILD_TO_PARENT: dict[str, str] = {
    child: parent
    for parent, children in PARENT_TO_CHILDREN.items()
    for child in children
}


def is_parent(sphere: str) -> bool:
    return sphere in PARENT_TO_CHILDREN


def is_child(sphere: str) -> bool:
    return sphere in CHILD_TO_PARENT


def dedup_spheres(spheres, *, collapse_to_parent: bool = False) -> list[str]:
    """Dedup a sphere list against the parent-child taxonomy.

    Default mode (specificity-first):
      Drop any parent sphere whose at least one child is also present.
      regional_korean+kr_press_english → kr_press_english only
      regional_chinese+cn_state+cn_hk → cn_state+cn_hk only

    collapse_to_parent mode (rollup):
      Drop any child sphere if its parent is also present.
      regional_korean+kr_press_english → regional_korean only
      Useful for higher-level cross-region narrative comparison.

    Spheres unaffected by the taxonomy pass through unchanged.
    Output preserves input order with duplicates removed.
    """
    if not spheres:
        return []
    s = set(spheres)
    if collapse_to_parent:
        # Drop any child whose parent is in the set
        keep = {sph for sph in s if not (is_child(sph) and CHILD_TO_PARENT[sph] in s)}
    else:
        # Drop any parent whose at least one child is in the set
        keep = {sph for sph in s
                if not (is_parent(sph) and PARENT_TO_CHILDREN[sph] & s)}
    # Preserve input order
    seen: set[str] = set()
    out: list[str] = []
    for sph in spheres:
        if sph in keep and sph not in seen:
            out.append(sph)
            seen.add(sph)
    return out

"""Regenerate the documentation diagrams in docs/.

    python docs/generate_diagrams.py

Writes two files:

  docs/lineage_dag.svg  the dbt DAG, derived entirely from target/manifest.json,
                        so it is correct by construction and never goes stale.
  docs/erd.svg          the star-schema ER diagram. Its layout and column lists
                        are curated (showing every column would be unreadable),
                        but the foreign keys it draws are cross-checked against
                        the `relationships` tests in the manifest. If the model
                        gains or loses an FK and this file isn't updated, the
                        script exits non-zero and tells you what diverged.

Needs a manifest, so run dbt at least once first (`dbt parse` is enough):

    cd dbt && dbt parse --profiles-dir .
"""

from __future__ import annotations

import json
import sys
from html import escape
from pathlib import Path

DOCS = Path(__file__).resolve().parent
REPO = DOCS.parent
MANIFEST = REPO / "dbt" / "target" / "manifest.json"


def load_manifest() -> dict:
    if not MANIFEST.exists():
        sys.exit(
            f"No manifest at {MANIFEST}.\n"
            "Run `cd dbt && dbt parse --profiles-dir .` first."
        )
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# lineage diagram
# --------------------------------------------------------------------------

LINEAGE_STYLE = {
    "source":       ("#4b5563", "raw source"),
    "seed":         ("#7c5c9e", "seed"),
    "staging":      ("#1f6f8b", "staging (view)"),
    "intermediate": ("#2f6f4f", "intermediate (view)"),
    "marts":        ("#1f4e79", "mart (table)"),
    "test":         ("#b45309", "singular test"),
}


def build_lineage(m: dict) -> tuple[str, str]:
    nodes: dict[str, dict] = {}

    for nid, s in m["sources"].items():
        nodes[nid] = {"label": f'{s["source_name"]}.{s["name"]}', "kind": "source"}

    for nid, n in m["nodes"].items():
        rt = n["resource_type"]
        if rt == "seed":
            nodes[nid] = {"label": n["name"], "kind": "seed"}
        elif rt == "model":
            path = n.get("path", "").replace("\\", "/")
            layer = "marts"
            for cand in ("staging", "intermediate", "marts"):
                if path.startswith(cand + "/"):
                    layer = cand
            nodes[nid] = {"label": n["name"], "kind": layer}
        elif rt == "test" and n["name"].startswith("assert_"):
            # bespoke singular tests only; the generic ones would swamp the picture
            nodes[nid] = {"label": n["name"], "kind": "test"}

    edges = [
        (p, c)
        for c, parents in m["parent_map"].items()
        if c in nodes
        for p in parents
        if p in nodes
    ]

    # longest-path depth, so every edge points strictly rightwards
    depth = {n: 0 for n in nodes}
    for _ in range(len(nodes)):
        changed = False
        for p, c in edges:
            if depth[c] < depth[p] + 1:
                depth[c] = depth[p] + 1
                changed = True
        if not changed:
            break

    cols: dict[int, list[str]] = {}
    for n, d in depth.items():
        cols.setdefault(d, []).append(n)
    for d in cols:
        cols[d].sort(key=lambda n: (nodes[n]["kind"], nodes[n]["label"]))

    BOX_H, VGAP, COL_GAP, PAD, TITLE_H = 30, 16, 74, 30, 58

    def width_for(label: str) -> int:
        return max(150, int(len(label) * 6.7) + 26)

    col_w = {d: max(width_for(nodes[n]["label"]) for n in ns) for d, ns in cols.items()}
    col_x, x = {}, PAD
    for d in sorted(cols):
        col_x[d] = x
        x += col_w[d] + COL_GAP
    W = x - COL_GAP + PAD
    H = TITLE_H + max(len(ns) for ns in cols.values()) * (BOX_H + VGAP) + PAD + 34

    parents_of: dict[str, list[str]] = {}
    for p, c in edges:
        parents_of.setdefault(c, []).append(p)

    def y_of(n: str) -> float:
        ns = cols[depth[n]]
        span = len(ns) * (BOX_H + VGAP) - VGAP
        top = TITLE_H + (H - TITLE_H - PAD - span) / 2
        return top + ns.index(n) * (BOX_H + VGAP)

    # barycentre passes to reduce edge crossings
    for _ in range(4):
        for d in sorted(cols):
            if d == 0:
                continue
            cols[d].sort(
                key=lambda n: (
                    sum(y_of(p) for p in parents_of.get(n, [])) / len(parents_of[n])
                    if parents_of.get(n)
                    else 0
                )
            )

    pos = {n: (col_x[depth[n]], y_of(n), col_w[depth[n]]) for n in nodes}

    p: list[str] = []
    p.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="12">'
    )
    p.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>')
    p.append(
        f'<text x="{PAD}" y="30" font-size="17" font-weight="700" fill="#222">'
        f"dbt lineage — football_analytics</text>"
    )
    p.append(
        f'<text x="{PAD}" y="47" font-size="11" fill="#666">'
        f"generated from target/manifest.json; generic tests omitted for readability</text>"
    )

    for a, b in edges:
        ax, ay, aw = pos[a]
        bx, by, _ = pos[b]
        x1, y1 = ax + aw, ay + BOX_H / 2
        x2, y2 = bx, by + BOX_H / 2
        mid = (x1 + x2) / 2
        p.append(
            f'<path d="M {x1} {y1} C {mid} {y1}, {mid} {y2}, {x2} {y2}" '
            f'fill="none" stroke="#b6bec9" stroke-width="1.3"/>'
        )
        p.append(f'<circle cx="{x2}" cy="{y2}" r="2.6" fill="#b6bec9"/>')

    for n, (bx, by, bw) in pos.items():
        fill, _ = LINEAGE_STYLE[nodes[n]["kind"]]
        p.append(
            f'<rect x="{bx}" y="{by}" width="{bw}" height="{BOX_H}" rx="6" ry="6" '
            f'fill="{fill}"/>'
        )
        p.append(
            f'<text x="{bx + bw / 2}" y="{by + 19.5}" text-anchor="middle" '
            f'fill="#ffffff" font-weight="600">{escape(nodes[n]["label"])}</text>'
        )

    lx, ly = PAD, H - 16
    for fill, label in LINEAGE_STYLE.values():
        p.append(f'<rect x="{lx}" y="{ly - 9}" width="11" height="11" rx="2" fill="{fill}"/>')
        p.append(f'<text x="{lx + 16}" y="{ly}" font-size="11" fill="#555">{label}</text>')
        lx += 20 + int(len(label) * 6.2) + 22

    p.append("</svg>")
    summary = f"{len(nodes)} nodes, {len(edges)} edges, {len(cols)} layers, {W}x{H}"
    return "\n".join(p), summary


# --------------------------------------------------------------------------
# ER diagram
# --------------------------------------------------------------------------

ROW_H, HEAD_H, PAD_B = 20, 28, 8
HEAD_FILL = {"dim": "#2f6f4f", "fact": "#1f4e79"}

# Curated: position, and the columns worth showing. Keep the key columns first.
ERD_BOXES = {
    "dim_competitions": (470, 20, 240, "dim", [
        ("competition_code", "PK"), ("competition_name", ""), ("competition_type", "")]),
    "dim_seasons": (470, 250, 240, "dim", [
        ("season_id", "PK"), ("competition_code", "FK"), ("season_label", ""),
        ("season_start_date", ""), ("season_end_date", "")]),
    "dim_teams": (470, 470, 240, "dim", [
        ("team_id", "PK"), ("team_name", ""), ("tla", ""), ("area_name", "")]),
    "fact_matches": (40, 140, 300, "fact", [
        ("match_id", "PK"), ("competition_code", "FK"), ("season_id", "FK"),
        ("home_team_id", "FK"), ("away_team_id", "FK"), ("stage", ""),
        ("status / matchday / winner", ""), ("scores + points (measures)", "")]),
    "fact_standings": (840, 360, 300, "fact", [
        ("standing_key", "PK"), ("competition_code", "FK"), ("season_id", "FK"),
        ("team_id", "FK"), ("matchday", ""), ("played / won / drawn / lost", ""),
        ("goals + points + position", "")]),
}

# (child, fk_column, parent, parent_column, connector)
#   "r"/"l" = leave the child's right/left edge; "v" = vertical between rows
ERD_RELS = [
    ("fact_matches", "competition_code", "dim_competitions", "competition_code", "r"),
    ("fact_matches", "season_id", "dim_seasons", "season_id", "r"),
    ("fact_matches", "home_team_id", "dim_teams", "team_id", "r"),
    ("fact_matches", "away_team_id", "dim_teams", "team_id", "r"),
    ("fact_standings", "competition_code", "dim_competitions", "competition_code", "l"),
    ("fact_standings", "season_id", "dim_seasons", "season_id", "l"),
    ("fact_standings", "team_id", "dim_teams", "team_id", "l"),
    ("dim_seasons", "competition_code", "dim_competitions", "competition_code", "v"),
]


def relationships_from_manifest(m: dict) -> set[tuple[str, str, str, str]]:
    """Every FK the model actually declares, from its `relationships` tests."""
    found = set()
    for nid, n in m["nodes"].items():
        meta = n.get("test_metadata") or {}
        if meta.get("name") != "relationships":
            continue
        kwargs = meta.get("kwargs") or {}
        child = None
        attached = n.get("attached_node")
        if attached and attached in m["nodes"]:
            child = m["nodes"][attached]["name"]
        if child is None:  # fall back to the yml file the test came from
            fkn = (n.get("file_key_name") or "").split(".")[-1]
            child = fkn or "?"
        to = str(kwargs.get("to", ""))          # e.g. "ref('dim_teams')"
        parent = to.split("'")[1] if "'" in to else to
        found.add((child, n.get("column_name") or "", parent, str(kwargs.get("field", ""))))
    return found


def check_erd_against_manifest(m: dict) -> None:
    declared = relationships_from_manifest(m)
    drawn = {(c, col, p, pcol) for c, col, p, pcol, _ in ERD_RELS}
    missing = declared - drawn
    extra = drawn - declared
    if missing or extra:
        print("ERD is out of step with the model's relationships tests:", file=sys.stderr)
        for c, col, p, pcol in sorted(missing):
            print(f"  in model, not in diagram: {c}.{col} -> {p}.{pcol}", file=sys.stderr)
        for c, col, p, pcol in sorted(extra):
            print(f"  in diagram, not in model: {c}.{col} -> {p}.{pcol}", file=sys.stderr)
        sys.exit("Update ERD_BOXES/ERD_RELS in this script, then re-run.")
    print(f"  ERD foreign keys cross-checked against {len(declared)} relationships tests: OK")


def box_height(cols) -> int:
    return HEAD_H + len(cols) * ROW_H + PAD_B


def build_erd() -> tuple[str, str]:
    def col_y(box: str, col: str) -> float:
        x, y, w, kind, cols = ERD_BOXES[box]
        for i, (name, _tag) in enumerate(cols):
            if name == col:
                return y + HEAD_H + i * ROW_H + ROW_H / 2
        return y + HEAD_H + ROW_H / 2

    def edge_x(box: str, side: str) -> float:
        x, y, w, *_ = ERD_BOXES[box]
        return x + w if side == "r" else x

    W, H = 1180, 700
    p: list[str] = []
    p.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13">'
    )
    p.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>')
    p.append(
        '<text x="40" y="26" font-size="18" font-weight="700" fill="#222">'
        "Star schema (football_analytics.marts)</text>"
    )

    for child, col, parent, pcol, style in ERD_RELS:
        if style == "v":
            cx, cy, cw, *_ = ERD_BOXES[child]
            px, py, pw, _k, pcols = ERD_BOXES[parent]
            x = px + pw / 2
            y1 = py + box_height(pcols)
            y2 = cy
            p.append(
                f'<path d="M {x} {y1} L {x} {y2}" fill="none" stroke="#9aa4b2" '
                f'stroke-width="1.5"/>'
            )
            p.append(f'<circle cx="{x}" cy="{y2}" r="3" fill="#9aa4b2"/>')
            p.append(f'<rect x="{x - 5}" y="{y1}" width="10" height="2" fill="#9aa4b2"/>')
            continue
        to_side = "l" if style == "r" else "r"
        x1, y1 = edge_x(child, style), col_y(child, col)
        x2, y2 = edge_x(parent, to_side), col_y(parent, pcol)
        mid = (x1 + x2) / 2
        p.append(
            f'<path d="M {x1} {y1} C {mid} {y1}, {mid} {y2}, {x2} {y2}" '
            f'fill="none" stroke="#9aa4b2" stroke-width="1.5"/>'
        )
        p.append(f'<circle cx="{x1}" cy="{y1}" r="3" fill="#9aa4b2"/>')
        p.append(f'<rect x="{x2 - (2 if to_side == "r" else 0)}" y="{y2 - 5}" '
                 f'width="2" height="10" fill="#9aa4b2"/>')

    for box, (x, y, w, kind, cols) in ERD_BOXES.items():
        h = box_height(cols)
        p.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" ry="7" '
            f'fill="#ffffff" stroke="#8a94a6" stroke-width="1.5"/>'
        )
        p.append(
            f'<path d="M {x} {y + HEAD_H} L {x} {y + 7} Q {x} {y} {x + 7} {y} '
            f'L {x + w - 7} {y} Q {x + w} {y} {x + w} {y + 7} L {x + w} {y + HEAD_H} Z" '
            f'fill="{HEAD_FILL[kind]}"/>'
        )
        p.append(
            f'<text x="{x + w / 2}" y="{y + 19}" text-anchor="middle" fill="#ffffff" '
            f'font-weight="700">{escape(box)}</text>'
        )
        for i, (name, tag) in enumerate(cols):
            ry = y + HEAD_H + i * ROW_H
            if i % 2 == 1:
                p.append(f'<rect x="{x + 1}" y="{ry}" width="{w - 2}" height="{ROW_H}" '
                         f'fill="#f4f6f9"/>')
            weight = "700" if tag == "PK" else "400"
            colour = "#1f4e79" if tag == "FK" else "#222"
            p.append(
                f'<text x="{x + 10}" y="{ry + 14}" fill="{colour}" font-weight="{weight}">'
                f"{escape(name)}</text>"
            )
            if tag:
                badge = "#2f6f4f" if tag == "PK" else "#1f4e79"
                p.append(
                    f'<text x="{x + w - 10}" y="{ry + 14}" text-anchor="end" fill="{badge}" '
                    f'font-weight="700" font-size="11">{tag}</text>'
                )

    p.append(
        '<text x="40" y="660" fill="#555" font-size="12">'
        "PK = primary key    FK = foreign key    "
        "lines: one dimension row -&gt; many fact rows    "
        "(fact_matches joins dim_teams twice: home and away)</text>"
    )
    p.append("</svg>")
    return "\n".join(p), f"{len(ERD_BOXES)} tables, {len(ERD_RELS)} relationships"


def main() -> None:
    m = load_manifest()

    svg, summary = build_lineage(m)
    (DOCS / "lineage_dag.svg").write_text(svg, encoding="utf-8")
    print(f"wrote docs/lineage_dag.svg  ({summary})")

    check_erd_against_manifest(m)
    svg, summary = build_erd()
    (DOCS / "erd.svg").write_text(svg, encoding="utf-8")
    print(f"wrote docs/erd.svg          ({summary})")


if __name__ == "__main__":
    main()

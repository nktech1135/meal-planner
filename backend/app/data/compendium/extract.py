"""Rebuild adult_2024.json from the official 2024 Adult Compendium PDF.

Not used at runtime. Needs pdfplumber (not a project dependency):
    uv run --with pdfplumber python app/data/compendium/extract.py 1_2024-adult-compendium_1_2024.pdf

The PDF table has no ruling lines, so rows are rebuilt from word positions: a line holding a
five-digit activity code and a MET value anchors a row, and wrapped description lines (printed
above and below the anchor, vertically centred) join the nearest anchor on the page.
"""

import json
import re
import sys
from pathlib import Path

import pdfplumber

OUT = Path(__file__).with_name("adult_2024.json")


def rows_from_page(page) -> list[dict]:
    lines: list[list] = []
    for w in sorted(page.extract_words(), key=lambda w: (w["top"], w["x0"])):
        if lines and w["top"] - lines[-1][0] <= 1.5:
            lines[-1][1].append(w)
        else:
            lines.append([w["top"], [w]])
    anchors, orphans = [], []
    for top, ws in lines:
        ws.sort(key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in ws)
        if text.startswith(("Major Heading", "2024 Adult Compendium")):
            continue
        i = next((i for i, w in enumerate(ws[:-1]) if re.fullmatch(r"\d{5}", w["text"])
                  and re.fullmatch(r"\d+(\.\d+)?", ws[i + 1]["text"])), None)
        if i is None:
            orphans.append((top, ws))
            continue
        anchors.append({"top": top, "heading": [(top, " ".join(w["text"] for w in ws[:i]))], "code": ws[i]["text"],
                        "met": float(ws[i + 1]["text"]), "x": ws[i + 1]["x1"],
                        "desc": [(top, " ".join(w["text"] for w in ws[i + 2:]))]})
    for top, ws in orphans:
        a = min(anchors, key=lambda a: abs(a["top"] - top))
        a["heading"].append((top, " ".join(w["text"] for w in ws if w["x0"] <= a["x"])))
        a["desc"].append((top, " ".join(w["text"] for w in ws if w["x0"] > a["x"])))
    join = lambda parts: " ".join(t for _, t in sorted(parts) if t).strip()  # noqa: E731
    return [{"code": a["code"], "met": a["met"], "heading": join(a["heading"]), "description": join(a["desc"])}
            for a in anchors]


def main(pdf_path: str) -> None:
    with pdfplumber.open(pdf_path) as pdf:
        rows = [r for page in pdf.pages for r in rows_from_page(page)]
    codes = [r["code"] for r in rows]
    assert len(codes) == len(set(codes)), "duplicate activity codes"
    lines = (json.dumps([r["code"], r["met"], r["heading"], r["description"]], ensure_ascii=False) for r in rows)
    OUT.write_text("[\n" + ",\n".join(lines) + "\n]\n")  # one activity per line
    print(f"{len(rows)} activities written to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])

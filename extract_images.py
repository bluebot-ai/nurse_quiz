#!/usr/bin/env python3
"""Extract question images from exam PDFs and update JSON data files.

Images are assigned to the question whose stem they visually follow (reading
order), which is robust to:
  * PDFs whose internal image-object order != visual order
  * figures that consist of multiple images (圖(七) = 甲 + 乙, PA + lateral, ...)
  * questions whose A/B/C/D *options* are images (no 圖 reference in the stem)

For each question we set:
  q['image']         -> str | [str, ...]   (圖 figures referenced by the stem)
  q['option_images'] -> {"A": path, ...}   (when the options themselves are images)

Run `python3 extract_images.py` for a dry-run summary, add `--apply` to write
files. Requires PyMuPDF: pip install pymupdf --user --break-system-packages
"""

import fitz, hashlib, io, json, os, re, sys
from collections import defaultdict
from PIL import Image

BASE    = os.path.dirname(os.path.abspath(__file__))
QUIZ    = os.path.join(BASE, "quiz")
DATA    = os.path.join(BASE, "data")
IMG_DIR = os.path.join(DATA, "images")

CN_NUM = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
# tolerant: 圖 ( 三 ) / 圖(一 ) / 圖(圖二) all match
_FIG_RE = re.compile(r'圖\s*[（(]\s*(?:圖)?\s*([一二三四五六七八九十\d]+)\s*[）)]')
# question number at the start of a line; tolerate leading junk like the stray
# macron "ˉ" some exam PDFs prepend (e.g. "ˉ23.")
_Q_RE   = re.compile(r'^\D{0,2}(\d{1,2})[\.．、]')

MIN_AREA = 5000   # px²; below this is decorative
LETTERS  = ['A', 'B', 'C', 'D', 'E', 'F']

EXAMS = [
    (114, "neike",   "內科"),
    (114, "tonglun", "通論"),
    (113, "neike",   "內科"),
    (113, "tonglun", "通論"),
    (112, "neike",   "內科"),
    (112, "tonglun", "通論"),
    (111, "neike",   "內科"),
    (111, "tonglun", "通論"),
    (110, "neike",   "內科"),
    (110, "tonglun", "通論"),
    (109, "neike",   "內科"),
    (109, "tonglun", "通論"),
]


def fig_nums_in(text):
    return sorted({CN_NUM.get(m.group(1), int(m.group(1)) if m.group(1).isdigit() else 0)
                   for m in _FIG_RE.finditer(text)} - {0})


def options_are_images(q):
    """True when the A/B/C/D options are placeholders for images (empty or just
    the option letter), i.e. the image IS the option."""
    vals = list(q.get("options", {}).values())
    if not vals:
        return False
    blank = sum(1 for v in vals if len(v.strip()) <= 1)
    return blank >= 2 and blank >= len(vals) - 1


def collect_placements(doc):
    """Return (events, n_pages). Events: dicts with page, y, kind, payload.
    kind 'label' -> qnum ; kind 'image' -> {'bytes','ext','w','h','digest'}."""
    n_pages = len(doc)

    # background = same image bytes drawn on >= half the pages
    digest_pages = defaultdict(set)
    raw = []  # (page, rect.y0, rect.x0, xref, digest, info)
    for pno in range(n_pages):
        page = doc[pno]
        for xref in {im[0] for im in page.get_images()}:
            info = doc.extract_image(xref)
            digest = hashlib.md5(info["image"]).hexdigest()
            for rect in page.get_image_rects(xref):
                digest_pages[digest].add(pno)
                raw.append((pno, rect.y0, rect.x0, xref, digest, info))
    bg = {d for d, pgs in digest_pages.items() if len(pgs) >= max(2, n_pages // 2)}

    events = []
    # question-number labels: words like "23." sitting at the left margin.
    # Numbers only ever increase 1..80, which filters spurious in-text numbers.
    last_q = 0
    for pno in range(n_pages):
        if pno == 0:                    # page 1 = instructions
            continue
        words = doc[pno].get_text("words")
        if not words:
            continue
        left = min(w[0] for w in words)
        cand = []
        for x0, y0, x1, y1, wd, *_ in words:
            m = _Q_RE.match(wd)
            if m and x0 <= left + 8:
                cand.append((y0, int(m.group(1))))
        for y0, num in sorted(cand):
            if last_q < num <= 80:
                last_q = num
                events.append({"page": pno, "y": y0, "kind": "label", "q": num})

    for pno, y0, x0, xref, digest, info in raw:
        if pno == 0 or digest in bg:
            continue
        if info["width"] * info["height"] < MIN_AREA:
            continue
        events.append({"page": pno, "y": y0, "x": x0, "kind": "image",
                       "img": {"bytes": info["image"], "ext": info["ext"],
                               "w": info["width"], "h": info["height"]}})

    events.sort(key=lambda e: (e["page"], e["y"], e.get("x", 0)))
    return events


def assign(events):
    """Walk reading order; attach each image to the current question."""
    owned = defaultdict(list)
    cur = None
    for e in events:
        if e["kind"] == "label":
            cur = e["q"]
        elif cur is not None:
            owned[cur].append(e["img"])
    return owned


def process_exam(roc_year, id_suffix, subject_cn, apply):
    exam_id   = f"{roc_year}_{id_suffix}"
    pdf_path  = os.path.join(QUIZ, f"{roc_year}年度_專科護理師_{subject_cn}_試題.pdf")
    json_file = os.path.join(DATA, f"{exam_id}.json")
    if not os.path.exists(pdf_path):
        print(f"{exam_id}: PDF missing, skip"); return

    with open(json_file) as f:
        data = json.load(f)
    qmap = {q["num"]: q for q in data["questions"]}

    doc = fitz.open(pdf_path)
    owned = assign(collect_placements(doc))

    saved = []
    for q in data["questions"]:
        q.pop("image", None)
        q["has_image"] = False
        q.pop("option_images", None)

    for qnum, imgs in sorted(owned.items()):
        q = qmap.get(qnum)
        if q is None:
            continue
        if options_are_images(q):                  # the images ARE the options
            opt = {}
            for letter, im in zip(LETTERS, imgs):
                fn = f"{exam_id}_q{qnum}_{letter}.jpg"
                opt[letter] = "data/images/" + fn
                saved.append((fn, im))
            q["has_image"] = True
            q["option_images"] = opt
            kind = "options"
        else:                                      # 圖(N) / 附圖 / 如下 figure(s)
            paths = []
            for i, im in enumerate(imgs, 1):
                fn = f"{exam_id}_q{qnum}_{i}.jpg"
                paths.append((fn, im))
            q["has_image"] = True
            q["image"] = ("data/images/" + paths[0][0] if len(paths) == 1
                          else ["data/images/" + p for p, _ in paths])
            saved += paths
            kind = "figure"
        sizes = ", ".join("{}x{}".format(im["w"], im["h"]) for im in imgs)
        print(f"  Q{qnum:<2} {kind:<7} x{len(imgs)}  [{sizes}]")

    print(f"{exam_id}: {len(owned)} image-questions, {len(saved)} images")

    if not apply:
        return

    os.makedirs(IMG_DIR, exist_ok=True)
    # clear this exam's old images
    for old in os.listdir(IMG_DIR):
        if old.startswith(exam_id + "_"):
            os.remove(os.path.join(IMG_DIR, old))
    for fn, im in saved:
        pil = Image.open(io.BytesIO(im["bytes"]))
        if pil.mode not in ("RGB", "L"):
            pil = pil.convert("RGB")
        pil.save(os.path.join(IMG_DIR, fn), "JPEG", quality=90)
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    apply = "--apply" in sys.argv
    for args in EXAMS:
        process_exam(*args, apply=apply)
    print("\n" + ("WROTE files." if apply else "DRY RUN (use --apply to write)."))


if __name__ == "__main__":
    main()

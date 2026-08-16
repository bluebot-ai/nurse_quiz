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
TILE_GAP = 3      # pt; images closer than this are tiles of one figure

EXAMS = [
    # (roc_year, id_suffix, subject_cn[, file_prefix, exam_id]) — see parse_pdfs.EXAMS
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
    (108, "neike",   "內科", "108年度第二次", "108_2_neike"),
    (108, "tonglun", "通論", "108年度第二次", "108_2_tonglun"),
    (108, "neike",   "內科", "108年度第一次", "108_1_neike"),
    (108, "tonglun", "通論", "108年度第一次", "108_1_tonglun"),
    (107, "neike",   "內科"),
    (107, "tonglun", "通論"),
    (106, "neike",   "內科"),
    (106, "tonglun", "通論"),
    (105, "neike",   "內科"),
    (105, "tonglun", "通論"),
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
                raw.append((pno, rect.y0, rect.x0, rect, xref, digest, info))
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

    for pno, y0, x0, rect, xref, digest, info in raw:
        if pno == 0 or digest in bg:
            continue
        if info["width"] * info["height"] < MIN_AREA:
            continue
        events.append({"page": pno, "y": y0, "x": x0, "kind": "image",
                       "rect": rect,
                       "img": {"bytes": info["image"], "ext": info["ext"],
                               "w": info["width"], "h": info["height"]}})

    events.sort(key=lambda e: (e["page"], e["y"], e.get("x", 0)))
    return events


def assign(events):
    """Walk reading order; attach each image event to the current question."""
    owned = defaultdict(list)
    cur = None
    for e in events:
        if e["kind"] == "label":
            cur = e["q"]
        elif cur is not None:
            owned[cur].append(e)
    return owned


def stitch_tiles(doc, items):
    """Merge images that are tiles of a single figure.

    Some PDFs slice one figure (a long ECG strip, an anatomical diagram) into a
    grid of touching images.  Extracting those separately shows the reader a
    stack of fragments, so any group of images whose boxes touch (gap < TILE_GAP)
    is pasted back together on one canvas, positioned by their page rectangles.
    Figures that merely sit near each other — 105 內科 Q77's five separate ECGs
    — keep their real gaps and stay separate.

    The tiles are composited from the embedded image bytes rather than
    re-rendered off the page, so the page's 「僅供參考」浮水印 stays out of the
    picture.
    """
    groups = []          # [(page, fitz.Rect, [item, ...]), ...]
    for it in items:
        rect = it.get("rect")
        if rect is None:
            groups.append((it["page"], None, [it]))
            continue
        grown = fitz.Rect(rect) + (-TILE_GAP, -TILE_GAP, TILE_GAP, TILE_GAP)
        for i, (pno, box, members) in enumerate(groups):
            if box is not None and pno == it["page"] and grown.intersects(box):
                groups[i] = (pno, box | rect, members + [it])
                break
        else:
            groups.append((it["page"], fitz.Rect(rect), [it]))

    # a tile can bridge two groups that were started apart, so keep merging
    merged = True
    while merged:
        merged = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                (p1, b1, m1), (p2, b2, m2) = groups[i], groups[j]
                if b1 is None or b2 is None or p1 != p2:
                    continue
                if (b1 + (-TILE_GAP, -TILE_GAP, TILE_GAP, TILE_GAP)).intersects(b2):
                    groups[i] = (p1, b1 | b2, m1 + m2)
                    groups.pop(j)
                    merged = True
                    break
            if merged:
                break

    out = []
    for pno, box, members in groups:
        if len(members) == 1:
            out.append(members[0]["img"])
            continue
        # pixels per point of the sharpest tile, so we don't lose resolution
        scale = max(m["img"]["w"] / max(fitz.Rect(m["rect"]).width, 1) for m in members)
        canvas = Image.new("RGB",
                           (max(1, round(box.width * scale)),
                            max(1, round(box.height * scale))), "white")
        for m in members:
            r = fitz.Rect(m["rect"])
            tile = Image.open(io.BytesIO(m["img"]["bytes"]))
            if tile.mode not in ("RGB", "L"):
                tile = tile.convert("RGB")
            size = (max(1, round(r.width * scale)), max(1, round(r.height * scale)))
            canvas.paste(tile.resize(size, Image.LANCZOS),
                         (round((r.x0 - box.x0) * scale),
                          round((r.y0 - box.y0) * scale)))
        buf = io.BytesIO()
        canvas.save(buf, "PNG")
        out.append({"bytes": buf.getvalue(), "ext": "png",
                    "w": canvas.width, "h": canvas.height, "tiles": len(members)})
    return out


def process_exam(roc_year, id_suffix, subject_cn, file_prefix=None, exam_id=None,
                 apply=False):
    exam_id   = exam_id or f"{roc_year}_{id_suffix}"
    prefix    = file_prefix or f"{roc_year}年度"
    pdf_path  = os.path.join(QUIZ, f"{prefix}_專科護理師_{subject_cn}_試題.pdf")
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

    for qnum, items in sorted(owned.items()):
        q = qmap.get(qnum)
        if q is None:
            continue
        # A/B/C/D pictures sit side by side and must stay four separate images;
        # only 題幹 figures may be tiles of one picture.
        imgs = ([it["img"] for it in items] if options_are_images(q)
                else stitch_tiles(doc, items))
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
    only  = {a for a in sys.argv[1:] if not a.startswith("--")}
    for args in EXAMS:
        exam_id = args[4] if len(args) > 4 else f"{args[0]}_{args[1]}"
        if only and exam_id not in only:
            continue
        process_exam(*args, apply=apply)
    print("\n" + ("WROTE files." if apply else "DRY RUN (use --apply to write)."))


if __name__ == "__main__":
    main()

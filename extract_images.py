#!/usr/bin/env python3
"""Extract question images from exam PDFs and update JSON data files."""

import pdfplumber, hashlib, io, json, os, re
from collections import Counter
from PIL import Image

BASE     = os.path.dirname(os.path.abspath(__file__))
QUIZ     = os.path.join(BASE, "quiz")
DATA     = os.path.join(BASE, "data")
IMG_DIR  = os.path.join(DATA, "images")

# Chinese numeral → int (圖(一) → 1, etc.)
CN_NUM = {'一':1,'二':2,'三':3,'四':4,'五':5,
          '六':6,'七':7,'八':8,'九':9,'十':10}
_FIG_RE = re.compile(r'圖[（(]([一二三四五六七八九十\d]+)[）)]')

MIN_AREA      = 8000   # skip tiny decoratives (< ~90×90)
SKIP_PAGE_ONE = True   # page 1 is always instructions

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


def cn_to_int(s):
    if s.isdigit():
        return int(s)
    return CN_NUM.get(s, 0)


def fig_nums_in(text):
    """Return sorted list of figure numbers referenced in text."""
    return sorted({cn_to_int(m.group(1)) for m in _FIG_RE.finditer(text) if cn_to_int(m.group(1))})


def extract_real_images(pdf_path):
    """Return list of (page_num, pil_image) for real question images, in reading order."""
    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        hash_count = Counter()
        all_entries = []

        for pg_idx, page in enumerate(pdf.pages):
            page_num = pg_idx + 1
            for img in page.images:
                data = img['stream'].get_data()
                h = hashlib.md5(data).hexdigest()
                hash_count[h] += 1
                w, ht = img.get('srcsize', (0, 0))
                all_entries.append((page_num, h, data, w, ht))

    # Background = appears on >= half the pages
    bg = {h for h, c in hash_count.items() if c >= max(2, n_pages // 2)}

    results = []
    for page_num, h, data, w, ht in all_entries:
        if h in bg:                        continue  # background
        if SKIP_PAGE_ONE and page_num == 1: continue  # instructions page
        if w * ht < MIN_AREA:               continue  # too small

        # Try as JPEG first
        pil = None
        try:
            pil = Image.open(io.BytesIO(data))
            pil.load()
        except Exception:
            pil = None

        # Fall back to raw RGB
        if pil is None:
            try:
                pil = Image.frombytes('RGB', (w, ht), data)
            except Exception:
                continue

        results.append((page_num, pil))

    return results


def save_image(pil, path):
    """Save PIL image; convert mode if needed."""
    if pil.mode not in ('RGB', 'L', 'RGBA'):
        pil = pil.convert('RGB')
    pil.save(path, 'JPEG', quality=90)


def process_exam(roc_year, id_suffix, subject_cn):
    exam_id  = f"{roc_year}_{id_suffix}"
    q_file   = os.path.join(QUIZ, f"{roc_year}年度_專科護理師_{subject_cn}_試題.pdf")
    json_file = os.path.join(DATA, f"{exam_id}.json")

    with open(json_file) as f:
        data = json.load(f)

    # Collect image questions and figure numbers they reference
    img_questions = {}   # {q_num: [fig_num, ...]}
    for q in data['questions']:
        figs = fig_nums_in(q['stem'])
        if not figs:
            # also check options
            for v in q['options'].values():
                figs += fig_nums_in(v)
            figs = sorted(set(figs))
        if figs:
            img_questions[q['num']] = figs
            q['has_image'] = True
        elif q['has_image']:
            # has_image was set by text scan but we found no specific figure ref
            img_questions[q['num']] = []

    if not img_questions:
        print(f"{exam_id}: no image questions")
        return

    # Extract real images from PDF
    real_imgs = extract_real_images(q_file)
    print(f"{exam_id}: {len(img_questions)} img-Qs, {len(real_imgs)} real images extracted")

    if not real_imgs:
        print(f"  WARNING: no images extracted!")
        return

    # Save images and build figure→path map
    os.makedirs(IMG_DIR, exist_ok=True)
    fig_to_path = {}
    for i, (page_num, pil) in enumerate(real_imgs, start=1):
        fname = f"{exam_id}_fig{i}.jpg"
        fpath = os.path.join(IMG_DIR, fname)
        save_image(pil, fpath)
        fig_to_path[i] = f"data/images/{fname}"
        print(f"  fig{i} (page {page_num}) → {fname} {pil.size}")

    # Update JSON: assign image paths to questions
    for q in data['questions']:
        if q['num'] not in img_questions:
            continue
        figs = img_questions[q['num']]
        if figs:
            # Use the first referenced figure number; collect all
            paths = [fig_to_path[n] for n in figs if n in fig_to_path]
            q['image'] = paths[0] if len(paths) == 1 else paths
        else:
            # has_image but no specific fig ref; assign the next unused image
            pass  # leave as has_image: true

    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    for args in EXAMS:
        process_exam(*args)


if __name__ == '__main__':
    main()

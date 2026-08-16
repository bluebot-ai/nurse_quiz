#!/usr/bin/env python3
"""Parse nursing exam PDFs into JSON data files.

    python3 parse_pdfs.py                # 重新解析全部（會覆蓋手動修正與圖片欄位！）
    python3 parse_pdfs.py 105_neike ...  # 只重新解析指定的考卷，其餘沿用現有資料
"""

import pdfplumber, re, json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
QUIZ = os.path.join(BASE, "quiz")
DATA = os.path.join(BASE, "data")

# Allow optional spaces inside parens: (A) or ( A ) or (A )
_OPT_RE   = re.compile(r'\(\s*([A-D])\s*\)\s*(.*?)(?=\s*\(\s*[A-D]\s*\)|$)')
# Question number at line start. The (?!\d) guard stops a wrapped line that
# begins with a decimal ("39.5C，白血球…"、"10.1mg/dL") being read as a題號.
_Q_RE     = re.compile(r'^(\d+)\.(?!\d)\s*(.+)')
_INSTR_RE = re.compile(
    r'^(?:'
    r'第\d+頁|共\d+頁|'
    r'(?:內科|外科|家庭科|兒科|婦產科|精神科|通論|內科\s*、).*專科護理|'
    r'注意：考試開始|'
    r'入場證號碼：|'
    r'考試開始鈴|'
    r'【注\s*意\s*事\s*項|'
    r'以下空白'
    r')'
)
_PREAMBLE_RE = re.compile(
    r'^\d+[\.\s]*(請核對|請檢查|本試卷|有關數值|本試卷空白|請在試卷|選一個最適當)'
)

# ─── answer key parsers ───────────────────────────────────────────────────────

def _clean_answer_token(tok):
    """Clean a single answer token; normalize multi-select to contiguous letters."""
    if '送分' in tok:
        return '送分'
    # Keep only A-D (and the Chinese separator 、 which we then drop)
    clean = re.sub(r'[^A-Da-d、]', '', tok).upper()
    # Remove the separator so "B、D" → "BD"
    clean = clean.replace('、', '')
    return clean


def parse_answers(pdf_path):
    """Parse answer key PDF; handles both column-table (110+) and grid (109) formats."""
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)

    answers = {}

    # ── Format A: column-table  e.g. "1 C  11 A  21 C ..."  (one number + one answer per pair)
    # Also handles multi-select answers like "43 BC" / "39 C、D" and special "46 送分"
    # Try matching pairs (num, answer) on same line
    table_matches = re.findall(
        r'\b(\d+)\s+(送分|[A-D]{1,4}(?:\s*、\s*[A-D]{1,4})*)(?![A-Za-z])', text)
    if table_matches:
        for num_s, ans in table_matches:
            answers[int(num_s)] = _clean_answer_token(ans)
        # Verify at least half of Q1-80 are covered
        if len(answers) >= 40:
            return answers

    # ── Format B: grid (109 style)
    # Numbers row: "1 2 3 4 5 6 7 8 9 10"
    # Answers row: "B、D A 送分 D D C D C C D"
    # Watermark single chars (標準答案) may appear as standalone lines between rows
    answers = {}
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    def is_watermark_line(s):
        return len(s) <= 2 and all('一' <= c <= '鿿' for c in s)

    i = 0
    while i < len(lines):
        line = lines[i]
        # Detect a "numbers only" row
        clean_line = re.sub(r'[^\d\s]', '', line).strip()
        nums_in_line = clean_line.split()
        if (nums_in_line and
                all(n.isdigit() for n in nums_in_line) and
                len(nums_in_line) >= 5):
            nums = list(map(int, nums_in_line))
            # Look ahead, skipping watermark single-char lines
            j = i + 1
            while j < len(lines) and is_watermark_line(lines[j]):
                j += 1
            if j < len(lines):
                ans_line = lines[j]
                tokens = ans_line.split()
                cleaned = [_clean_answer_token(t) for t in tokens]
                for num, ans in zip(nums, cleaned):
                    if ans:
                        answers[num] = ans
                i = j + 1
                continue
        i += 1

    return answers


# ─── question parser ──────────────────────────────────────────────────────────

_WATERMARK_SIZE = 40          # 「公告試題」「僅供參考」斜向浮水印是 100pt 彩色字
_WHITE = {(1,), (1, 1, 1), (1, 1, 1, 0)}


def _clean_page(page):
    """Strip the artefacts that pollute these PDFs' text layer:

    * 假粗體：同一個字重複描繪兩次（105 內科 p9-p11 「林先生生 66 歲」）
    * 隱形浮水印：白色的「的」「a」字元散在內文中（105、106 全篇）
    * 斜向大字浮水印：紅色 100pt 的「公告試題」「僅供參考」
    """
    page = page.dedupe_chars(tolerance=1)

    def keep(obj):
        if obj.get("object_type") != "char":
            return True
        if (obj.get("size") or 0) >= _WATERMARK_SIZE:
            return False
        color = obj.get("non_stroking_color")
        if color is not None and tuple(color) in _WHITE:
            return False
        return True

    return page.filter(keep)


def parse_questions(pdf_path):
    lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            lines.extend((_clean_page(page).extract_text() or "").split('\n'))

    questions   = []
    current_q   = None
    last_opt    = None
    in_preamble = True
    last_num    = 0     # 題號只會遞增 1..80，用來擋掉內文中的假題號

    def flush():
        nonlocal current_q
        if current_q and current_q.get('stem') and current_q['options']:
            questions.append(current_q)
        current_q = None

    for raw in lines:
        line = raw.strip()
        if not line or line in ('ˉ', '□□□□□□□□'):
            continue
        if _INSTR_RE.match(line):
            continue

        qm = _Q_RE.match(line)
        if qm and (in_preamble or last_num < int(qm.group(1)) <= 80):
            num  = int(qm.group(1))
            stem = qm.group(2).strip()
            if in_preamble and _PREAMBLE_RE.match(line):
                continue
            flush()
            in_preamble = False
            last_num = num
            current_q = {
                'num': num, 'stem': stem,
                'options': {}, 'answer': None,
                'is_multi': False, 'has_image': False,
            }
            last_opt = None
            continue

        if in_preamble or current_q is None:
            continue

        if re.search(r'圖[（(][一二三四五六七八九十\d]+[）)]', line):
            current_q['has_image'] = True

        opts = _OPT_RE.findall(line)
        if opts:
            for key, val in opts:
                val = val.strip()
                # Always register the key (even empty), so continuation works
                current_q['options'][key] = val if val else current_q['options'].get(key, '')
            last_opt = opts[-1][0]
            continue

        if not current_q['options']:
            current_q['stem'] += ' ' + line
        elif last_opt and last_opt in current_q['options']:
            current_q['options'][last_opt] += ' ' + line

    flush()
    return questions


# ─── exam manifest ────────────────────────────────────────────────────────────

EXAMS = [
    # (roc_year, id_suffix, subject_cn, subject_label, subtitle[, file_prefix, exam_id])
    # file_prefix / exam_id are only needed when a year has more than one sitting
    # (108 年分第一次、第二次筆試)．
    (114, "neike",   "內科", "進階專科護理", "內科"),
    (114, "tonglun", "通論", "專科護理通論", "通論"),
    (113, "neike",   "內科", "進階專科護理", "內科"),
    (113, "tonglun", "通論", "專科護理通論", "通論"),
    (112, "neike",   "內科", "進階專科護理", "內科"),
    (112, "tonglun", "通論", "專科護理通論", "通論"),
    (111, "neike",   "內科", "進階專科護理", "內科"),
    (111, "tonglun", "通論", "專科護理通論", "通論"),
    (110, "neike",   "內科", "進階專科護理", "內科"),
    (110, "tonglun", "通論", "專科護理通論", "通論"),
    (109, "neike",   "內科", "進階專科護理", "內科"),
    (109, "tonglun", "通論", "專科護理通論", "通論"),
    (108, "neike",   "內科", "進階專科護理", "內科（第二次）",
     "108年度第二次", "108_2_neike"),
    (108, "tonglun", "通論", "專科護理通論", "通論（第二次）",
     "108年度第二次", "108_2_tonglun"),
    (108, "neike",   "內科", "進階專科護理", "內科（第一次）",
     "108年度第一次", "108_1_neike"),
    (108, "tonglun", "通論", "專科護理通論", "通論（第一次）",
     "108年度第一次", "108_1_tonglun"),
    (107, "neike",   "內科", "進階專科護理", "內科"),
    (107, "tonglun", "通論", "專科護理通論", "通論"),
    (106, "neike",   "內科", "進階專科護理", "內科"),
    (106, "tonglun", "通論", "專科護理通論", "通論"),
    (105, "neike",   "內科", "進階專科護理", "內科"),
    (105, "tonglun", "通論", "專科護理通論", "通論"),
]

ROC_TO_AD = {105: 2016, 106: 2017, 107: 2018, 108: 2019,
             109: 2020, 110: 2021, 111: 2022, 112: 2023, 113: 2024, 114: 2025}


def process_exam(roc_year, id_suffix, subject_cn, subject_label, subtitle_label,
                 file_prefix=None, exam_id=None):
    exam_id  = exam_id or f"{roc_year}_{id_suffix}"
    prefix   = file_prefix or f"{roc_year}年度"
    q_file   = os.path.join(QUIZ, f"{prefix}_專科護理師_{subject_cn}_試題.pdf")
    a_file   = os.path.join(QUIZ, f"{prefix}_專科護理師_{subject_cn}_標準答案.pdf")
    out_file = os.path.join(DATA, f"{exam_id}.json")

    print(f"Processing {exam_id} ...", end=" ", flush=True)

    answers   = parse_answers(a_file)
    questions = parse_questions(q_file)

    for q in questions:
        ans = answers.get(q['num'])
        q['answer']   = ans
        q['is_multi'] = bool(ans and len(ans) > 1 and ans != '送分')

    ad_year = ROC_TO_AD[roc_year]
    data = {
        "id":       exam_id,
        "title":    f"{roc_year}年度 {subtitle_label}",
        "subtitle": subject_label,
        "year":     roc_year,
        "ad_year":  ad_year,
        "subject":  subject_cn,
        "total":    len(questions),
        "questions": questions,
    }

    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    missing     = [q['num'] for q in questions if not q['answer']]
    incomplete  = [q['num'] for q in questions if len(q['options']) < 4]
    multi       = [q['num'] for q in questions if q['is_multi']]
    free        = [q['num'] for q in questions if q['answer'] == '送分']
    print(
        f"{len(questions)} Qs"
        + (f" | MISSING_ANS={missing}" if missing else "")
        + (f" | INCOMPLETE_OPTS={incomplete}" if incomplete else "")
        + (f" | multi={multi}" if multi else "")
        + (f" | free={free}" if free else "")
    )
    return data


def exam_id_of(args):
    """The exam id for an EXAMS entry (explicit 7th field, else year_suffix)."""
    return args[6] if len(args) > 6 else f"{args[0]}_{args[1]}"


def main():
    os.makedirs(DATA, exist_ok=True)
    only = set(sys.argv[1:])
    if only:
        print("Only re-parsing:", ", ".join(sorted(only)))

    manifest_path = os.path.join(DATA, "exams.json")
    existing = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding='utf-8') as f:
            existing = {e["id"]: e for e in json.load(f).get("exams", [])}

    manifest_exams = []
    for args in EXAMS:
        exam_id = exam_id_of(args)
        if only and exam_id not in only:
            # keep the current manifest entry untouched
            if exam_id in existing:
                manifest_exams.append(existing[exam_id])
            continue
        data = process_exam(*args)
        manifest_exams.append({
            "id":       data["id"],
            "title":    data["title"],
            "subtitle": data["subtitle"],
            "year":     data["year"],
            "ad_year":  data["ad_year"],
            "subject":  data["subject"],
            "total":    data["total"],
            "file":     f"data/{data['id']}.json",
        })

    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump({"exams": manifest_exams}, f, ensure_ascii=False, indent=2)

    print(f"\nWrote data/exams.json with {len(manifest_exams)} exams.")


if __name__ == "__main__":
    main()

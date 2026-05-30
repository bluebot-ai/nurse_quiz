#!/usr/bin/env python3
"""Parse nursing exam PDFs into JSON data files."""

import pdfplumber, re, json, os

BASE = os.path.dirname(os.path.abspath(__file__))
QUIZ = os.path.join(BASE, "quiz")
DATA = os.path.join(BASE, "data")

# Allow optional spaces inside parens: (A) or ( A ) or (A )
_OPT_RE   = re.compile(r'\(\s*([A-D])\s*\)\s*(.*?)(?=\s*\(\s*[A-D]\s*\)|$)')
_Q_RE     = re.compile(r'^(\d+)\.\s*(.+)')  # allow zero or more spaces after period
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
    # Also handles multi-select answers like "43 BC" and special "46 送分"
    # Try matching pairs (num, answer) on same line
    table_matches = re.findall(r'\b(\d+)\s+(送分|[A-D]{1,4})\b', text)
    if table_matches:
        for num_s, ans in table_matches:
            answers[int(num_s)] = ans
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

def parse_questions(pdf_path):
    lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            lines.extend((page.extract_text() or "").split('\n'))

    questions   = []
    current_q   = None
    last_opt    = None
    in_preamble = True

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
        if qm:
            num  = int(qm.group(1))
            stem = qm.group(2).strip()
            if in_preamble and _PREAMBLE_RE.match(line):
                continue
            flush()
            in_preamble = False
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
    # (roc_year, id_suffix, subject_cn, subject_label, subtitle)
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
]

ROC_TO_AD = {109: 2020, 110: 2021, 111: 2022, 112: 2023, 113: 2024, 114: 2025}


def process_exam(roc_year, id_suffix, subject_cn, subject_label, subtitle_label):
    exam_id  = f"{roc_year}_{id_suffix}"
    q_file   = os.path.join(QUIZ, f"{roc_year}年度_專科護理師_{subject_cn}_試題.pdf")
    a_file   = os.path.join(QUIZ, f"{roc_year}年度_專科護理師_{subject_cn}_標準答案.pdf")
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


def main():
    os.makedirs(DATA, exist_ok=True)
    manifest_exams = []

    for args in EXAMS:
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

    with open(os.path.join(DATA, "exams.json"), 'w', encoding='utf-8') as f:
        json.dump({"exams": manifest_exams}, f, ensure_ascii=False, indent=2)

    print(f"\nWrote data/exams.json with {len(manifest_exams)} exams.")


if __name__ == "__main__":
    main()

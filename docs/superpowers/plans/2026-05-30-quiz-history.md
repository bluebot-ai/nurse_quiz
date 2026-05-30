# Quiz History & Score Trends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-exam answer history and score trend display to exam cards using localStorage, with no backend.

**Architecture:** Two new helper functions (`loadHistory` / `saveHistory`) manage a localStorage key per exam (`quiz_history_{examId}`). `finishExam()` saves results after scoring. `buildCard()` reads history and injects a history block below the start button.

**Tech Stack:** Vanilla JS, localStorage, CSS custom properties (already in use)

---

### Task 1: Add localStorage helper functions

**Files:**
- Modify: `app.js` (append to helpers section near bottom, before `arraysEqual`)

- [ ] **Step 1: Verify localStorage works in the dev server**

  Open `http://localhost:8080` in a browser, open DevTools → Console, run:
  ```js
  localStorage.setItem('test', '1'); localStorage.getItem('test');
  ```
  Expected: `"1"` — confirms localStorage is available.

- [ ] **Step 2: Add `loadHistory` and `saveHistory` to `app.js`**

  In `app.js`, find the `// ── helpers ──` comment block. Add the two functions immediately before the `arraysEqual` function:

  ```js
  function loadHistory(examId) {
    try {
      return JSON.parse(localStorage.getItem(`quiz_history_${examId}`)) || [];
    } catch (e) {
      return [];
    }
  }

  function saveHistory(examId, result) {
    const history = loadHistory(examId);
    history.unshift(result);
    if (history.length > 5) history.length = 5;
    try {
      localStorage.setItem(`quiz_history_${examId}`, JSON.stringify(history));
    } catch (e) {}
  }
  ```

- [ ] **Step 3: Verify functions work in browser console**

  Reload the page, open DevTools → Console, run:
  ```js
  saveHistory('test_exam', { date: '2026-05-30', score: 75, correct: 60, wrong: 15, skipped: 5, wrongNums: [3, 7] });
  loadHistory('test_exam');
  ```
  Expected:
  ```js
  [{ date: '2026-05-30', score: 75, correct: 60, wrong: 15, skipped: 5, wrongNums: [3, 7] }]
  ```

- [ ] **Step 4: Verify max 5 entries cap**

  In DevTools console:
  ```js
  localStorage.removeItem('quiz_history_cap_test');
  for (let i = 1; i <= 7; i++) saveHistory('cap_test', { date: '2026-05-30', score: i * 10, correct: i, wrong: 0, skipped: 0, wrongNums: [] });
  loadHistory('cap_test').length;
  ```
  Expected: `5` (not 7)

- [ ] **Step 5: Clean up test data from localStorage**

  ```js
  localStorage.removeItem('quiz_history_test_exam');
  localStorage.removeItem('quiz_history_cap_test');
  ```

- [ ] **Step 6: Commit**

  ```bash
  git add app.js
  git commit -m "feat: add loadHistory and saveHistory localStorage helpers"
  ```

---

### Task 2: Save history when finishing an exam

**Files:**
- Modify: `app.js` — `finishExam()` function (lines ~303–374)

- [ ] **Step 1: Add `wrongNums` collection to the scoring loop in `finishExam()`**

  Find the loop in `finishExam()`:
  ```js
  let correct = 0, wrong = 0, skipped = 0;

  for (const q of qs) {
    const num = q.num;
    if (!state.confirmed[num]) { skipped++; continue; }
    if (q.answer === '送分')   { correct++; continue; }
    if (state.skipped[num])    { skipped++; continue; }

    const userSel     = state.userAnswers[num] || [];
    const correctKeys = [...q.answer];
    if (arraysEqual(userSel.sort(), correctKeys.sort())) correct++;
    else wrong++;
  }
  ```

  Replace it with:
  ```js
  let correct = 0, wrong = 0, skipped = 0;
  const wrongNums = [];

  for (const q of qs) {
    const num = q.num;
    if (!state.confirmed[num]) { skipped++; continue; }
    if (q.answer === '送分')   { correct++; continue; }
    if (state.skipped[num])    { skipped++; continue; }

    const userSel     = state.userAnswers[num] || [];
    const correctKeys = [...q.answer];
    if (arraysEqual(userSel.sort(), correctKeys.sort())) correct++;
    else { wrong++; wrongNums.push(num); }
  }
  ```

- [ ] **Step 2: Call `saveHistory` after calculating `pct`**

  Find these two lines in `finishExam()`:
  ```js
  const total  = qs.length;
  const pct    = Math.round((correct / total) * 100);
  ```

  Add the `saveHistory` call immediately after them:
  ```js
  const total  = qs.length;
  const pct    = Math.round((correct / total) * 100);
  saveHistory(state.examId, {
    date: new Date().toISOString().slice(0, 10),
    score: pct,
    correct,
    wrong,
    skipped,
    wrongNums,
  });
  ```

- [ ] **Step 3: Verify history is saved after completing an exam**

  1. Start the dev server (`python3 -m http.server 8080`) and open `http://localhost:8080`
  2. Start any exam, answer a few questions, click 「結束測驗」→ 確定
  3. In DevTools Console, run (replace `114_neike` with the exam id you used):
     ```js
     loadHistory('114_neike')
     ```
  Expected: array with 1 entry containing `date`, `score`, `correct`, `wrong`, `skipped`, `wrongNums`.

- [ ] **Step 4: Commit**

  ```bash
  git add app.js
  git commit -m "feat: save exam result to localStorage history on finish"
  ```

---

### Task 3: Render history block on exam cards

**Files:**
- Modify: `app.js` — `buildCard()` function (lines ~51–70)

- [ ] **Step 1: Add history block rendering at the end of `buildCard()`**

  Find the end of `buildCard()`:
  ```js
    btn.onclick = () => startExam('${exam.file}', '${exam.id}', '${shuffleId}')">
        開始測驗
      </button>`;
    return card;
  }
  ```

  Replace with:
  ```js
    btn.onclick = () => startExam('${exam.file}', '${exam.id}', '${shuffleId}')">
        開始測驗
      </button>`;

    const history = loadHistory(exam.id);
    if (history.length > 0) {
      const last = history[0];
      const dots = history.slice().reverse().map(h =>
        `<span class="trend-dot ${h.score >= 60 ? 'green' : 'red'}">${h.score}%</span>`
      ).join('');
      const histEl = document.createElement('div');
      histEl.className = 'card-history';
      histEl.innerHTML = `
        <div class="history-summary">上次 <strong>${last.score}%</strong>・共練習 <strong>${history.length}</strong> 次</div>
        <div class="history-trend">${dots}</div>`;
      card.appendChild(histEl);
    }

    return card;
  }
  ```

- [ ] **Step 2: Verify the history block appears on a card that has history**

  1. Reload `http://localhost:8080`
  2. The exam you completed in Task 2 should now show a history block on its card with score and trend dot.
  3. Exams with no history should show no history block.

- [ ] **Step 3: Complete a second run on the same exam and verify trend updates**

  1. Start the same exam again, finish it, return home.
  2. Card should now show 「共練習 2 次」and 2 trend dots ordered oldest→newest.

- [ ] **Step 4: Commit**

  ```bash
  git add app.js
  git commit -m "feat: render exam history block with score trend on home cards"
  ```

---

### Task 4: Style the history block and trend dots

**Files:**
- Modify: `style.css` (append before `@media` block at bottom)

- [ ] **Step 1: Add styles to `style.css`**

  Find the `@media(max-width:600px)` block at the bottom of `style.css`. Insert the following immediately before it:

  ```css
  /* ── CARD HISTORY ── */
  .card-history{border-top:1px solid var(--border);margin-top:14px;padding-top:12px;
    font-size:13px;color:var(--sub)}
  .history-summary{margin-bottom:6px}
  .history-summary strong{color:var(--text)}
  .history-trend{display:flex;gap:5px;flex-wrap:wrap}
  .trend-dot{display:inline-flex;align-items:center;justify-content:center;
    padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700}
  .trend-dot.green{background:#dcfce7;color:#15803d}
  .trend-dot.red{background:#fee2e2;color:#b91c1c}
  ```

- [ ] **Step 2: Visual check**

  Reload `http://localhost:8080`. Verify:
  - History block has a visible separator line above it
  - Score text is in the card's main text color (not grey)
  - Trend dots are pill-shaped, green for ≥60%, red for <60%
  - Card layout is not broken on mobile (resize to <600px)

- [ ] **Step 3: Commit**

  ```bash
  git add style.css
  git commit -m "feat: add styles for card history block and trend dots"
  ```

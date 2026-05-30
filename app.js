'use strict';

// ── state ────────────────────────────────────────────────────────────────────
const state = {
  examId: null,
  questions: [],    // current question list (possibly shuffled / filtered)
  currentIndex: 0,
  userAnswers: {},  // { originalNum: selectedKeys[] }
  confirmed: {},    // { originalNum: true }
  skipped: {},      // { originalNum: true }
};

// ── boot ─────────────────────────────────────────────────────────────────────
fetch('data/exams.json')
  .then(r => r.json())
  .then(renderHome)
  .catch(() => {
    document.getElementById('exam-list').innerHTML =
      '<p style="color:red;padding:20px">無法載入考卷清單，請確認以 HTTP 伺服器啟動（不可直接開啟 file://）</p>';
  });

// ── home screen ──────────────────────────────────────────────────────────────
function renderHome(manifest) {
  // Group exams by year
  const byYear = {};
  for (const exam of manifest.exams) {
    (byYear[exam.year] = byYear[exam.year] || []).push(exam);
  }

  const container = document.getElementById('exam-list');
  container.innerHTML = '';

  // Sort years descending
  for (const year of Object.keys(byYear).sort((a, b) => b - a)) {
    const exams = byYear[year];
    const adYear = exams[0].ad_year;

    const group = document.createElement('div');
    group.className = 'year-group';
    group.innerHTML = `<h2>${year} 年度（民國 ${year} 年 / ${adYear} 年）</h2>
      <div class="exam-cards" id="cards-${year}"></div>`;
    container.appendChild(group);

    const grid = group.querySelector('.exam-cards');
    for (const exam of exams) {
      grid.appendChild(buildCard(exam));
    }
  }
}

function buildCard(exam) {
  const card = document.createElement('div');
  card.className = 'exam-card';

  const shuffleId = `shuffle-${exam.id}`;
  card.innerHTML = `
    <h3>${exam.title}</h3>
    <div class="subtitle">${exam.subtitle}</div>
    <div class="meta">
      <span>${exam.total} 題</span>
      <span>${exam.subject}</span>
    </div>
    <label class="shuffle-label" for="${shuffleId}">
      <input type="checkbox" id="${shuffleId}"> 隨機排序
    </label>
    <button class="btn-start" onclick="startExam('${exam.file}', '${exam.id}', '${shuffleId}')">
      開始測驗
    </button>`;
  return card;
}

// ── start exam ───────────────────────────────────────────────────────────────
function startExam(file, id, shuffleId) {
  const shuffle = document.getElementById(shuffleId)?.checked;
  fetch(file)
    .then(r => r.json())
    .then(data => launchQuiz(data, id, shuffle))
    .catch(() => alert('無法載入試題，請確認 data/ 資料夾存在'));
}

function launchQuiz(data, id, shuffle) {
  state.examId       = id;
  state.currentIndex = 0;
  state.userAnswers  = {};
  state.confirmed    = {};
  state.skipped      = {};

  let qs = [...data.questions];
  if (shuffle) qs = qs.sort(() => Math.random() - 0.5);
  state.questions = qs;

  document.getElementById('quiz-title').textContent = data.title;
  showScreen('quiz');
  renderQuiz();
}

// ── quiz screen ──────────────────────────────────────────────────────────────
function renderQuiz() {
  const qs    = state.questions;
  const idx   = state.currentIndex;
  const total = qs.length;
  const q     = qs[idx];
  const num   = q.num;

  document.getElementById('quiz-progress-text').textContent = `${idx + 1} / ${total}`;
  document.getElementById('question-num').textContent = `第 ${idx + 1} 題（原題號 ${num}）`;
  document.getElementById('question-stem').textContent = q.stem;

  // Image(s)
  const imgWrap = document.getElementById('question-image');
  imgWrap.innerHTML = '';
  const images = q.image ? (Array.isArray(q.image) ? q.image : [q.image]) : [];
  if (images.length) {
    images.forEach((src, i) => {
      const imgEl = document.createElement('img');
      imgEl.src = src;
      imgEl.alt = `圖(${i + 1})`;
      imgEl.style.cssText = 'max-width:100%;border-radius:8px;border:1px solid var(--border);box-shadow:0 2px 8px rgba(0,0,0,.08);cursor:pointer;transition:transform .2s;margin-bottom:8px';
      imgEl.onclick = () => openImgModal(src);
      imgWrap.appendChild(imgEl);
    });
    imgWrap.style.display = 'block';
  } else {
    imgWrap.style.display = 'none';
  }

  // Hints
  document.getElementById('multi-hint').style.display  = q.is_multi ? 'inline-block' : 'none';
  document.getElementById('free-hint').style.display   = (q.answer === '送分') ? 'inline-block' : 'none';

  // Options
  const optList = document.getElementById('options-list');
  optList.innerHTML = '';
  const isConfirmed = !!state.confirmed[num];
  const userSel     = state.userAnswers[num] || [];
  const correctKeys = q.answer ? [...q.answer] : [];

  for (const [key, text] of Object.entries(q.options)) {
    const btn = document.createElement('button');
    btn.className = 'option-btn';
    btn.disabled  = isConfirmed;

    const isSelected = userSel.includes(key);
    const isCorrect  = correctKeys.includes(key);

    if (isConfirmed) {
      if (isCorrect)          btn.classList.add('correct-ans');
      else if (isSelected)    btn.classList.add('wrong-ans');
    } else if (isSelected) {
      btn.classList.add('selected');
    }

    btn.innerHTML = `<span class="opt-label">${key}</span><span>${text}</span>`;
    btn.onclick   = () => selectOption(key);
    optList.appendChild(btn);
  }

  // Feedback
  renderFeedback(q, isConfirmed);

  // Footer buttons
  document.getElementById('btn-prev').disabled    = idx === 0;
  document.getElementById('btn-next').disabled    = idx === total - 1;
  document.getElementById('btn-skip').disabled    = isConfirmed;
  document.getElementById('btn-confirm').disabled = isConfirmed;

  // Progress grid
  renderProgressGrid();
}

function renderFeedback(q, isConfirmed) {
  const fb  = document.getElementById('feedback');
  const num = q.num;

  if (!isConfirmed) {
    fb.className = 'feedback';
    return;
  }

  if (q.answer === '送分') {
    fb.className = 'feedback free show';
    fb.textContent = '本題為送分題，所有人均得分。';
    return;
  }

  const userSel    = state.userAnswers[num] || [];
  const correctKeys = [...q.answer];
  const isCorrect   = arraysEqual(userSel.sort(), correctKeys.sort());

  if (state.skipped[num]) {
    fb.className = 'feedback wrong show';
    fb.textContent = `未作答。正確答案：${q.answer}`;
    return;
  }

  fb.className = `feedback ${isCorrect ? 'correct' : 'wrong'} show`;
  fb.textContent = isCorrect
    ? '正確！'
    : `錯誤。正確答案：${q.answer}`;
}

function renderProgressGrid() {
  const grid  = document.getElementById('progress-grid');
  const qs    = state.questions;
  const idx   = state.currentIndex;
  grid.innerHTML = '';

  qs.forEach((q, i) => {
    const num  = q.num;
    const cell = document.createElement('div');
    cell.className = 'pg-cell';
    cell.textContent = i + 1;
    cell.onclick = () => { state.currentIndex = i; renderQuiz(); };

    if (i === idx) cell.classList.add('current');
    else if (q.answer === '送分' && state.confirmed[num]) cell.classList.add('free');
    else if (state.confirmed[num]) {
      const userSel    = state.userAnswers[num] || [];
      const correctKeys = [...(q.answer || '')];
      cell.classList.add(
        state.skipped[num]
          ? 'skipped'
          : arraysEqual(userSel.sort(), correctKeys.sort()) ? 'correct' : 'wrong'
      );
    }

    grid.appendChild(cell);
  });
}

// ── answer interaction ────────────────────────────────────────────────────────
function selectOption(key) {
  const q   = state.questions[state.currentIndex];
  const num = q.num;
  if (state.confirmed[num]) return;

  if (!state.userAnswers[num]) state.userAnswers[num] = [];

  if (q.is_multi) {
    const arr = state.userAnswers[num];
    const pos = arr.indexOf(key);
    if (pos >= 0) arr.splice(pos, 1); else arr.push(key);
  } else {
    state.userAnswers[num] = [key];
  }
  renderQuiz();
}

function confirmAnswer() {
  const q   = state.questions[state.currentIndex];
  const num = q.num;
  if (state.confirmed[num]) return;

  if (q.answer !== '送分' && (!state.userAnswers[num] || !state.userAnswers[num].length)) {
    alert('請先選擇答案，或點選「跳過」');
    return;
  }
  state.confirmed[num] = true;
  renderQuiz();
}

function skipQuestion() {
  const q   = state.questions[state.currentIndex];
  const num = q.num;
  state.skipped[num]      = true;
  state.confirmed[num]    = true;
  state.userAnswers[num]  = [];
  renderQuiz();
  autoAdvance();
}

function autoAdvance() {
  const idx = state.currentIndex;
  if (idx < state.questions.length - 1) {
    setTimeout(() => { state.currentIndex = idx + 1; renderQuiz(); }, 400);
  }
}

function goNext() {
  if (state.currentIndex < state.questions.length - 1) {
    state.currentIndex++;
    renderQuiz();
  }
}

function goPrev() {
  if (state.currentIndex > 0) {
    state.currentIndex--;
    renderQuiz();
  }
}

// ── image modal ───────────────────────────────────────────────────────────────
function openImgModal(src) {
  document.getElementById('modal-img').src = src;
  document.getElementById('img-modal').classList.add('open');
}
function closeImgModal() {
  document.getElementById('img-modal').classList.remove('open');
}

// ── result screen ─────────────────────────────────────────────────────────────
function finishExam() {
  if (!confirm('確定要結束測驗嗎？')) return;

  const qs      = state.questions;
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
  const pass   = pct >= 60;

  document.getElementById('result-title').textContent = '測驗結果';
  document.getElementById('score-big').textContent    = `${pct}%`;
  document.getElementById('score-label').textContent  = pass ? '及格 (≥60%)' : '未及格 (<60%)';
  document.getElementById('score-big').style.color    = pass ? 'var(--green)' : 'var(--red)';
  document.getElementById('stat-correct').textContent = correct;
  document.getElementById('stat-wrong').textContent   = wrong;
  document.getElementById('stat-skip').textContent    = skipped;

  // Detail rows
  const rowsEl = document.getElementById('result-rows');
  rowsEl.innerHTML = '';
  qs.forEach((q, i) => {
    const num         = q.num;
    const isConfirmed = !!state.confirmed[num];
    const isSkipped   = state.skipped[num];
    const userSel     = state.userAnswers[num] || [];
    const isFree      = q.answer === '送分';
    const isCorrect   = isFree || (isConfirmed && !isSkipped &&
      arraysEqual(userSel.sort(), [...(q.answer || '')].sort()));

    let rowClass = 'result-row';
    if (!isConfirmed || isSkipped) rowClass += ' skip-row';
    else if (isCorrect)             rowClass += ' correct-row';
    else                            rowClass += ' wrong-row';

    let badge = '';
    if (!isConfirmed || isSkipped)  badge = '<span class="badge badge-skip">未作答</span>';
    else if (isFree)                badge = '<span class="badge badge-correct">送分</span>';
    else if (isCorrect)             badge = '<span class="badge badge-correct">正確</span>';
    else                            badge = '<span class="badge badge-wrong">錯誤</span>';

    const userAnsDisplay = isSkipped ? '—' : (userSel.join('') || '—');
    const correctDisplay = q.answer || '—';

    const row = document.createElement('div');
    row.className = rowClass;
    row.innerHTML = `
      <div>${i + 1}</div>
      <div class="stem-preview">${esc(q.stem)}</div>
      <div>${userAnsDisplay}</div>
      <div>${correctDisplay}</div>
      <div>${badge}</div>`;
    rowsEl.appendChild(row);
  });

  document.getElementById('btn-retry-wrong').style.display =
    wrong > 0 ? 'inline-block' : 'none';

  showScreen('result');
}

function retryWrong() {
  const qs      = state.questions;
  const wrong   = qs.filter(q => {
    const num = q.num;
    if (!state.confirmed[num] || state.skipped[num] || q.answer === '送分') return false;
    const userSel     = state.userAnswers[num] || [];
    const correctKeys = [...q.answer];
    return !arraysEqual(userSel.sort(), correctKeys.sort());
  });

  if (wrong.length === 0) { alert('沒有錯題！'); return; }

  state.currentIndex = 0;
  state.questions    = wrong;
  state.userAnswers  = {};
  state.confirmed    = {};
  state.skipped      = {};

  showScreen('quiz');
  renderQuiz();
}

function goHome() {
  showScreen('home');
}

// ── helpers ──────────────────────────────────────────────────────────────────
function loadHistory(examId) {
  try {
    const data = JSON.parse(localStorage.getItem(`quiz_history_${examId}`));
    return Array.isArray(data) ? data : [];
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
  } catch (e) { console.warn('saveHistory: could not write to localStorage', e); }
}

function showScreen(name) {
  document.getElementById('screen-home').style.display   = name === 'home'   ? 'block' : 'none';
  document.getElementById('screen-result').style.display = name === 'result' ? 'block' : 'none';

  const quizEl = document.getElementById('screen-quiz');
  if (name === 'quiz') quizEl.classList.add('active');
  else                 quizEl.classList.remove('active');
}

function arraysEqual(a, b) {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

function esc(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

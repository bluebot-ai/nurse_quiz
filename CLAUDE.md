# 專科護理師考古題練習網站

## 專案概覽

靜態前端網站，部署在 GitHub Pages。將衛生福利部 109–114 年度專科護理師甄審筆試 PDF 解析為 JSON，提供線上練習介面。

## 本機開發

```bash
python3 -m http.server 8080
# 開啟 http://localhost:8080
```

必須用 HTTP server，不能直接開 file://（fetch() 會被 CORS 擋）。

## 檔案結構

```
nurse_quiz/
├── index.html          # App shell（三個畫面：首頁、測驗、結果）
├── style.css           # 所有樣式（CSS 變數主題）
├── app.js              # 應用邏輯
├── parse_pdfs.py       # 一次性工具：PDF → JSON（需要 pdfplumber）
├── extract_images.py   # 一次性工具：從 PDF 擷取題目圖片
├── data/
│   ├── exams.json      # 考卷清單（manifest）
│   ├── {year}_{id}.json  # 各份考卷題目（12 個）
│   └── images/         # 題目圖片（46 張 jpg）
└── quiz/               # 原始 PDF（git-ignored，不上傳）
```

## 資料格式

### `data/exams.json`
```json
{
  "exams": [
    { "id": "114_neike", "title": "114年度 內科", "subtitle": "進階專科護理",
      "year": 114, "ad_year": 2025, "subject": "內科", "total": 80,
      "file": "data/114_neike.json" }
  ]
}
```

### `data/{exam_id}.json`
```json
{
  "id": "114_neike",
  "questions": [
    {
      "num": 1,
      "stem": "題幹文字",
      "options": { "A": "...", "B": "...", "C": "...", "D": "..." },
      "answer": "C",        // 單選；複選如 "BD"；送分如 "送分"
      "is_multi": false,    // true 代表複選（answer 長度 > 1）
      "has_image": false,   // 題目含圖片（題幹圖或選項圖皆會設 true）
      "image": null         // 題幹圖路徑：字串（單圖）或字串陣列（一題多圖，如圖六含甲/乙兩張）
      // "option_images": { "A": "...", "B": "...", ... }  // 選項本身是圖片時才有（如 113內科 Q2 四張心電圖）
    }
  ]
}
```

**圖片欄位：**
- `image` — 題幹引用的圖（`圖(一)`、`如附圖`、`心電圖如下`…）。一題可有多張圖（PA+lateral、甲+乙），此時為陣列。
- `option_images` — A/B/C/D 選項本身就是圖片（`options` 文字為空），由 `app.js` 在每個選項按鈕內渲染圖片。

**answer 格式：**
- 單選：`"C"`
- 複選：`"BD"` / `"ABC"`（直接串接，無分隔符）
- 送分：`"送分"`

## app.js 架構

狀態全部放在 `state` 物件：
```js
state = { examId, questions[], currentIndex, userAnswers{}, confirmed{}, skipped{} }
```

主要函式：
- `renderHome(manifest)` — 載入 exams.json 後渲染首頁卡片
- `startExam(file, id, shuffleId)` — fetch 考卷 JSON，呼叫 `launchQuiz()`
- `renderQuiz()` — 渲染當前題目、選項、進度格、回饋
- `confirmAnswer()` — 確認作答，寫入 `confirmed`
- `finishExam()` — 算分，切換到結果畫面
- `retryWrong()` — 過濾錯題，重新進入測驗
- `showScreen(name)` — 切換三個畫面（'home' / 'quiz' / 'result'）

**注意：** `showScreen` 必須用明確的 `'block'`，不能用 `''`，因為 CSS 預設 `#screen-result { display: none }`。

## 新增考卷的步驟

1. 把新年度 PDF 放進 `quiz/`（命名格式：`{年度}年度_專科護理師_{科目}_{試題|標準答案}.pdf`）
2. 在 `parse_pdfs.py` 的 `EXAMS` 清單加入新條目
3. 執行 `python3 parse_pdfs.py`
4. 執行 `python3 extract_images.py`
5. `git add data/ && git commit && git push`

## PDF 解析注意事項

- **parse_pdfs.py** 用 pdfplumber；**extract_images.py** 改用 **PyMuPDF(fitz) + Pillow**：
  `python3 -m pip install pymupdf pillow --user --break-system-packages`
- **109 年答案卷格式**與 110+ 不同：格狀排列（題號列 + 答案列），且夾雜水印字（標、準、答、案）
- **110 年通論 Q10**：PDF 水印「公告試題」嵌入選項文字，導致選項 B 缺損，答案仍正確
- **圖片擷取（extract_images.py）**：
  - 用 fitz 取得每頁圖片的「視覺位置」(top, left)，依閱讀順序排列（**不可用 pdfplumber 的物件順序，會錯位**）。
  - 以 MD5 過濾背景浮水印（出現在 ≥ 半數頁面者）、略過第 1 頁說明、過濾 < 5000px² 小圖。
  - **歸屬法**：每張圖指派給「題幹在它上方、最接近的那一題」（偵測左邊界的題號 `23.`，題號只會遞增 1..80；部分 PDF 題號前有雜訊字元 `ˉ`，正則需容忍）。
  - 題幹有 `圖(N)`/`如附圖`/`如下` → 存成 `image`（一題多圖則為陣列）；選項為空白（圖片選項）→ 存成 `option_images`。
- **parse_pdfs.py 已知 bug**：113 內科把第 37 題的題號誤判為「2」且題幹被截斷（已在 `data/113_neike.json` 手動修正，重跑 parse 會再壞）。

## 已知限制

- **109 年其實有題目圖**（內科 Q15/35/36、通論 Q42；舊文件誤記為無圖，現已可顯示）
- 110 年內科部分圖片解析度低（原 PDF 如此）
- 113 年內科 PDF 含重複圖（同一張圖在不同頁出現），歸屬法只取題幹下方那張，不再錯位

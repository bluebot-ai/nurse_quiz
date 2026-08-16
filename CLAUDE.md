# 專科護理師考古題練習網站

## 專案概覽

靜態前端網站，部署在 GitHub Pages。將衛生福利部 105–114 年度專科護理師甄審筆試 PDF 解析為 JSON，提供線上練習介面。

共 22 份考卷（每年通論 + 內科各一份；108 年分第一次、第二次兩場筆試，故有 4 份）。
105–108 年的 PDF 來自台灣專科護理師學會網站（`tnpa.org.tw/information/content.php?id=…`，105=149、106=177、107=195、108第一次=205、108第二次=207），
原始檔把試題與解答併在同一個 PDF、且 106 年還把通論與外科各組併在一起，已依本專案命名規則切割後放進 `quiz/`。

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
│   ├── {year}_{id}.json  # 各份考卷題目（22 個）
│   └── images/         # 題目圖片（92 張）
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

1. 把新年度 PDF 放進 `quiz/`（命名格式：`{前綴}_專科護理師_{科目}_{試題|標準答案}.pdf`，
   前綴預設是 `{年度}年度`；同一年有多場時另外指定，例如 `108年度第二次`）
2. 在 `parse_pdfs.py` 的 `EXAMS` 清單加入新條目
   （同一年多場時要補上第 6、7 個欄位 `file_prefix`、`exam_id`，例如 `"108年度第一次", "108_1_neike"`）
3. `python3 parse_pdfs.py 105_neike 105_tonglun`（只重跑指定考卷；不給參數會重跑全部）
4. `python3 extract_images.py --apply`（同樣可接考卷 id 只跑指定的；不加 `--apply` 是 dry-run）
   — **一定要在 parse 之後跑**，因為 parse 會清掉 JSON 裡的圖片欄位
5. 在 `extract_images.py` 的 `EXAMS` 也要加對應條目
6. `git add data/ && git commit && git push`

## PDF 解析注意事項

- **parse_pdfs.py** 用 pdfplumber；**extract_images.py** 改用 **PyMuPDF(fitz) + Pillow**：
  `python3 -m pip install pymupdf pillow --user --break-system-packages`
- **109 年答案卷格式**與 110+ 不同：格狀排列（題號列 + 答案列），且夾雜水印字（標、準、答、案）；
  108 年（205／207）也是格狀，105–107 年則是「題號 答案」欄位表，兩種格式 `parse_answers()` 都吃得下
- **文字層清洗（`_clean_page()`）**：這批 PDF 的文字層有三種雜訊，解析前一律先濾掉
  - 假粗體：同一個字被描繪兩次 → `page.dedupe_chars(tolerance=1)`（105 內科 p9–p11「林先生生 66 歲」）
  - 隱形浮水印：白色的「的」「a」字元散在內文裡（105、106 幾乎每題都有）→ 濾掉白色字元
  - 斜向大字浮水印「公告試題」「僅供參考」→ 濾掉字級 ≥ 40pt 的字元
  這也順手修好了 110 通論 Q10 選項 B 缺損、112 內科 Q35 選項 D 夾雜「45515」等舊問題
- **題號判定**：`^(\d+)\.(?!\d)` 加上「題號只能遞增、上限 80」的檢查，
  避免內文換行後開頭的小數被當成題號（106 內科「39.5C，白血球…」、107 內科「10.1mg/dL」曾因此吃掉整題）。
  舊文件記載的「113 內科 Q37 題號被誤判成 2、題幹被截斷」也是同一個 bug（「2.5mg/dL」換行到行首），
  以及 111 內科 Q51 整題消失（「1.4g/dL」）— 兩者都已由這個修正解決，不必再手動改 JSON。
  111 內科 Q51 先前手動補題時答案填成 `C`，標準答案 PDF 是 `B`，重跑後已更正
- **圖片擷取（extract_images.py）**：
  - 用 fitz 取得每頁圖片的「視覺位置」(top, left)，依閱讀順序排列（**不可用 pdfplumber 的物件順序，會錯位**）。
  - 以 MD5 過濾背景浮水印（出現在 ≥ 半數頁面者）、略過第 1 頁說明、過濾 < 5000px² 小圖。
  - **歸屬法**：每張圖指派給「題幹在它上方、最接近的那一題」（偵測左邊界的題號 `23.`，題號只會遞增 1..80；部分 PDF 題號前有雜訊字元 `ˉ`，正則需容忍）。
  - 題幹有 `圖(N)`/`如附圖`/`如下` → 存成 `image`（一題多圖則為陣列）；選項為空白（圖片選項）→ 存成 `option_images`。
  - **拼圖（`stitch_tiles()`）**：有些 PDF 把一張圖切成好幾塊相鄰的小圖（105 內科 Q63/Q65/Q68 的心電圖與解剖圖），
    圖框間距 < 3pt 者視為同一張圖，依各圖塊在頁面上的座標用 PIL 拼回一張。
    **要用圖塊本身的 bytes 拼、不要用 `get_pixmap` 重算頁面**，否則會把紅色「僅供參考」浮水印一起畫進圖裡。
    間距夠大的才算不同張（105 內科 Q77 的五張心電圖仍是 5 張）。
    **選項圖不套用拼圖**，否則 113 內科 Q2 的四張心電圖會被黏成兩張。

## 已知限制

- **107 通論 Q39** 依學會的疑義更正公告（195-8）答案為 `C、D`，故 JSON 存成複選 `"CD"`；
  該份的標準答案 PDF 直接使用更正後的公告表，不是原始那份
- **109 年其實有題目圖**（內科 Q15/35/36、通論 Q42；舊文件誤記為無圖，現已可顯示）
- 110 年內科部分圖片解析度低（原 PDF 如此）
- 113 年內科 PDF 含重複圖（同一張圖在不同頁出現），歸屬法只取題幹下方那張，不再錯位

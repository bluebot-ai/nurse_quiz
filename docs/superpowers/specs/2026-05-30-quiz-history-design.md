# 答題記錄與得分趨勢 — 設計規格

## 功能範圍

1. **每份考卷的作答歷史** — 記錄每次練習的錯題題號
2. **練習次數 / 得分趨勢** — 顯示最近 5 次的得分變化

## 資料儲存

**方案：** localStorage，每份考卷一個 key

**Key 格式：** `quiz_history_{examId}`（例如 `quiz_history_114_neike`）

**Value 格式：** JSON 陣列，最多 5 筆，最新在最前

```json
[
  {
    "date": "2026-05-30",
    "score": 72,
    "correct": 58,
    "wrong": 18,
    "skipped": 4,
    "wrongNums": [3, 7, 12, 25, 41]
  }
]
```

- `score`：百分比整數（0–100）
- `wrongNums`：答錯的原始題號陣列（`q.num`）
- 超過 5 筆時截斷尾端（保留最新 5 筆）

## UI — 考卷卡片

`buildCard()` 在渲染完基本資訊後，呼叫 `loadHistory(examId)` 並動態注入歷史區塊。

**有歷史記錄時：**
```
上次 72%  共練習 3 次
趨勢  ● 65  ● 70  ● 72
```
- 趨勢點由舊到新由左至右排列
- 綠點（≥60%）/ 紅點（<60%）

**無歷史記錄時：** 不顯示歷史區塊

## 程式碼改動

### `app.js`

| 函式 | 變更 |
|------|------|
| `saveHistory(examId, result)` | 新增：寫入 localStorage，維持最多 5 筆 |
| `loadHistory(examId)` | 新增：讀取並解析 localStorage，回傳陣列（失敗回傳 `[]`） |
| `finishExam()` | 修改：計算完分數後呼叫 `saveHistory()` |
| `buildCard(exam)` | 修改：渲染後附加歷史區塊 HTML |

### `style.css`

新增歷史區塊樣式：
- `.card-history`：卡片內分隔線上方的區塊
- `.trend-dot`：趨勢點（綠/紅，帶數字標籤）

## 不在此次範圍內

- 跨裝置同步
- 清除歷史記錄的 UI
- 依歷史錯題自動篩選練習

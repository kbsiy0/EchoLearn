# EchoLearn — Project CLAUDE.md

AI 語言學習 Web App：貼 YouTube URL → 產生中英雙語字幕 → 單句精準對齊播放。

> **狀態（2026-10-20）**：Phase 0（PR #1）、1a 循環播放與變速（PR #4）、1b 段段串流（PR #7）、2 影片歷史與學習進度恢復（PR #12）已完成並 archive 至 `openspec/archive/`；之後三輪 simplify / refactor（#13–#15）。
> 下一步候選：Phase 3（句子收藏 / 字卡、單字查詢）。
> 重啟指標：`git log` + `openspec/archive/` 最新一期的 `proposal.md`「Out of scope」段。

**與 user-level 分工**：工作分道（直做 / Micro / SDD-lite / SDD-full）、不可繞的 gate、N-round checkpoint、git 工作流、Simplify 通則定義在 `~/.claude/CLAUDE.md`，本檔只記 EchoLearn 特化。

## 技術棧

| 層 | 技術 |
|---|---|
| Frontend | React 19 + Vite 7 + TypeScript ~5.9 + Tailwind v4 + React Router 6 |
| Backend | FastAPI 0.115 + Python 3.9+（README 下限）+ SQLite (WAL mode)；依賴鎖版在 `backend/requirements.txt` |
| AI | OpenAI Whisper（唯一時間基準）、GPT-4o-mini（翻譯）；音訊下載走 `yt-dlp` |
| 測試 | pytest + Vitest + MSW；真實瀏覽器操作由專案 agent `.claude/agents/ui-verifier.md`（Playwright）承擔 |

## 架構原則

1. **Whisper 是唯一時間基準**：不使用 `youtube-transcript-api`，句級與字級時間都來自同一次 Whisper 轉錄（Phase 0 決策——兩個時間來源會互相漂移）。
2. **Services 為純函式 + progress callback**：進度透過 callback 往上報，為了 Phase 1 改成串流時不必重寫 service。
3. **Frontend 走 `features/` 切分**：player、jobs 自成目錄，含自己的 hooks / components / lib。
4. **驗收標準**：句級 highlight 誤差 ≤ 100ms、字級 ≤ 150ms、3 分鐘影片 < 60s 處理完。
5. **Sync 精度測量慣例**：`/watch/:videoId?measure=1` 關閉 auto-pause 與 loop（`frontend/src/features/player/lib/flags.ts`），供 ui-verifier 量連續播放的 sentence / word p95。IFrame postMessage resume latency（~190ms）是 UX 物理，不混進演算法精度指標。Production 預設 auto-pause ON。

## 目錄

```
backend/app/
  routers/              # FastAPI endpoints（薄）
  services/             # 業務邏輯（純函式）
    transcription/      # whisper + youtube_audio（yt-dlp 下載）
    translation/
    alignment/          # word stream → sentences
  repositories/         # SQLite CRUD——service 不直接碰 SQLite
  db/                   # schema.sql、connection.py
  jobs/                 # 背景執行器
  models/schemas.py     # Pydantic schemas（對外 API 形狀）
backend/tests/{unit,integration,fakes,fixtures}/  # fakes/ = whisper / translator 的 fake client
frontend/src/
  routes/               # 頁面級元件
  features/<name>/{hooks,components,lib}/
  api/  lib/  types/
openspec/archive/       # 已完成 phase 的 spec（不是生產碼）
docs/ui-verification/   # ★ ui-verifier 報告與截圖（PR 驗收證據的來源）
```

## 開發指令

```bash
cd backend && uvicorn app.main:app --reload --port 8000
cd backend && python -m pytest                    # 全部（unit + integration）
cd backend && python -m pytest tests/unit -v

cd frontend && npm install --cache /tmp/npm-cache-echolearn   # 系統 npm cache 有 root 擁有的檔案，直接 install 會 EACCES
cd frontend && npm run dev                        # http://localhost:5173
cd frontend && npm run lint && npm run build      # build = tsc -b && vite build，型別錯在這裡才炸
cd frontend && npx vitest run                     # 一次性執行；npm test 在互動終端是 watch 模式
```

## 分道觸發（diff path 機械比對；各道定義見 user-level）

- **SDD-full 觸發**（任一即中）：OpenAI key 與付費 API 呼叫，錯了會外洩 key 或重複扣費。
  - `backend/app/config.py`（`OPENAI_API_KEY`）、`backend/app/services/transcription/whisper.py`、`backend/app/services/translation/translator.py`
  - 清單是手維護的：新檔若讀 `OPENAI_API_KEY` 或呼叫 OpenAI，視同在清單內，並在同一 PR 補進來。
- **persona-tester**：SDD-lite / SDD-full 的 diff 動到使用者看得到的路徑才派；直做 / Micro 與純後端改動不派。
  - 視覺：`frontend/src/**`（非 `*.test.*`）
  - 前端看得到的 API：`backend/app/models/schemas.py`、`backend/app/routers/**`
  - 字幕同步精度（使用者唯一能直接感知的核心品質）：`backend/app/services/alignment/**`、`frontend/src/features/player/hooks/useSubtitleSync.ts`
- 前端行為類 task 另派專案 agent `ui-verifier`（`.claude/agents/ui-verifier.md`）量化驗證，報告寫 `docs/ui-verification/<task>.md`。
- **其餘改動**：新功能預設 SDD-lite；單根因小修走 Micro。

## Simplify（EchoLearn 特化）

通則見 user-level。本專案額外的進場點：**Phase 結束、spec archive 之前**——清 refactor 累積的 legacy 別名與未刪原檔（Phase 0：搬家未刪原檔 → 4 個 orphan .py 留在 `services/` 平層）。

Review scope 排除：`openspec/archive/**`、`backend/tests/**`、`frontend/src/**/*.test.*`、`docs/ui-verification/**`、`package-lock.json`、fixtures。生產碼聚焦 `backend/app/**/*.py` + `frontend/src/**/*.{ts,tsx}`（非測試）。

Phase 0 實測累積的常見可簡化項：
- 動過 `services/` 或 `features/` 目錄後，舊路徑 import grep 為 0 的原檔該刪
- Video ID regex / `_now()` helper 在各 repo 重複定義 → 集中到 `db/` 或 `lib/`
- 工作狀態、錯誤碼字串字面值散落 → 集中成 `Literal` union 或 StrEnum
- Router 各自定義 `get_db_conn` / `DbConn` → 放 `db/connection.py`
- 每-request 重跑 schema DDL / PRAGMA → 移到 lifespan 啟動一次

清理產出開 `change/cleanup-<scope>` 分支（例：`change/cleanup-phase0-deadcode`），不搭便車塞進其他 change。

## 已知陷阱

- **yt-dlp / ffmpeg 必要**：缺少或下載失敗時 `services/transcription/youtube_audio.py` 拋 `PipelineError("FFMPEG_MISSING", ...)`——看到這個錯先查本機工具，不是查程式。
- **OpenAI API key**：開發從 `.env` 讀（範本 `.env.example`）；`config.OPENAI_API_KEY` 預設空字串，測試走 `tests/fakes/` 不打真 API。
- **CORS**：backend 只允許 `http://localhost:5173`（`backend/app/main.py`）；改 port 時兩邊都要改。
- **PR 驗收證據**：附 ui-verifier 報告連結 + pytest / vitest 結果摘要。

## 易腐事實

測試數、目前 phase 進度細節、OpenAI key 是否有效、dev server 是否在跑——不記本檔，查 auto-memory 或現場驗證。

## History

Phase 0 把雙時間來源（YouTube captions + Whisper）收斂成 Whisper-only 並立測試底座；Phase 1a 在其上加循環與變速（純前端）。決策細節以 `openspec/archive/<phase>/` 與 `git log` 為準。

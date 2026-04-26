# EchoLearn — Project CLAUDE.md

此檔案是 EchoLearn 的專案層級規範。**使用者層級 CLAUDE.md（`~/.claude/CLAUDE.md`）的通用規則全數適用**，本檔只補充 EchoLearn 特有的約束。

## 專案簡介

AI 語言學習 Web App：貼 YouTube URL → 產生中英雙語字幕 → 單句精準對齊播放。

分期路線：
- **Phase 0（已完成 2026-04-20，PR #1）**：Whisper-only 精準對齊、SQLite 資料層、程式碼重構、React Router、測試底座。Spec 已 archive 至 `openspec/archive/phase0-refactor/`。
- **Phase 1a（已完成，PR #4）**：循環播放、速度控制。Spec 已 archive 至 `openspec/archive/phase1a-loop-and-speed/`。
- **Phase 1b（已完成 2026-04-26，PR #7）**：段段串流顯示與處理過程中的部分字幕。Spec 已 archive 至 `openspec/archive/phase1b-segment-streaming/`。
- **Phase 2**：影片歷史、學習進度恢復
- **Phase 3**：句子收藏 / 字卡、單字查詢

每期走一輪 spec → tasks → TDD → integrate。

## 技術棧

| 層 | 技術 |
|---|---|
| Frontend | React 18 + Vite + TypeScript + Tailwind v4 + React Router |
| Backend | FastAPI + Python 3.9+ + SQLite (WAL mode) |
| AI | OpenAI Whisper（唯一時間基準）、GPT-4o-mini（翻譯） |
| 測試 | pytest + Vitest + MSW + Playwright（透過 ui-verifier agent） |

## 架構原則（Phase 0 後）

1. **Whisper 是唯一時間基準**：不再使用 `youtube-transcript-api`，句級與字級時間都來自同一次 Whisper 轉錄。
2. **單檔 200 行上限**：超過代表責任不清，拆成更小的單位。
3. **Repositories 隔離 DB**：service 不直接操作 SQLite，一律走 `repositories/`。
4. **Services 為純函式 + progress callback**：不讀寫全域狀態；進度透過 callback 往上報，方便 Phase 1 改成串流。
5. **Frontend 走 `features/` 切分**：player、jobs 等功能自成目錄，含自己的 hooks 與 components。
6. **驗收標準可量測**：句級 highlight 誤差 ≤ 100ms、字級 ≤ 150ms、3 分鐘影片 < 60s 處理完。
7. **Sync 精度測量慣例**：`/watch/:videoId?measure=1` 會關閉 auto-pause，用於 ui-verifier 蒐集連續播放的 sentence / word p95。IFrame postMessage resume latency（~190ms）是 UX 物理，不混進演算法精度指標。Production 預設 auto-pause ON。

## 目錄慣例

```
backend/app/
  routers/              # FastAPI endpoints（薄）
  services/             # 業務邏輯（純函式）
    transcription/      # whisper + audio 下載
    translation/
    alignment/          # word stream → sentences
  repositories/         # SQLite CRUD
  db/                   # schema.sql、connection.py
  jobs/                 # 背景執行器
  models/               # Pydantic schemas

frontend/src/
  routes/               # 頁面級元件
  features/<name>/
    hooks/              # 該 feature 的 hooks
    components/         # 該 feature 的 UI
  api/                  # API client
  lib/                  # 純工具函式
  types/
```

## 開發指令

```bash
# Backend
cd backend && uvicorn app.main:app --reload --port 8000
cd backend && python -m pytest                    # 全部測試
cd backend && python -m pytest tests/unit -v      # 只跑 unit

# Frontend（npm cache 有 root 權限問題時加 --cache）
cd frontend && npm install --cache /tmp/npm-cache-echolearn
cd frontend && npm run dev                        # http://localhost:5173
cd frontend && npm run lint
cd frontend && npm run build
cd frontend && npx vitest run
```

## SDD 工作流與 Agent 進場時機

Phase 0 開始採 SDD（Spec-Driven Development）+ 5 個 agent：

| Agent | 進場時機 | 職責 |
|---|---|---|
| `spec-writer` | brainstorming 完成後 | 產出 `openspec/changes/<id>/{proposal,design,tasks}.md` + `specs/` |
| `spec-reviewer` | (1) spec 寫完、(2) 每個 task 完成後 | 架構 / QA / 安全審查 |
| `tdd-implementer` | spec 通過、人工同意後，逐個 task | Red-Green-Refactor，一 task 一 commit |
| `ui-verifier` | 凡影響前端行為的 task 完成後 | Playwright 跑 UI、量化測 sync 精度、寫 `docs/ui-verification/<task>.md` |
| `integrator` | 所有 task 綠燈後 | 全測試 + lint + build + PR 合併 + spec archive |

混合並行策略（來自 user CLAUDE.md）：
- **有依賴的 task** → 串聯（一次一個 implementer + 兩階段 review）
- **獨立的 task** → 並行（多個 implementer 同時 dispatch）
- 依賴分析由主 session 在讀 `tasks.md` 時判斷，不詢問使用者

## Simplify 流程（EchoLearn 特化）

通用規範見 user CLAUDE.md「Simplify」。EchoLearn 的觸發點與 scope：

### 進場時機

- **每個 tdd-implementer 完成 task 後、spec-reviewer 審 code 之前**：作為 implementer 的 self-cleanup，減少 reviewer 第 N 輪修正
- **integrator agent 跑全測試前**：最後一道價值 filter，避免把可簡化的程式碼合進 main
- **Phase 結束、spec archive 之前**：把 refactor 過程累積的 legacy 別名、死碼、未移走的舊檔案清乾淨（Phase 0 的教訓：搬家未刪原檔 → 4 個 orphan .py 留在 `services/` 平層）

### Review scope（EchoLearn 專屬 skip list）

派三個 review agent 時明確排除：
- `openspec/archive/**`（已 archive 的 spec，不是生產碼）
- `backend/tests/**`、`frontend/src/**/*.test.*`（測試自有規範）
- `docs/ui-verification/**`、`package-lock.json`、fixtures

生產碼聚焦：`backend/app/**/*.py` + `frontend/src/**/*.{ts,tsx}`（非測試）。

### EchoLearn 常見可簡化項（Phase 0 實測累積）

- 重構搬家後**原檔未刪**：動過 `services/` 或 `features/` 目錄後，grep 舊路徑的 import 為 0 就該刪
- Video ID regex / `_now()` helper 容易在各 repo 重複定義 → 集中到 `db/` 或 `lib/`
- 工作狀態、錯誤碼的字串字面值散落多處 → 集中成 `Literal` union 或 StrEnum
- Router 各自定義 `get_db_conn` / `DbConn` → 放到 `db/connection.py`
- 每-request 重跑 schema DDL / PRAGMA → 移到 lifespan 啟動一次

### 清理變更的分支

Simplify 產出**獨立於 Phase 的 change**：開 `change/cleanup-<scope>` 分支（例：`change/cleanup-phase0-deadcode`），走 PR 合併。不搭便車塞進其他 change branch。

## Git 工作流（重要）

### 分支規則

- **`main` 受保護**：絕不直接 commit、絕不 force push。任何變更都走 PR。
- **每個 SDD change 開一條分支**：命名 `change/<change-id>`，例如 `change/phase0-refactor`。分支一路存活到 integrator 合併回 main。
- **動工前先確認分支**：每個 agent（特別是 tdd-implementer）開始前必須 `git branch --show-current` 確認不在 main；在 main 則先 checkout 到 change branch。
- **並行 task 若會動到衝突檔案**：用 git worktree 隔離，例如 `git worktree add ../EchoLearn-task-05 change/phase0-refactor`，tdd-implementer 在該 worktree 作業後 merge 回主 change branch。

### Commit 規則

- 格式：`<type>(<scope>): <subject>`
  - type：`feat` / `fix` / `refactor` / `test` / `docs` / `chore`
  - scope：以 task 範圍為主，例：`feat(pipeline): whisper-only transcription`
- **一個 task 一個 commit**（tdd-implementer 強制）。refactor 步驟若必要可拆第二個 commit，但屬於同一 task。
- 絕不 `--amend` 已 push 的 commit；絕不 `--no-verify`、`--no-gpg-sign`；pre-commit hook 失敗代表有問題，修好再 commit（不是跳過）。

### PR 規則

- PR 標題 = change id（例：`Phase 0: Whisper-only refactor`）
- PR 說明含：change 目標、關鍵決策、驗收證據（ui-verifier 報告連結、pytest / vitest 結果摘要）
- 只有 integrator 或人類能按 merge；merge 策略優先 squash 或 rebase，保持 main 乾淨線性

### 絕對禁止

- ❌ 在 main 直接 commit
- ❌ force push 到 main
- ❌ 用 `git reset --hard`、`git checkout .`、`git clean -f` 清掉未 commit 的變更而沒先確認那不是你的在進行中的工作
- ❌ `--no-verify` 跳過 hook
- ❌ 未經使用者同意就 push

## 已知陷阱

- **npm cache 權限**：系統 npm cache 有 root 擁有的檔案。`npm install` 若失敗用 `--cache /tmp/npm-cache-echolearn` 繞過。
- **ffmpeg 必要**：Whisper 轉錄前要確認 `check_ffmpeg()`。缺 ffmpeg → 回傳 `FFMPEG_MISSING` error code。
- **OpenAI API key**：開發時從 `.env` 讀；測試時 `OPENAI_API_KEY` 預設為空字串不會爆（service 層走 fake client）。
- **CORS**：backend 只允許 `http://localhost:5173`；改 port 時兩邊都要改。

## 寫作與溝通

- 回覆繁體中文，保留專有名詞、函式名、程式關鍵字原文
- 不在每次回覆結尾總結剛做了什麼（diff 自己會說話）
- 功能完成的證明 = ui-verifier 報告 + 測試結果，不是口頭宣稱

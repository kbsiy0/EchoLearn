# Review: phase0-refactor — T01 Testing Foundation (Stage 2 Code Review)

**Date**: 2026-04-17
**Reviewed**: Code (commit `727914c` on `change/phase0-refactor`)
**Verdict**: **APPROVED_WITH_NOTES**

T01 交付品質整體良好：47 個 backend 測試綠、27 個 frontend 測試綠、生產 build 通過、ESLint placeholder 禁令兩種 import 路徑都能擋下、in-memory SQLite fixture 獨立、`EL_TEST_STRICT=1` 以 `autouse=True` 正確預設。下面列出的 issues 多為「T02/T03 必須補」或「應在 follow-up 收尾」的 notes，沒有阻斷性 critical。

---

## Issues Found

### Critical
無。

### Important

#### I1. `test_fake_signatures.py` 只比對 fake vs. 本檔內的 stub，沒比對 fake vs. real client（spec 承諾落空）
- **位置**：`backend/tests/unit/test_fake_signatures.py:22-38`（`_SpecWhisperClient`、`_SpecTranslator` 是檔內 stub）
- **觀察**：`specs/testing-infrastructure.md` 的 Invariants 明文：「If a fake's method signature drifts from the real client's, both are wrong; `test_fake_signatures.py` enforces the match via `inspect.signature` diff.」目前實作只把 fake 跟「測試檔案作者自己從 spec 抄來的 stub」比對 —— 兩者都是 T01 作者寫的，檢測不到 T03 的 `WhisperClient.transcribe(self, path: Path)`（把 `audio_path` 改成 `path`）這類漂移。檔內註解也自承「When T03 creates the real modules, a second test class below will also compare the fake against the real implementation」，但該 class 目前只是口頭承諾。
- **建議**：T01 加入 conditional 測試：用 `importlib.util.find_spec` 檢查 `app.services.transcription.whisper` / `app.services.translation.translator` 是否存在，存在則動態 import 並執行真正的 `fake vs. real` 比對。這樣 T03 一落地就會自動生效，不需要 T03 記得回來補；不存在則 `pytest.skip`。這正是 spec 要的「mechanical enforcement」。

#### I2. T01 添加 `backend/app/db/schema.sql` 屬 T02 scope
- **位置**：`backend/app/db/schema.sql`（34 行）
- **觀察**：T02 acceptance 第一條就是「`backend/app/db/schema.sql` contains the three-table schema from design.md Section 2 verbatim」，且 T02 "Files expected to touch" 列了 `schema.sql`。T01 提前加入該檔，屬於向下一 task 越界。
  - 額外子問題：schema.sql 的 `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` 不是 design.md Section 2 的 **verbatim**（design 用 `CREATE TABLE jobs` 沒有 IF NOT EXISTS）。T02 acceptance 是 verbatim 要求，會在 T02 review 時被抓。
- **建議**：屬於 implementer 在提交時主動揭露的偏離 (#1)，理由是「讓 conftest 不用內嵌 schema 字串」，可接受。請 T02 implementer 在自己的 task 一開始確認 schema.sql 是否需要改回完全 verbatim（去掉 IF NOT EXISTS），並補上 T02 要求的其它檔案（`connection.py`、repos）。spec-reviewer 會在 T02 審查時再度檢查。

### Minor

#### M1. 新增的 ESLint `react-hooks/set-state-in-effect` 規則對 placeholder 報錯 2 條
- **位置**：
  - `frontend/src/test/placeholders/useJobPolling.ts:53` — `setJob(null); setError(null)` 在 effect body 同步執行
  - `frontend/src/test/placeholders/useSubtitleSync.ts:99` — reset path 同步 `setCurrentIndex(-1)`
- **觀察**：`npm run lint` 共 5 個 error。其中 3 個在 `src/hooks/*` 是 Phase 0 開始前就存在（非 T01 責任），2 個在 T01 新增的 placeholder。Project-level DoD 要求 lint 綠。雖然 placeholder 會在 T06/T07 被刪掉，但 Phase 0 進行中的任何 task 都不應讓 lint 狀態更糟。
- **建議**：placeholder 可以加 `// eslint-disable-next-line react-hooks/set-state-in-effect` 並註解「intentional — mirrors production hook's reset-on-dep-change behaviour; will be removed in T06/T07」，或改用 `useLayoutEffect` 之類。不擋 T01 進 T02，但記在 notes，T02 不得再加新 lint error。

#### M2. `frontend/src/features/player/hooks/useSubtitleSync.test.ts` 234 行 > 單檔 200 行上限
- **位置**：`frontend/src/features/player/hooks/useSubtitleSync.test.ts`（234 行）
- **觀察**：CLAUDE.md 的「單檔 200 行上限」規則對 test 檔也適用（規則沒有豁免 test）。檔案由三個 describe block 組成（segment binary search / word binary search / no-rerender），是合理可拆的邊界。
- **建議**：可拆成 `useSubtitleSync.segment.test.ts`、`useSubtitleSync.word.test.ts`、`useSubtitleSync.stable.test.ts` 三檔，或用 `describe.each` 壓縮樣板。低優先，T07 重寫時可順手處理。

#### M3. 主動偏離 #2：placeholder `useJobPolling` 增加 `intervalMs` 參數（偏離 spec 預期的「match eventual real counterpart signature」）
- **位置**：`frontend/src/test/placeholders/useJobPolling.ts:41`
- **觀察**：spec Placeholder discipline 要求「Each placeholder exports the same type signature as its eventual real counterpart so tests compile」。實作為了測試縮短 poll interval，在 placeholder 加了 `intervalMs = 1000` 預設參數。若 T06 的真實 hook 簽名不吃 `intervalMs`（例如走 `defaultPollIntervalMs` const），T01 的 test 搬過去時會編譯失敗、要修 call site。
- **建議**：可接受為 pragmatic 偏離，但請 T06 作者明確抉擇：(a) 真實 hook 也接受 optional `intervalMs`（推薦，符合 spec invariant「Thresholds are parameters, never constants-in-code」），或 (b) 真實 hook 固定 interval，`useJobPolling.test.ts` 改用 `vi.useFakeTimers()`。寫進 T06 的 task notes。

#### M4. 主動偏離 #3：`tsconfig.app.json` 將 `src/test/**` 和 `*.test.ts` 排除於 build 之外
- **位置**：`frontend/tsconfig.app.json:25-29`
- **觀察**：合理處理 —— 避免 msw / @testing-library/react 被 vite/tsc 當成 production bundle 一部分；且 placeholder 檔被排除後反而強化了「production 不能依賴 placeholder」的邊界。這個偏離是正確的。
- **建議**：無，僅記錄為可接受的偏離。

#### M5. 主動偏離 #4：ESLint `no-restricted-imports` 而非 CI grep
- **位置**：`frontend/eslint.config.js:21-45`
- **觀察**：已驗證兩種 import 路徑（`./test/placeholders/...` 與 `../../test/placeholders/...`）都會被擋；測試檔與 `src/test/**` 內檔案都能正常 import。這是比 grep 更結構化、IDE 友善的實作，spec 原文就允許這兩種方式擇一。
- **建議**：無。

---

## Architecture Review

- **層次**：test fixture / fake / placeholder / production 四層界線清晰；placeholder 用 ESLint 規則硬擋、tsconfig.app.json 排除於 build 之外，雙重保險避免 production 誤用。
- **Fake 設計**：constructor 吃 `list | Exception` 的設計簡潔，錯誤注入語意清楚。`translate_batch` unknown key 回傳原字串的 fallback 行為與 real translator padding 行為對齊，文件有寫明。
- **Fixture 設計**：`db_conn` 每 test 獨立 `:memory:`、`PRAGMA foreign_keys = ON` 有開、`autouse=True` 的 `EL_TEST_STRICT=1` 讓所有 test 預設 strict —— 符合 spec。
- **scope creep**：T01 越界加了 `app/db/schema.sql`（見 I2），但性質是前置 artifact、沒破壞設計。
- **200 行規則**：只有 `useSubtitleSync.test.ts` 234 行破壞（見 M2）。

## QA Review

- **Backend pytest**：47 個測試綠（37 個 pre-existing + 10 個 T01 新增）。`test_fake_signatures.py` 的 9 個 case 覆蓋參數名、kind、回傳型態煙霧測試、例外注入 —— 都是行為測試，不是 import-only。
- **Frontend vitest**：27 個測試綠。`useJobPolling` 覆蓋了 null jobId / polling / completed stop / failed stop / unmount cancel / 回傳欄位，相當完整。`useSubtitleSync` 的 binary-search 邊界覆蓋 before-all / at-boundary / mid / gap / after-all / word-level，也是行為測試。`useYouTubePlayer` 覆蓋了 onReady / onStateChange / destroy / null videoId / late-callback-after-unmount，這些都是真的 behavioral assertions。
- **沒涵蓋 spec 承諾的「drift enforcement」**：I1 是 QA 層面最大的缺口 —— fake vs. real 的機械化檢查不存在。
- **timing tests**：用真 timer + 50ms interval 而非 fake timer，spec 允許的 tradeoff；`useSubtitleSync` 則用 `vi.useFakeTimers()` 控 RAF。

## Security Review

- **無硬編碼秘密**：`.env`、API key 不在任何 T01 檔案。
- **Placeholder guard 實測通過**：相對路徑 `./test/placeholders/...` 與 `../../test/placeholders/...` 都會觸發 ESLint error，production code 無法 import。測試檔與 `src/test/**` 正確豁免。
- **In-memory SQLite 獨立性**：驗證 `:memory:` connection 間無共享 —— 一個 test 不會看到另一個 test 的 row。
- **`EL_TEST_STRICT` autouse**：每個 test 預設 strict，進入 T02 後若要測 production mode 必須明示 `monkeypatch.delenv`，不會意外退化成 prod 路徑。
- **Fake `translate_batch` 失敗模式**：fake 吃到 `Exception` 時 raise，不會誤觸 real client —— conftest 沒有註冊任何 real OpenAI client，沒有「fake 被繞過直接打 real」的風險。
- **No network / no filesystem**：fixture 不 touch 真實 db 檔案、不 touch `data/` 目錄，符合 spec 的 hermetic 要求。

---

## Recommendations (依優先序)

1. **T01 補 patch（建議 on this branch）**：
   - 在 `test_fake_signatures.py` 加入 `importlib`-based conditional test class，對應 I1。這是 spec 明文要求，價值高、改動小。
   - 兩個 placeholder 的 effect-setState 加 `eslint-disable-next-line` 並註明 rationale（M1），讓 lint 至少不退化。
2. **T02 啟動前 implementer 注意**：
   - 確認 `schema.sql` 是否要改回 verbatim（去 `IF NOT EXISTS`），或修 design.md/T02 acceptance 放寬（二擇一）。
   - `connection.py` 還沒建，T02 仍需補上 WAL mode。
3. **T06 啟動前 implementer 注意**：
   - 決定真實 `useJobPolling` 是否接受 `intervalMs`（M3），並同步更新 test import 與 placeholder 刪除。
4. **T07 啟動前 implementer 注意**：
   - 刪 `useYouTubePlayer` / `useSubtitleSync` placeholder 時，把 `useSubtitleSync.test.ts` 拆小於 200 行（M2）。

**Verdict**: **APPROVED_WITH_NOTES** — T01 可進 T02，上述 I1 建議盡快補在同一 branch 的 follow-up commit；M1–M5 可併入後續 task 處理。

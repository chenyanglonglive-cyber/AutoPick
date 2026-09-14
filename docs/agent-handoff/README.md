# AutoPick Agent Handoff Pack

This package is a safe, reusable onboarding guide for an Agent taking over AutoPick. It contains no customer photos, project databases, exports, history reports, feedback, or API keys.

## 1. Get the code

GitHub repository: <https://github.com/chenyanglonglive-cyber/AutoPick>

```powershell
git clone https://github.com/chenyanglonglive-cyber/AutoPick.git
Set-Location AutoPick
```

To work from the current released baseline, use:

```powershell
git checkout V1.0.0
```

Otherwise, use the default branch for the newest work in progress.

## 2. Configure the local environment

Requirements: Windows, Python 3.12 or later, Node.js 20 or later, pnpm, and WebView2 for desktop mode. Before installing dependencies, verify the command-line tools:

```powershell
python --version  # 3.12 or later
node --version    # 20 or later
pnpm --version
```

Install missing prerequisites through the approved company software channel. WebView2 is required only when starting `python -m backend.desktop`; browser development does not need it.

```powershell
Copy-Item .env.example .env
python -m pip install -r requirements.txt
Set-Location frontend
pnpm install
Set-Location ..
```

Edit `.env` locally:

```ini
DASHSCOPE_API_KEY=your_DashScope_key
AUTOPICK_DATA_ROOT=./AutoPickData
AUTOPICK_DEMO_EMBEDDINGS=0
AUTOPICK_QWEN_MAX_RETRIES=8
AUTOPICK_TRAINING_FEEDBACK_THRESHOLD=500
```

`.env` normally sits at the repository root so the application can load it, but it is Git-ignored and must remain untracked. Obtain `DASHSCOPE_API_KEY` from the organization's approved DashScope account and do not paste it into issues, source code, or chat logs.

Use `AUTOPICK_DEMO_EMBEDDINGS=1` only to demonstrate the interface without a key. It must not be used for real audit matching. For customer work, replace the relative data path with an absolute path outside the repository, for example `AUTOPICK_DATA_ROOT=D:\AutoPickData`. A repository-relative data directory is suitable only for disposable local demonstrations and must remain ignored.

## 3. Run the application

For browser development, use two terminals:

```powershell
# Terminal 1, repository root
python -m backend.run
```

```powershell
# Terminal 2
Set-Location frontend
pnpm run dev
```

The API listens on `http://127.0.0.1:8787`; Vite prints the browser URL.

For the local desktop application:

```powershell
python -m backend.desktop
```

## 4. Product model the Agent must preserve

- Built-in checklist types are `quality_v1` (Quality Checklist, 199 image fields) and `social_audit_v1` (Social Audit Checklist, 36 reserved image fields).
- A factory project shares its gallery, image vectors, and OCR across checklist types.
- Fields, candidates, confirmations, aliases, feedback, and training readiness are isolated by checklist type. Switching checklists must not mix their matching or learned data.
- Automatic selection is one image to one field within the same checklist. Manual confirmation and different checklist types may explicitly reuse a photo.
- If no candidate clears the automatic-selection confidence criteria, leave the field empty. Do not force an answer or label a weak result as a recommendation.
- The normal workflow is: import gallery → build image vectors → run local OCR (recommended) → select the required checklist → rematch → review manually → export `.xlsx`.

## 5. Data safety rules

Runtime business data belongs only under `AUTOPICK_DATA_ROOT`, including SQLite databases, imported photos, OCR artifacts, exports, and Word history reports. Never commit or package any of those files, nor `.env`.

The only Excel templates that may travel with source code are the blank, fixed templates:

- `resources/checklists/quality_v1/Quality list.xlsx`
- `resources/checklists/social_audit_v1/Social Audit Checklist.xlsx`

Keep their sheet names, cell coordinates, merged cells, column widths, row heights, and styles intact. Insert images only at the defined image cells; never cover the field labels.

## 6. Before handing work back

Run the verification and release steps in [PROJECT_CHECKLIST.md](PROJECT_CHECKLIST.md). Read the repository-level [AGENTS.md](../../AGENTS.md) before changing matching, Excel handling, or data storage.

### Code map for safe changes

| Area | Primary location |
| --- | --- |
| API routes and application-facing behavior | `backend/autopick/api.py` |
| Checklist matching, automatic confirmation, feedback flow | `backend/autopick/services.py` |
| Database schema and `checklist_aliases` persistence | `backend/autopick/db.py` |
| Fixed-workbook export and `image_cell` insertion rules | `backend/autopick/excel_checklist.py` |
| Browser and desktop startup | `backend/run.py`, `backend/desktop.py` |
| Main browser interface | `frontend/src/App.vue` |
| Blank fixed templates | `resources/checklists/` |

Use the code map to orient changes, then read the repository-level `AGENTS.md` before editing. Do not infer or alter Excel field coordinates from a customer export.

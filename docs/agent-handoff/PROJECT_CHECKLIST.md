# AutoPick Project Checklist

Use this checklist for a new machine, an Agent handoff, or a release. It intentionally excludes customer business data.

## A. New-machine readiness

- [ ] Clone `https://github.com/chenyanglonglive-cyber/AutoPick.git` and enter the `AutoPick` folder.
- [ ] Choose the intended code state: default branch for current work, or `V1.0.0` for the released baseline.
- [ ] Copy `.env.example` to `.env` in the repository root; keep the new `.env` untracked and never share its contents.
- [ ] Install Python 3.12+, Node.js 20+, pnpm, and WebView2 when desktop mode is required.
- [ ] Run `python -m pip install -r requirements.txt`.
- [ ] Run `pnpm install` from `frontend`.
- [ ] Set a real `DASHSCOPE_API_KEY` for matching, or use demo embeddings only for interface demonstrations.
- [ ] Use an absolute `AUTOPICK_DATA_ROOT` outside the repository (for example, `D:\AutoPickData`) for all customer work.

## B. First-run functional check

- [ ] Start `python -m backend.run` from the repository root.
- [ ] Start `pnpm run dev` from `frontend` in a second terminal, then open the URL printed by Vite.
- [ ] Confirm that both **Quality Checklist** and **Social Audit Checklist** are available when creating or switching a project checklist.
- [ ] Confirm that each checklist has its own fields, candidates, confirmations, aliases, feedback, and learning readiness.
- [ ] Confirm that shared gallery, visual embedding, and OCR data remain available when switching checklists.
- [ ] Confirm automatic matching does not reuse one photo for two fields in the same checklist.
- [ ] Confirm a low-confidence or unsuitable field remains empty instead of receiving a forced answer.

## C. Change safety

- [ ] Do not commit `AutoPickData/`, `.env`, customer photos, project SQLite files, exports, or Word reports.
- [ ] Do not replace built-in blank Excel templates with customer exports.
- [ ] Preserve workbook layouts and insert pictures only into defined `image_cell` positions.
- [ ] Ensure learned aliases are written to `checklist_aliases`, scoped to the correct checklist type.
- [ ] Keep automatic matching isolated per checklist; only explicit manual confirmation may reuse an image.

## D. Verification before a code handoff or release

```powershell
git rev-parse -q --verify refs/tags/V1.0.0
python -m pytest tests/test_excel_checklist.py tests/test_feedback_import.py -q
Set-Location frontend
pnpm run build
Set-Location ..
git diff --check
git status --short
```

- [ ] Verify the exported workbook can open in Excel or LibreOffice and that picture anchors are correct.
- [ ] Review `git status --short`; only code, tests, documentation, and blank built-in templates may be committed.
- [ ] Treat the focused tests and frontend build above as the current required verification gate. Run the full suite only after separately resolving or allowing for its known cross-project-index timing issue.
- [ ] If creating a release, create an annotated version tag only after verification, then push the branch and tag.

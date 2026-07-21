# Task: Clarify W1/W2 workflow labels

## Goal
Unify Dashboard and documentation terminology so W1 means response scan/check and W2 means apply, with no W3 workflow.

## Background
The project currently has inconsistent workflow labels:
- `code/dashboard/frontend/src/pages/Dashboard.tsx` schedule card labels show `W1 投递` and `W2 检查`.
- `code/dashboard/frontend/src/components/workflow/WorkflowTrack.tsx` shows `投递流程 (W2)` and `回复扫描 (W3)`.
- `TECHNICAL.md` describes W2/W3 progress tracks.

The intended business mapping is:
- W1 = 回复扫描 / check workflow (`workflowId="check"`)
- W2 = 投递 / apply workflow (`workflowId="apply"`)
- There is no W3 workflow.

## Implementation Requirements

### 1. `code/dashboard/frontend/src/pages/Dashboard.tsx`
Update schedule labels and schedule log display so:
- `check` is shown as `W1 检查` or equivalent clear W1 response-scan wording.
- `apply` is shown as `W2 投递`.
- Any workflow-to-label mapping reflects `check -> W1`, `apply -> W2`.

### 2. `code/dashboard/frontend/src/components/workflow/WorkflowTrack.tsx`
Update progress track naming so:
- check steps use W1 naming, not W3.
- apply steps use W2 naming.
- Remove W3 terminology from variable/type names and comments where practical.
- UI titles clearly show `回复扫描 (W1)` and `投递流程 (W2)`.

### 3. `code/dashboard/frontend/src/components/workflow/WorkflowPanel.tsx`
Update comments or visible text that refer to auto-poll W3 so they refer to W1/check instead.

### 4. Documentation and comments
Update user-facing or maintainer-facing references in:
- `README.md`
- `TECHNICAL.md`
- obvious comments in `code/dashboard/server.py`

The wording must explicitly state the stable mapping:
- W1 = check / 回复扫描
- W2 = apply / 投递
- W3 does not exist

Do not change runtime behavior or workflow keys (`apply`, `check`).

## Acceptance Criteria
- [ ] `rg -n "W3" README.md TECHNICAL.md code/dashboard/frontend/src code/dashboard/server.py` returns no stale W3 workflow references.
- [ ] Dashboard schedule labels map `check -> W1` and `apply -> W2`.
- [ ] WorkflowTrack titles show check as W1 and apply as W2.
- [ ] Run `node --check` or TypeScript build/compile validation appropriate for the changed frontend files.

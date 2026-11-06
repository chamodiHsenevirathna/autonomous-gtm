# Autonomous GTM - frontend

Vite + React + TypeScript single-page app for the Corvane Digital case study (fictional company, **synthetic data, simulated model**).
No UI or chart libraries, no external fonts or CDNs: it works offline.

## Install and run

```bash
cd frontend
npm install
npm run dev            # mock mode (default): in-memory fixtures, no backend needed
```
Open http://localhost:5173. Drive the story from **Demo control**: submit the scripted enquiry, approve proposal #301 then #302
in **Approvals**, deliver the scripted reply, then open the account to see the updated intelligence and **Audit** to verify the chain.

### Against the backend
```bash
# backend on 127.0.0.1:8765 (see ../backend)
VITE_API_MODE=http npm run dev      # Vite proxies /api/* to http://127.0.0.1:8765
```
The JSON the UI expects is specified in [API_SPEC.md](API_SPEC.md). For a static build served next to the API, build with
`VITE_API_MODE=http npm run build` and serve `dist/` from the same origin as `/api`.

## Scripts
| Command | What |
|---|---|
| `npm run dev` | dev server |
| `npm run build` | type check (`tsc --noEmit`) then production build to `dist/` |
| `npm run typecheck` | type check only |
| `npm test` | vitest (mock API behaviour, approval flow, audit verify, evaluation honesty statement, render smoke test of every page) |

## Structure
```
src/api/types.ts         DTOs (snake_case, mirrors gtm/contracts/api.py + frontend-defined DTOs)
src/api/client.ts        Api interface, ApiError, scripted demo ids
src/api/http.ts          fetch implementation (/api/*)
src/api/mock/            in-memory backend: mockApi.ts (golden thread, gateway simulation, hash chain), seed.ts (eval fixture)
src/api/sha256.ts        sync SHA-256 + canonical JSON (mock audit chain and payload hashes are real hashes)
src/api/index.ts         createApi(): VITE_API_MODE=mock (default) | http
src/context.tsx          AppProvider + useData (refetches after any decision or demo action)
src/components/          Layout (header, SYNTHETIC notice, sim clock, theme), ui (badges, cards, states)
src/pages/               Overview, Leads, Accounts(+detail), Approvals, Runs(+trace), Alerts, Audit, Evaluation, Feedback, Demo
src/styles.css           CSS variables, light/dark themes, responsive rules
```

## Honesty and design notes
- A persistent banner states that data is synthetic and the model a deterministic mock; the header shows the **simulated** clock.
- Mock mode shows a "Mock API (browser fixtures)" pill. Evaluation numbers in mock mode are static fixtures, labelled as such.
- Status is never colour-only (glyph plus text). Data origins (GT, SIM, SCR, MOD, HUM-sim, HUM-real, PLT) and evidence bases
  (measured on simulation, machinery check, modelled impact) are badges with explanatory tooltips.
- Mock-only: "Tamper with one row" on the Audit page corrupts a row so the broken-chain display can be shown. It does not exist in http mode.
- Theme: follows the OS, toggle in the header (stored in localStorage, optional).

# Capture scripts

`capture.mjs` drives the golden thread through the real UI against the real backend (no mocks) with Playwright (the frontend's installed `@playwright/test`).

Rerun (from the project root; Postgres must be up on 127.0.0.1:5433):

```
source .venv/bin/activate
(cd backend && python -m gtm.cli serve) &          # API + simulators on :8765, RESETS the demo DB
(cd frontend && VITE_API_MODE=http npm run dev) &  # note the port Vite prints (5173, or 5174 if busy)
cd portfolio/capture
BASE_URL=http://localhost:5174 MODE=shots node capture.mjs   # PNGs into ../screenshots (1440x900 @2x, light)
BASE_URL=http://localhost:5174 MODE=video node capture.mjs   # ../demo/golden-thread.webm (1280x800)
```
Convert with ffmpeg as described in `../demo/README.md`. Stop both servers afterwards.

Notes: tall pages are captured by temporarily growing the viewport (capped at 2600 CSS px; Audit and Evaluation are therefore cut off at the bottom). Every shot waits for network idle and no `.spinner` / "Loading" text. `shot-problems.json` lists browser console errors seen (only the expected 422 from the blocked price edit). `video-marks.json` has the step timestamps of the last video run.

# Golden-thread screen recording

`golden-thread.mp4` (H.264, 1280x800, ~105 s, no audio, 2 MB; re-encoded from a Playwright recording) and `golden-thread.gif` (800 px, 6 fps, 3 MB).

It is ONE scripted, continuous run of the real UI against the real backend, with a fictional company, simulated providers/CRM/email and a deterministic mock model (llm_mode: mock). No real message is sent. The script pauses 2 to 4 s per screen so it can be read.

Approximate timeline (seconds):

| Time | Step |
|---|---|
| 0:00 | Demo control, reset to clean state |
| 0:04 | Submit scripted enquiry |
| 0:08 | Leads: lead scored (fit high 0.90) |
| 0:12 | Account: provenance, AI-written fields, agent state |
| 0:23 | Approvals queue |
| 0:26 | CRM proposal: exact payload and SHA-256 hash |
| 0:33 | Approve: 13 gateway checks |
| 0:36 | Reply edited to include a price ("EUR 20,000") |
| 0:39 | Blocked by the commercial-content screen |
| 0:43 | Clean edit approved: payload diff, new hash, send parked |
| 0:47 | Demo control: advance simulated clock +1 hour |
| 0:50 | Parked send executes ("sent to ...") |
| 0:53 | Deliver scripted customer reply |
| 0:57 | Account intelligence updated (stakeholders, commitments) |
| 1:06 | Run trace |
| 1:10 | Audit: chain verification OK |
| 1:40 | Evaluation re-run (about 30 s of the preceding wait is the evaluation executing; the page shows the button state) |
| 1:46 | Overview |

Note: the clock advance used is +1 hour, not +3 days. At 1280 px the banner wraps and the page scrolls with the header, unlike the 1440 px screenshots.

## Regenerate
Start the backend and frontend as in `../capture/README.md`, then:
```
BASE_URL=http://localhost:5174 MODE=video node ../capture/capture.mjs
ffmpeg -y -i golden-thread.webm -c:v libx264 -pix_fmt yuv420p -crf 26 -preset slow -an -movflags +faststart golden-thread.mp4
ffmpeg -y -i golden-thread.mp4 -vf "fps=6,scale=800:-1:flags=lanczos,palettegen=max_colors=96" pal.png
ffmpeg -y -i golden-thread.mp4 -i pal.png -lavfi "fps=6,scale=800:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4" golden-thread.gif
```

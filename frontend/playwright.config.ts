import { defineConfig } from '@playwright/test';

const MOCK = 'http://127.0.0.1:5199';
const REAL = 'http://127.0.0.1:5197'; // http mode against the REAL backend started below
const HTTP = 'http://127.0.0.1:5198'; // http mode, proxy deliberately points at a dead port

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: { viewport: { width: 1280, height: 800 } },
  projects: [
    { name: 'mock', testIgnore: /http-down|real-/, use: { baseURL: MOCK } },
    { name: 'real-backend', testMatch: /real-/, use: { baseURL: REAL } },
    { name: 'http-down', testMatch: /http-down/, use: { baseURL: HTTP } },
  ],
  webServer: [
    // The real backend resets the demo DB on start. Run with `npx playwright test --project=real-backend`.
    {
      command: 'bash -c "cd ../backend && source ../.venv/bin/activate && python -m gtm.cli serve"',
      url: 'http://127.0.0.1:8765/api/health', timeout: 120_000, reuseExistingServer: false,
    },
    { command: 'npx vite --port 5197 --strictPort --host 127.0.0.1', url: REAL, env: { VITE_API_MODE: 'http', VITE_PROXY_TARGET: 'http://127.0.0.1:8765' }, timeout: 60_000 },
    { command: 'npx vite --port 5199 --strictPort --host 127.0.0.1', url: MOCK, env: { VITE_API_MODE: 'mock' }, timeout: 60_000 },
    { command: 'npx vite --port 5198 --strictPort --host 127.0.0.1', url: HTTP, env: { VITE_API_MODE: 'http', VITE_PROXY_TARGET: 'http://127.0.0.1:9' }, timeout: 60_000 },
  ],
});

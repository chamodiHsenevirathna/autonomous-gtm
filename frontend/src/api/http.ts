import { ApiError, type Api, GOLDEN_ENQUIRY_ID, GOLDEN_REPLY_ID } from './client';

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    throw new ApiError(0, `Cannot reach the backend (${(e as Error).message}). Is it running on 127.0.0.1:8000?`);
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j?.detail === 'string' ? j.detail : JSON.stringify(j?.detail ?? j);
    } catch {
      // Non-JSON error body (e.g. dev proxy "ECONNREFUSED" 5xx): the API itself is not answering.
      if (res.status >= 500) throw new ApiError(0, `The API did not answer (HTTP ${res.status}). Is the backend running on 127.0.0.1:8000?`);
    }
    throw new ApiError(res.status, msg || `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

const get = <T>(p: string) => req<T>('GET', p);
const post = <T>(p: string, b?: unknown) => req<T>('POST', p, b ?? {});

export function createHttpApi(): Api {
  return {
    mode: 'http',
    health: () => get('/api/health'),
    config: () => get('/api/config'),
    overview: () => get('/api/overview'),
    leads: () => get('/api/leads'),
    accounts: () => get('/api/accounts'),
    account: (id) => get(`/api/accounts/${id}`),
    opportunities: () => get('/api/opportunities'),
    alerts: () => get('/api/pipeline/alerts'),
    proposals: (status) => get(`/api/proposals${status ? `?status=${encodeURIComponent(status)}` : ''}`),
    proposal: (id) => get(`/api/proposals/${id}`),
    decide: (id, body) => post(`/api/proposals/${id}/decision`, body),
    runs: () => get('/api/runs'),
    run: (id) => get(`/api/runs/${id}`),
    audit: (limit = 200) => get(`/api/audit?limit=${limit}`),
    verifyAudit: () => get('/api/audit/verify'),
    events: (limit = 100) => get(`/api/events?limit=${limit}`),
    evals: () => get('/api/evals'),
    runEvals: () => post('/api/evals/run'),
    feedback: () => get('/api/feedback'),
    submitLostDealReview: (b) => post('/api/lost-deal-reviews', b),
    demoEnquiry: () => post('/api/demo/enquiry', { enquiry_id: GOLDEN_ENQUIRY_ID }),
    demoReply: () => post('/api/demo/reply', { reply_id: GOLDEN_REPLY_ID }),
    demoAdvance: (seconds) => post('/api/demo/advance', { seconds }),
    demoReset: () => post('/api/demo/reset'),
  };
}

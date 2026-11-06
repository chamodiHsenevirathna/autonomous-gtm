import type {
  AccountDetail, AccountRow, AuditRow, AuditVerifyOut, ConfigOut, DecisionIn, DemoResultOut, EvalSummaryOut,
  EventRow, FeedbackRow, HealthOut, LeadOut, LostDealReviewIn, LostDealReviewOut, OpportunityRow, OverviewOut,
  PipelineAlert, ProposalOut, RunDetail, RunRow,
} from './types';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** Scripted ids for the golden thread (the backend scenario library must accept these). */
export const GOLDEN_ENQUIRY_ID = 'S01-golden-enquiry';
export const GOLDEN_REPLY_ID = 'S01-golden-reply';

export interface Api {
  mode: 'mock' | 'http';
  health(): Promise<HealthOut>;
  config(): Promise<ConfigOut>;
  overview(): Promise<OverviewOut>;
  leads(): Promise<LeadOut[]>;
  accounts(): Promise<AccountRow[]>;
  account(id: number): Promise<AccountDetail>;
  opportunities(): Promise<OpportunityRow[]>;
  alerts(): Promise<PipelineAlert[]>;
  proposals(status?: string): Promise<ProposalOut[]>;
  proposal(id: number): Promise<ProposalOut>;
  decide(id: number, body: DecisionIn): Promise<ProposalOut>;
  runs(): Promise<RunRow[]>;
  run(id: number): Promise<RunDetail>;
  audit(limit?: number): Promise<AuditRow[]>;
  verifyAudit(): Promise<AuditVerifyOut>;
  events(limit?: number): Promise<EventRow[]>;
  evals(): Promise<EvalSummaryOut>;
  runEvals(): Promise<EvalSummaryOut>;
  feedback(): Promise<FeedbackRow[]>;
  submitLostDealReview(body: LostDealReviewIn): Promise<LostDealReviewOut>;
  demoEnquiry(): Promise<DemoResultOut>;
  demoReply(): Promise<DemoResultOut>;
  demoAdvance(seconds: number): Promise<DemoResultOut>;
  demoReset(): Promise<DemoResultOut>;
  /** Mock mode only: corrupt one audit row so the verify button can show a broken chain. */
  mockTamper?(): Promise<void>;
}

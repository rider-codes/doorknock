export type Seniority = "intern" | "entry" | "mid" | "senior" | "staff";

export interface Profile {
  name: string;
  headline: string;
  seniority: Seniority;
  years_experience: number;
  skills: string[];
  experience: { company: string; title: string; start: string; end: string; bullets: string[] }[];
  projects: { name: string; description: string; tech: string[] }[];
  education: string[];
  locations: string[];
}

export interface Brief {
  roles: string[];
  cities: string[];
  countries: string[];
  remote_ok: boolean;
  level: "intern" | "entry" | "mid" | "senior";
  job_type: "full_time" | "intern" | "contract" | "any";
  keywords: string[];
  exclude_keywords: string[];
  title_keywords: string[];
  avoid_titles: string[];
}

export interface Run {
  id: number;
  status: "running" | "done" | "error";
  stage: string;
  detail: Record<string, unknown> & { error?: string; board_errors?: string[]; errors?: string[] };
}

export interface AppState {
  profile: { filename: string; version: number; data: Profile } | null;
  brief: { version: number; data: Brief; history: { role: "user" | "assistant"; content: string }[] };
  counts: { found: number; filtered: number; waiting: number; scored: number; drafts: number };
  setup: { llm: boolean; jev: boolean; people_provider: string; aggregator: boolean; public: boolean; github_url: string; keys: { openrouter: boolean; hunter: boolean; jooble: boolean; adzuna: boolean }; gmail_client_secret: boolean; gmail_connected: boolean };
  freshness: { last_refreshed: string | null; auto_hours: number };
  demo: boolean;
  workspace_days: number;
  allowances: { key: string; label: string; detail: string; left: number; limit: number; unit: string; period: string }[];
  run: Run | null;
}

export interface Signal {
  score: number;
  max: number;
  reason: string;
}

export type JobView = "scored" | "waiting" | "filtered";

export interface JobSummary {
  id: number;
  title: string;
  company: string;
  company_id: number;
  domain: string;
  location: string;
  url: string;
  posted_at: string;
  status: string;
  filter_reason: string;
  sim: number;
  relevance: number | null;
  score: number | null;
  network: number;
  posted_key: string;
  source: string;
  aggregated: boolean;
  last_seen: string;
  people_count: number;
  signals: Record<"role" | "profile" | "skills" | "location" | "seniority", Signal> | null;
  opportunity: number | null;
  verdict: string | null;
  has_people: boolean;
  has_draft: boolean;
}

export interface Person {
  id: number;
  name: string;
  title: string;
  role_type: "recruiter" | "hiring_manager" | "teammate";
  email: string;
  email_status: "verified" | "risky" | "unknown";
  relevance: number;
  why: string;
  source: string;
}

export interface Evidence {
  sentence: string;
  fact_id: string;
  source: "resume" | "posting";
  quote: string;
}

export interface Draft {
  id: number;
  job_id: number;
  person_id: number | null;
  to: string;
  subject: string;
  body: string;
  evidence: Evidence[];
  problems: string[];
  status: "verified" | "needs_review" | "in_gmail";
  in_gmail: boolean;
}

export interface JobDetail extends JobSummary {
  description: string;
  people: Person[];
  draft: Draft | null;
}

export interface Company {
  id: number;
  name: string;
  ats: string;
  slug: string;
  domain: string;
  enabled: boolean;
  last_error: string;
}



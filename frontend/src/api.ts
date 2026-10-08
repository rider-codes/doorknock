import type { AppState, Brief, Company, Draft, JobDetail, JobSummary, JobView, Person, Profile, Run } from "./types";

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError("Cannot reach the Doorknock server. Is the backend running on port 8000?");
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(detail);
  }
  return res.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  state: () => request<AppState>("/api/state"),
  uploadResume: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ filename: string; version: number; data: Profile }>("/api/resume", { method: "POST", body: form });
  },
  saveProfile: (data: Profile) => request("/api/profile", json("PUT", { data })),
  chat: (message: string) =>
    request<{ reply: string; brief: AppState["brief"] }>("/api/brief/chat", json("POST", { message })),
  saveBrief: (data: Brief) => request("/api/brief", json("PUT", { data })),
  companies: () => request<Company[]>("/api/companies"),
  addCompany: (url: string, domain = "") => request<{ duplicate: boolean }>("/api/companies", json("POST", { url, domain })),
  removeCompany: (id: number) => request(`/api/companies/${id}`, { method: "DELETE" }),
  setDomain: (id: number, domain: string) => request(`/api/companies/${id}`, json("PATCH", { domain })),
  startRun: (stages: string[], score_limit = 25) => request<{ run_id: number }>("/api/runs", json("POST", { stages, score_limit })),
  latestRun: () => request<Run | null>("/api/runs/latest"),
  jobs: (view: JobView, sort: "newest" | "best" = "newest") => request<JobSummary[]>(`/api/jobs?view=${view}&sort=${sort}`),
  job: (id: number) => request<JobDetail>(`/api/jobs/${id}`),
  dismiss: (id: number) => request(`/api/jobs/${id}/dismiss`, { method: "POST" }),
  findPeople: (id: number) => request<Person[]>(`/api/jobs/${id}/people`, { method: "POST" }),
  addPerson: (id: number, name: string, title: string, email: string) =>
    request<Person>(`/api/jobs/${id}/people/manual`, json("POST", { name, title, email })),
  writeDraft: (id: number, personId: number | null) =>
    request<Draft>(`/api/jobs/${id}/draft`, json("POST", { person_id: personId })),
  editDraft: (id: number, subject: string, body: string) => request<Draft>(`/api/drafts/${id}`, json("PUT", { subject, body })),
  saveToGmail: (id: number) => request<{ gmail_draft_id: string; to: string }>(`/api/drafts/${id}/gmail`, { method: "POST" }),
  connectGmail: () => request<{ connected: boolean }>("/api/gmail/connect", { method: "POST" }),
};

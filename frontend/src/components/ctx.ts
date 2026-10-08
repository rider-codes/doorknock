import type { AppState } from "../types";
import type { StepKey } from "./FlowDiagram";

export interface Ctx {
  state: AppState;
  refresh: () => Promise<void>;
  notify: (message: string) => void;
  go: (step: StepKey) => void;
  jobId: number | null;
  selectJob: (id: number | null) => void;
  personId: number | null;
  selectPerson: (id: number | null) => void;
}

export const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

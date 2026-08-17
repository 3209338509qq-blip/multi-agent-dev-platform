const BASE = "/api";

export interface Project {
  id: string; name: string; description: string; status: string;
  requirement: string; workspace_path: string; config: Record<string, unknown>;
  created_at: string; updated_at: string;
}

export interface Task {
  id: string; agent_role: string; title: string; description: string;
  status: string; priority: number; retry_count: number; max_retries: number;
  input_data: Record<string, unknown> | null; output_data: Record<string, unknown> | null;
  error: string | null; started_at: string | null; finished_at: string | null;
  created_at: string; dependency_ids: string[];
}

export interface Event {
  type: string; task_id: string | null; payload: Record<string, unknown> | null; ts: string;
}

export async function listProjects(): Promise<Project[]> {
  const r = await fetch(BASE + "/projects");
  return r.json();
}

export async function getProject(id: string): Promise<Project & { tasks: Task[] }> {
  const r = await fetch(BASE + "/projects/" + id);
  return r.json();
}

export async function createProject(data: { name: string; requirement: string; description?: string }): Promise<Project> {
  const r = await fetch(BASE + "/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
  return r.json();
}

export async function runProject(id: string): Promise<{ status: string }> {
  const r = await fetch(BASE + "/projects/" + id + "/run", { method: "POST" });
  return r.json();
}

export async function getEvents(id: string, afterSeq = 0): Promise<Event[]> {
  const r = await fetch(BASE + "/projects/" + id + "/events?after_seq=" + afterSeq);
  return r.json();
}

export function connectWS(projectId: string, onEvent: (e: Event) => void): () => void {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(proto + "//" + window.location.host + "/ws/projects/" + projectId);
  ws.onmessage = (msg) => {
    try { onEvent(JSON.parse(msg.data)); } catch {}
  };
  ws.onerror = () => {};
  return () => ws.close();
}

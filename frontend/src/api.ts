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
  seq: number; type: string; task_id: string | null; payload: Record<string, unknown> | null; ts: string;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `请求失败 (${response.status})`);
  }
  return response.json();
}

export function listProjects(): Promise<Project[]> {
  return request("/projects");
}

export function getProject(id: string): Promise<Project & { tasks: Task[] }> {
  return request("/projects/" + encodeURIComponent(id));
}

export function createProject(data: { name: string; requirement: string; description?: string }): Promise<Project> {
  return request("/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
}

export function runProject(id: string): Promise<{ status: string }> {
  return request("/projects/" + encodeURIComponent(id) + "/run", { method: "POST" });
}

export function cancelProject(id: string): Promise<{ status: string }> {
  return request("/projects/" + encodeURIComponent(id) + "/cancel", { method: "POST" });
}

export function getEvents(id: string, afterSeq = 0): Promise<Event[]> {
  return request("/projects/" + encodeURIComponent(id) + "/events?after_seq=" + afterSeq);
}

export function connectWS(projectId: string, onEvent: (event: Event) => void): () => void {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = protocol + "//" + window.location.host + "/ws/projects/" + encodeURIComponent(projectId);
  let socket: WebSocket;
  let timer: number | undefined;
  let nextSeq = 0;
  let retryDelay = 500;
  let closed = false;

  function connect() {
    socket = new WebSocket(url + "?after_seq=" + nextSeq);
    socket.onopen = () => { retryDelay = 500; };
    socket.onmessage = (message) => {
      let event: Event;
      try {
        event = JSON.parse(message.data);
      } catch {
        return;
      }
      if (!event || !Number.isInteger(event.seq) || event.seq < nextSeq) return;
      nextSeq = event.seq + 1;
      onEvent(event);
    };
    socket.onclose = () => {
      if (closed) return;
      timer = window.setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 5000);
    };
  }

  connect();
  return () => {
    closed = true;
    window.clearTimeout(timer);
    socket.onmessage = null;
    socket.close();
  };
}

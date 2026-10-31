import ProjectArtifacts from "./ProjectArtifacts";
import { useEffect, useState, useCallback, useRef } from "react";
import { getProject, runProject, getEvents, connectWS, type Project, type Task, type Event } from "../api";

const TASK_STATUS: Record<string, { label: string; color: string }> = {
  pending: { label: "等待", color: "bg-slate-600 text-slate-200" },
  running: { label: "执行中", color: "bg-blue-500/30 text-blue-300 animate-pulse" },
  success: { label: "成功", color: "bg-emerald-500/20 text-emerald-300" },
  failed: { label: "失败", color: "bg-red-500/20 text-red-300" },
  retrying: { label: "重试中", color: "bg-yellow-500/20 text-yellow-300 animate-pulse" },
  blocked: { label: "阻塞", color: "bg-orange-500/20 text-orange-300" },
  cancelled: { label: "已取消", color: "bg-slate-500/20 text-slate-400" },
};

const ROLE_EMOJI: Record<string, string> = {
  pm: "\u{1F4CB}", architect: "\u{1F3D7}", backend: "\u2699", frontend: "\u{1F3A8}",
  test: "\u{1F9EA}", review: "\u{1F441}", debug: "\u{1F41B}", git: "\u{1F4E6}",
};

export default function ProjectDetail({ projectId, onBack }: { projectId: string; onBack: () => void }) {
  const [project, setProject] = useState<(Project & { tasks: Task[] }) | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [running, setRunning] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const p = await getProject(projectId);
    setProject(p);
    const evts = await getEvents(projectId);
    setEvents(evts);
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const close = connectWS(projectId, (e) => {
      setEvents(prev => [...prev, e]);
      // 自动刷新任务状态
      if (e.type.startsWith("task_") || e.type.startsWith("project_")) {
        setTimeout(() => load(), 500);
      }
      setTimeout(() => logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" }), 50);
    });
    return close;
  }, [projectId, load]);

  const handleRun = async () => {
    setRunning(true);
    try {
      await runProject(projectId);
      // 开始轮询状态
      const poll = setInterval(async () => {
        const p = await getProject(projectId);
        setProject(p);
        if (["completed", "failed", "cancelled"].includes(p.status)) {
          clearInterval(poll);
          setRunning(false);
        }
      }, 2000);
    } catch { setRunning(false); }
  };

  if (!project) return <div className="text-slate-500 animate-pulse">加载中...</div>;

  const tasks = project.tasks || [];
  const doneCount = tasks.filter(t => t.status === "success").length;

  return (
    <div>
      <button onClick={onBack} className="text-sm text-slate-400 hover:text-slate-200 mb-4 transition">&larr; 返回列表</button>

      {/* 项目头部 */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 mb-4">
        <div className="flex items-center gap-3 mb-2">
          <h1 className="text-xl font-bold">{project.name}</h1>
          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-300">{project.status}</span>
          {project.status === "planning" && (
            <button onClick={handleRun} disabled={running} className="ml-auto px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-sm font-medium disabled:opacity-50 transition">
              {running ? "Agent 执行中..." : "\u25B6 运行 Agent"}
            </button>
          )}
          {["completed", "failed"].includes(project.status) && (
            <span className="ml-auto text-sm text-slate-400">{doneCount}/{tasks.length} tasks completed</span>
          )}
        </div>
        <p className="text-sm text-slate-400">{project.requirement}</p>
      </div>

      <ProjectArtifacts key={projectId} projectId={projectId} />

      <div className="grid lg:grid-cols-5 gap-4 mt-4">
        {/* 任务面板 (3/5) */}
        <section className="lg:col-span-3 rounded-xl border border-slate-800 bg-slate-900 p-4">
          <h2 className="font-semibold mb-3 text-sm flex items-center gap-2">
            任务
            <span className="text-xs text-slate-500">({doneCount}/{tasks.length})</span>
            {tasks.length > 0 && (
              <div className="ml-auto flex gap-1">
                {tasks.map(t => (
                  <div key={t.id} className={"w-2 h-2 rounded-full " + (t.status === "success" ? "bg-emerald-400" : t.status === "running" ? "bg-blue-400 animate-pulse" : t.status === "failed" ? "bg-red-400" : "bg-slate-600")} />
                ))}
              </div>
            )}
          </h2>
          <div className="space-y-2">
            {tasks.map(t => {
              const s = TASK_STATUS[t.status] || TASK_STATUS.pending;
              return (
                <div key={t.id} className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-950 p-3">
                  <span className="text-lg">{ROLE_EMOJI[t.agent_role] || "\u2022"}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">{t.title}</div>
                    <div className="text-xs text-slate-500">{t.agent_role} &middot; {t.dependency_ids.length > 0 ? "deps: " + t.dependency_ids.length : "root"}</div>
                    {t.error && <div className="text-xs text-red-400 mt-1 truncate">{t.error}</div>}
                  </div>
                  <span className={"text-xs px-2 py-0.5 rounded-full whitespace-nowrap " + s.color}>{s.label}</span>
                  {t.retry_count > 0 && <span className="text-xs text-yellow-500">\u00D7{t.retry_count}</span>}
                </div>
              );
            })}
            {tasks.length === 0 && <p className="text-slate-600 text-sm text-center py-8">等待 PM Agent 创建任务...</p>}
          </div>
        </section>

        {/* 实时事件日志 (2/5) */}
        <section className="lg:col-span-2 rounded-xl border border-slate-800 bg-slate-900 p-4">
          <h2 className="font-semibold mb-3 text-sm">实时事件 <span className="text-xs text-slate-500">({events.length})</span></h2>
          <div ref={logRef} className="h-96 overflow-y-auto space-y-0.5 font-mono text-xs">
            {events.map((e, i) => (
              <div key={i} className="flex gap-2 py-0.5 hover:bg-slate-800/50 px-1 rounded">
                <span className="text-slate-600 shrink-0 w-14">{new Date(e.ts).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
                <span className={(e.type.includes("fail") ? "text-red-400" : e.type.includes("complete") ? "text-emerald-400" : e.type.includes("start") ? "text-blue-400" : "text-slate-300") + " truncate"}>{e.type}</span>
              </div>
            ))}
            {events.length === 0 && <p className="text-slate-600 text-center py-8">暂无事件，运行 Agent 后实时显示</p>}
          </div>
        </section>
      </div>
    </div>
  );
}

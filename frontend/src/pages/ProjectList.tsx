import { useEffect, useState, useCallback } from "react";
import { listProjects, createProject, type Project } from "../api";

const STATUS_COLORS: Record<string, string> = {
  planning: "bg-blue-500/20 text-blue-300",
  architecting: "bg-purple-500/20 text-purple-300",
  coding: "bg-yellow-500/20 text-yellow-300",
  testing: "bg-orange-500/20 text-orange-300",
  reviewing: "bg-cyan-500/20 text-cyan-300",
  completed: "bg-emerald-500/20 text-emerald-300",
  failed: "bg-red-500/20 text-red-300",
  cancelled: "bg-slate-500/20 text-slate-400",
};

export default function ProjectList({ onOpen }: { onOpen: (id: string) => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [req, setReq] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => { setProjects(await listProjects()); }, []);
  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    if (!name.trim() || !req.trim()) return;
    setLoading(true);
    try {
      const p = await createProject({ name, requirement: req });
      setName(""); setReq(""); setShowCreate(false);
      onOpen(p.id);
    } finally { setLoading(false); }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold">项目列表</h1>
        <button onClick={() => setShowCreate(true)} className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-sm font-medium transition">+ 新建项目</button>
      </div>

      {showCreate && (
        <div className="mb-6 rounded-xl border border-slate-700 bg-slate-900 p-4">
          <h3 className="font-semibold mb-3">新建项目</h3>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="项目名称" className="w-full mb-2 px-3 py-2 rounded bg-slate-800 border border-slate-700 text-sm" />
          <textarea value={req} onChange={e => setReq(e.target.value)} placeholder="描述你的软件需求..." rows={3} className="w-full mb-2 px-3 py-2 rounded bg-slate-800 border border-slate-700 text-sm" />
          <div className="flex gap-2">
            <button onClick={handleCreate} disabled={loading} className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-500 text-sm font-medium disabled:opacity-50">{loading ? "创建中..." : "创建并开始"}</button>
            <button onClick={() => setShowCreate(false)} className="px-4 py-2 rounded bg-slate-700 hover:bg-slate-600 text-sm">取消</button>
          </div>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {projects.map(p => (
          <button key={p.id} onClick={() => onOpen(p.id)} className="text-left rounded-xl border border-slate-800 bg-slate-900 p-4 hover:border-slate-600 transition">
            <div className="flex items-center gap-2 mb-2">
              <span className={"text-xs px-2 py-0.5 rounded-full " + (STATUS_COLORS[p.status] || "bg-slate-700 text-slate-300")}>{p.status}</span>
            </div>
            <h3 className="font-semibold text-sm mb-1">{p.name}</h3>
            <p className="text-xs text-slate-400 line-clamp-2">{p.requirement}</p>
            <p className="text-xs text-slate-600 mt-2">{new Date(p.created_at).toLocaleString("zh-CN")}</p>
          </button>
        ))}
        {projects.length === 0 && <p className="text-slate-500 text-sm col-span-full text-center py-12">暂无项目，点击右上角创建第一个</p>}
      </div>
    </div>
  );
}

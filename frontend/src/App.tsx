import { useEffect, useState } from "react";

interface Health {
  status: string;
  service: string;
  version: string;
  sandbox_backend: string;
}

function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) =>
        r.ok ? (r.json() as Promise<Health>) : Promise.reject(new Error("HTTP " + r.status))
      )
      .then(setHealth)
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-8 py-6">
        <h1 className="text-2xl font-bold">Multi-Agent Dev Platform</h1>
        <p className="mt-1 text-sm text-slate-400">
          输入软件需求，自动完成 需求分析 → 架构 → 编码 → 测试 → Review → Git 交付 的闭环
        </p>
      </header>
      <main className="mx-auto max-w-4xl px-8 py-10">
        <section className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="mb-3 text-lg font-semibold">系统状态</h2>
          {error && (
            <p className="rounded-lg bg-red-950/60 px-4 py-3 text-sm text-red-300">
              后端未连接：{error}（请先运行 make dev 启动后端）
            </p>
          )}
          {health && (
            <dl className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
              <div>
                <dt className="text-slate-500">状态</dt>
                <dd className="font-mono text-emerald-400">{health.status}</dd>
              </div>
              <div>
                <dt className="text-slate-500">服务</dt>
                <dd className="font-mono">{health.service}</dd>
              </div>
              <div>
                <dt className="text-slate-500">版本</dt>
                <dd className="font-mono">{health.version}</dd>
              </div>
              <div>
                <dt className="text-slate-500">沙箱后端</dt>
                <dd className="font-mono">{health.sandbox_backend}</dd>
              </div>
            </dl>
          )}
        </section>
        <p className="mt-8 text-sm text-slate-500">
          项目列表与项目详情 Dashboard 在 Phase 10 接入（WebSocket 实时 Agent 日志）。
          架构设计见仓库 docs/architecture.md。
        </p>
      </main>
    </div>
  );
}

export default App;

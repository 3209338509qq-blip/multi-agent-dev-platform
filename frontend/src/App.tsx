import { useState, useEffect, useCallback } from "react";
import ProjectList from "./pages/ProjectList";
import ProjectDetail from "./pages/ProjectDetail";
import "./index.css";

type Page = { type: "home" } | { type: "project"; id: string };

function useHashRoute(): [Page, (page: Page) => void] {
  const parse = (): Page => {
    const hash = window.location.hash.replace(/^#\/?/, "");
    const match = hash.match(/^projects\/([^/]+)$/);
    return match ? { type: "project", id: match[1] } : { type: "home" };
  };
  const [page, setPage] = useState<Page>(parse);
  useEffect(() => {
    const handler = () => setPage(parse());
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  const navigate = useCallback((p: Page) => {
    window.location.hash = p.type === "home" ? "/" : "/projects/" + p.id;
  }, []);
  return [page, navigate];
}

export default function App() {
  const [page, navigate] = useHashRoute();
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="sticky top-0 z-50 border-b border-slate-800 bg-slate-950/90 backdrop-blur px-6 py-3 flex items-center gap-4">
        <button onClick={() => navigate({ type: "home" })} className="text-lg font-bold hover:text-blue-400 transition">MADP</button>
        <span className="text-xs text-slate-500">Multi-Agent Dev Platform</span>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        {page.type === "home" && <ProjectList onOpen={(id) => navigate({ type: "project", id })} />}
        {page.type === "project" && <ProjectDetail projectId={page.id} onBack={() => navigate({ type: "home" })} />}
      </main>
    </div>
  );
}

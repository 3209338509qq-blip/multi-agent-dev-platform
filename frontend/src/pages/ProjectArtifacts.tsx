import { useEffect, useRef, useState } from "react";
import { listArtifacts, previewArtifact, downloadArtifacts, type Artifact, type ArtifactPreview } from "../api";

export default function ProjectArtifacts({ projectId }: { projectId: string }) {
  const [files, setFiles] = useState<Artifact[]>([]);
  const [preview, setPreview] = useState<ArtifactPreview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const request = useRef(0);
  const listRequest = useRef(0);
  async function refresh() {
    const current = ++listRequest.current;
    ++request.current;
    setPreview(null); setPreviewing(false); setLoading(true); setError("");
    try {
      const result = await listArtifacts(projectId);
      if (current === listRequest.current) setFiles(result.files);
    } catch (e) {
      if (current === listRequest.current) { setFiles([]); setError(String(e)); }
    } finally { if (current === listRequest.current) setLoading(false); }
  }
  useEffect(() => {
    refresh();
    return () => { ++request.current; ++listRequest.current; };
  }, [projectId]);
  async function select(path: string) {
    const current = ++request.current;
    setPreview(null); setError(""); setPreviewing(true);
    try {
      const result = await previewArtifact(projectId, path);
      if (current === request.current) setPreview(result);
    } catch (e) { if (current === request.current) setError(String(e)); }
    finally { if (current === request.current) setPreviewing(false); }
  }
  async function download() {
    setDownloading(true); setError("");
    try { await downloadArtifacts(projectId); }
    catch (e) { setError(String(e)); }
    finally { setDownloading(false); }
  }
  return <section className="rounded-xl border border-slate-800 bg-slate-900 p-4 mt-4">
    <div className="flex gap-4 items-center mb-3">
      <h2 className="font-semibold">成果文件</h2>
      <button onClick={refresh} disabled={loading} className="text-blue-300 disabled:opacity-50">{loading ? "加载中…" : "刷新文件"}</button>
      <button onClick={download} disabled={loading || downloading || !files.length} className="ml-auto text-emerald-300 disabled:opacity-50">{downloading ? "打包中…" : "下载 ZIP"}</button>
    </div>
    <p className="text-xs text-slate-400 mb-3">当前工作区文件；运行中可能变化，不代表已通过验收。仅预览 UTF-8 文本（≤256 KiB）。</p>
    {error && <p role="alert" className="text-red-300 mb-3">{error}</p>}
    <div className="grid md:grid-cols-3 gap-4">
      <div className="max-h-96 overflow-auto">
        {!loading && !files.length && <p className="text-slate-400">暂无可用成果文件</p>}
        {files.map(file => <button key={file.path} onClick={() => select(file.path)} className="block text-left break-all text-sm p-2 hover:bg-slate-800 w-full" aria-pressed={preview?.path === file.path}>
          {file.path} <span className="text-slate-500">({file.size} B)</span>
        </button>)}
      </div>
      <div className="md:col-span-2 min-w-0">
        <p className="text-sm text-slate-400 mb-2">{previewing ? "读取中…" : preview?.path || "选择文件查看代码"}</p>
        {preview && <pre className="overflow-auto max-h-96 bg-slate-950 p-3 text-xs"><code>{preview.content}</code></pre>}
      </div>
    </div>
  </section>;
}

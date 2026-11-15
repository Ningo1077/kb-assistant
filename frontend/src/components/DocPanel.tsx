import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Doc, DocStatus } from "../types";
import { STATUS_LABEL } from "../types";

const ACCEPT = ".pdf,.docx,.md,.txt,.csv";
const PENDING: DocStatus[] = ["pending", "parsing", "embedding"];

function badgeClass(s: DocStatus): string {
  if (s === "ready") return "badge ok";
  if (s === "failed") return "badge err";
  if (s === "pending") return "badge";
  return "badge warn";
}

function humanSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export default function DocPanel({ kbId, onChanged }: { kbId: number; onChanged: () => void }) {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState("");
  const timer = useRef<number | null>(null);

  const reload = useCallback(async () => {
    try {
      setDocs(await api.listDocs(kbId));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [kbId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // 有文档还在入库时轮询状态，全部结束后停止并刷新侧边栏统计
  useEffect(() => {
    const processing = docs.some((d) => PENDING.includes(d.status));
    if (!processing) {
      if (timer.current) window.clearInterval(timer.current);
      return;
    }
    timer.current = window.setInterval(() => {
      void reload();
    }, 1200);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [docs, reload]);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setError("");
    try {
      for (const file of Array.from(files)) {
        await api.uploadDoc(kbId, file);
      }
      await reload();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(doc: Doc) {
    if (!window.confirm(`删除文档「${doc.filename}」及其全部分块？`)) return;
    await api.deleteDoc(kbId, doc.id);
    setDocs((prev) => prev.filter((d) => d.id !== doc.id));
    onChanged();
  }

  return (
    <div
      className={`doc-panel${dragOver ? " drag-over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        void upload(e.dataTransfer.files);
      }}
    >
      <div className="doc-toolbar">
        <label>
          <input
            type="file"
            accept={ACCEPT}
            multiple
            style={{ display: "none" }}
            onChange={(e) => {
              void upload(e.target.files);
              e.target.value = "";
            }}
          />
          <span className="ghost" style={{ display: "inline-block", padding: "8px 14px", border: "1px solid var(--accent)", borderRadius: 10, color: "var(--accent)", cursor: busy ? "wait" : "pointer" }}>
            {busy ? "上传中…" : "⬆ 选择文件上传"}
          </span>
        </label>
        <span className="hint">支持 PDF / DOCX / MD / TXT / CSV，单文件 ≤ 20MB；也可直接把文件拖到本面板</span>
      </div>
      {error && <div className="error-box">{error}</div>}
      <div className="doc-table">
        {docs.length === 0 ? (
          <div className="empty-tip">还没有文档，上传后即可开始提问</div>
        ) : (
          docs.map((d) => (
            <div className="doc-row" key={d.id}>
              <span className="name">
                {d.filename}
                {d.status === "failed" && <span className="doc-error">　{d.error_msg}</span>}
              </span>
              <span className="meta">{humanSize(d.size_bytes)}</span>
              <span className="meta">
                {d.page_count} 页 · {d.chunk_count} 块
              </span>
              <span className={badgeClass(d.status)}>
                {PENDING.includes(d.status) ? "⟳ " : ""}
                {STATUS_LABEL[d.status]}
              </span>
              <button className="plain" onClick={() => void remove(d)}>
                删除
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

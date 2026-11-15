import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { KB, User } from "../types";
import DocPanel from "../components/DocPanel";
import ChatPanel from "../components/ChatPanel";

export default function Workspace({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [kbs, setKbs] = useState<KB[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [tab, setTab] = useState<"docs" | "chat">("docs");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    try {
      const list = await api.listKbs();
      setKbs(list);
      setActiveId((cur) => cur ?? list[0]?.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function createKb() {
    if (!newName.trim()) return;
    try {
      const kb = await api.createKb(newName.trim(), "");
      setNewName("");
      setCreating(false);
      setKbs((prev) => [kb, ...prev]);
      setActiveId(kb.id);
      setTab("docs");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function deleteKb(id: number) {
    if (!window.confirm("删除该知识库会同时删除其中全部文档与向量，确定？")) return;
    await api.deleteKb(id);
    setKbs((prev) => prev.filter((k) => k.id !== id));
    setActiveId((cur) => (cur === id ? null : cur));
  }

  const active = kbs.find((k) => k.id === activeId) ?? null;

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">📚 私有知识库</div>
        <button onClick={() => setCreating(true)}>＋ 新建知识库</button>
        {creating && (
          <div style={{ display: "flex", gap: 6 }}>
            <input
              autoFocus
              value={newName}
              placeholder="知识库名称"
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void createKb()}
            />
            <button className="ghost" onClick={() => void createKb()}>
              确认
            </button>
          </div>
        )}
        <div className="kb-list">
          {kbs.length === 0 && !creating && <div className="empty-tip">还没有知识库，先新建一个</div>}
          {kbs.map((kb) => (
            <button
              key={kb.id}
              className={`kb-item${kb.id === activeId ? " active" : ""}`}
              onClick={() => setActiveId(kb.id)}
            >
              {kb.name}
              <span className="desc">
                文档 <b>{kb.document_count}</b> · 分块 <b>{kb.chunk_count}</b>
              </span>
            </button>
          ))}
        </div>
        <div className="sidebar-footer">
          {user.display_name || user.email}
          <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
            <button className="plain" onClick={() => void deleteKb(activeId ?? -1)} disabled={!active}>
              删除当前库
            </button>
            <button className="plain" onClick={onLogout}>
              退出
            </button>
          </div>
        </div>
      </aside>

      <section className="main">
        <div className="main-header">
          <h2>{active ? active.name : "未选择知识库"}</h2>
          <div className="tabs">
            <button className={`tab${tab === "docs" ? " active" : ""}`} onClick={() => setTab("docs")}>
              文档管理
            </button>
            <button className={`tab${tab === "chat" ? " active" : ""}`} onClick={() => setTab("chat")}>
              智能问答
            </button>
          </div>
        </div>
        <div className="main-body">
          {error && <div className="error-box">{error}</div>}
          {!active ? (
            <div className="kb-empty">左侧新建或选择一个知识库开始使用</div>
          ) : tab === "docs" ? (
            <DocPanel kbId={active.id} onChanged={reload} />
          ) : (
            <ChatPanel kbId={active.id} />
          )}
        </div>
      </section>
    </div>
  );
}

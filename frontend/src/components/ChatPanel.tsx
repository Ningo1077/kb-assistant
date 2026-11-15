import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, streamChat } from "../api";
import type { Citation, Conversation, Message } from "../types";

export default function ChatPanel({ kbId }: { kbId: number }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [convId, setConvId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");
  const [openSnippet, setOpenSnippet] = useState<string | null>(null);
  const [voted, setVoted] = useState<Record<number, number>>({});
  const bottomRef = useRef<HTMLDivElement>(null);

  const reloadConvs = useCallback(async () => {
    try {
      setConvs(await api.listConversations(kbId));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [kbId]);

  useEffect(() => {
    setMessages([]);
    setConvId(null);
    setError("");
    setOpenSnippet(null);
    void reloadConvs();
  }, [kbId, reloadConvs]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function openConv(id: number) {
    try {
      setConvId(id);
      setMessages(await api.listMessages(id));
      setOpenSnippet(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function newConversation() {
    setConvId(null);
    setMessages([]);
    setOpenSnippet(null);
  }

  function patchLastAssistant(patch: (m: Message) => Message) {
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      const next = prev.slice();
      const last = next[next.length - 1];
      if (last && last.role === "assistant") next[next.length - 1] = patch(last);
      return next;
    });
  }

  async function send() {
    const question = input.trim();
    if (!question || streaming) return;
    setInput("");
    setStreaming(true);
    setError("");
    setOpenSnippet(null);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: question },
      { role: "assistant", content: "", citations: [] },
    ]);

    try {
      await streamChat({ kb_id: kbId, question, conversation_id: convId }, (e) => {
        if (e.type === "meta") {
          if (e.conversation_id) setConvId(e.conversation_id);
          patchLastAssistant((m) => ({ ...m, citations: e.citations ?? [] }));
        } else if (e.type === "delta") {
          patchLastAssistant((m) => ({ ...m, content: m.content + (e.content ?? "") }));
        } else if (e.type === "done") {
          patchLastAssistant((m) => ({ ...m, id: e.message_id ?? undefined, latency_ms: e.latency_ms }));
        } else if (e.type === "error") {
          setError(e.message ?? "生成失败");
        }
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStreaming(false);
      void reloadConvs();
    }
  }

  async function vote(messageId: number, rating: number) {
    await api.feedback(messageId, rating);
    setVoted((prev) => ({ ...prev, [messageId]: rating }));
  }

  function toggleSnippet(msgKey: number, cite: Citation) {
    const key = `${msgKey}-${cite.index}`;
    setOpenSnippet((cur) => (cur === key ? null : key));
  }

  /** 从提问中提取关键词：去虚词后，对每个词段做最长子串匹配，且必须真实出现在命中片段里 */
  function extractKeywords(question: string, corpus: string): string[] {
    if (!question || !corpus) return [];
    const STOP =
      /[，。！？、：；,.!?:;?（）()《》“”"'`\s\n这那有是了吗呢啊吧的啦么多少什么怎么哪些哪几多久如何请帮我告诉一下可以能否想需要看看查查找]/;
    const lowerCorpus = corpus.toLowerCase();
    const tokens = [...new Set(question.split(STOP).map((t) => t.trim()).filter((t) => t.length >= 2))];
    const picked: string[] = [];
    const dup = (s: string) => {
      const l = s.toLowerCase();
      return picked.some((p) => {
        const lp = p.toLowerCase();
        return lp === l || lp.includes(l) || l.includes(lp);
      });
    };
    for (const token of tokens) {
      let i = 0;
      while (i < token.length - 1 && picked.length < 6) {
        let len = token.length - i;
        let hitLen = 0;
        while (len >= 2) {
          if (lowerCorpus.includes(token.slice(i, i + len).toLowerCase())) {
            hitLen = len;
            break;
          }
          len--;
        }
        if (hitLen >= 2) {
          const word = token.slice(i, i + hitLen);
          if (!dup(word)) picked.push(word);
          i += hitLen;
        } else {
          i++;
        }
      }
    }
    return picked;
  }

  function markKeywords(text: string, keywords: string[]): ReactNode[] {
    if (!keywords.length || !text) return [text];
    const esc = keywords.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const re = new RegExp(`(${esc.join("|")})`, "gi");
    return text.split(re).map((seg, j) =>
      keywords.some((k) => k.toLowerCase() === seg.toLowerCase()) ? (
        <mark key={j} className="kw-hl">
          {seg}
        </mark>
      ) : (
        seg
      )
    );
  }

  function renderRich(text: string, keywords: string[]): ReactNode[] {
    // 解析 **加粗**（智能回答的关键信息标记），内部不再叠加关键词高亮
    return text.split(/(\*\*[^*]+\*\*)/g).map((p, i) => {
      if (/^\*\*[^*]+\*\*$/.test(p)) {
        return (
          <strong key={`b${i}`} className="ans-hl">
            {p.slice(2, -2)}
          </strong>
        );
      }
      return <span key={`t${i}`}>{markKeywords(p, keywords)}</span>;
    });
  }

  function renderContent(content: string, citations: Citation[] | null | undefined, msgKey: number, question: string) {
    const corpus = (citations ?? []).map((c) => c.snippet).join("\n");
    const keywords = extractKeywords(question, corpus);
    const parts = content.split(/(\[\d+\])/g);
    return parts.map((part, i) => {
      const m = part.match(/^\[(\d+)\]$/);
      if (m) {
        const idx = Number(m[1]);
        const cite = citations?.find((c) => c.index === idx);
        if (!cite) return <span key={i}>{part}</span>;
        return (
          <sup key={i} className="ref" onClick={() => toggleSnippet(msgKey, cite)} title={`${cite.filename} 第${cite.page_no}页`}>
            [{idx}]
          </sup>
        );
      }
      return <span key={i}>{renderRich(part, keywords)}</span>;
    });
  }

  return (
    <div className="chat-panel">
      <div className="chat-toolbar">
        <select
          value={convId ?? ""}
          onChange={(e) => (e.target.value ? void openConv(Number(e.target.value)) : newConversation())}
          style={{ width: 220 }}
        >
          <option value="">— 新对话 —</option>
          {convs.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
        <button className="plain" onClick={newConversation}>
          ＋ 新对话
        </button>
        <span style={{ flex: 1 }} />
        {streaming && <span className="stream-dot">● 正在生成…</span>}
      </div>

      {error && <div className="error-box">{error}</div>}

      <div className="chat-history">
        {messages.length === 0 && (
          <div className="empty-tip">向知识库提问，例如：“温度超过多少度会触发告警？”</div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="bubble">
              {m.role === "assistant"
                ? renderContent(
                    m.content || (streaming && i === messages.length - 1 ? "…" : ""),
                    m.citations,
                    i,
                    messages[i - 1]?.role === "user" ? (messages[i - 1].content ?? "") : ""
                  )
                : m.content}
            </div>
            {m.role === "assistant" && m.citations && m.citations.length > 0 && (
              <div className="cites">
                {m.citations.map((c) => (
                  <div key={c.index} style={{ display: "flex", flexDirection: "column" }}>
                    <button className="cite-chip" onClick={() => toggleSnippet(i, c)}>
                      [{c.index}] {c.filename} · 第{c.page_no}页
                    </button>
                    {openSnippet === `${i}-${c.index}` && <div className="snippet-pop">{c.snippet}</div>}
                  </div>
                ))}
              </div>
            )}
            {m.role === "assistant" && m.latency_ms != null && (
              <div className="latency">
                耗时 {m.latency_ms}ms
                {m.id != null && voted[m.id] === undefined && (
                  <>
                    <button className="plain" style={{ padding: "0 6px" }} onClick={() => void vote(m.id!, 1)}>
                      有用
                    </button>
                    <button className="plain" style={{ padding: "0 6px" }} onClick={() => void vote(m.id!, -1)}>
                      无用
                    </button>
                  </>
                )}
                {m.id != null && voted[m.id] != null && <span>已反馈</span>}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input">
        <textarea
          value={input}
          placeholder="输入问题，Ctrl+Enter 发送"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void send();
          }}
        />
        <button onClick={() => void send()} disabled={streaming || !input.trim()}>
          发送
        </button>
      </div>
    </div>
  );
}

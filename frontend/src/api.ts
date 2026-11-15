import type { Citation, Conversation, Doc, KB, Message, User } from "./types";

const TOKEN_KEY = "kb_token";

// Web 端走 Vite 代理（相对路径）；桌面端构建时注入 VITE_API_BASE=http://127.0.0.1:8000
export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(t: string): void {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  return getToken() ? { Authorization: `Bearer ${getToken()}`, ...extra } : { ...extra };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + path, { ...init, headers: authHeaders(init?.headers as Record<string, string>) });
  if (res.status === 204) return undefined as T;
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  async register(email: string, password: string, displayName: string) {
    const r = await request<{ access_token: string; user: User }>("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, display_name: displayName }),
    });
    setToken(r.access_token); // 注册即登录，与 login 保持一致
    return r;
  },
  async login(email: string, password: string) {
    const r = await request<{ access_token: string; user: User }>("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    setToken(r.access_token);
    return r;
  },
  me: () => request<User>("/api/auth/me"),
  logout: () => setToken(""),

  listKbs: () => request<KB[]>("/api/kbs"),
  createKb: (name: string, description: string) =>
    request<KB>("/api/kbs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description }),
    }),
  deleteKb: (id: number) => request<void>(`/api/kbs/${id}`, { method: "DELETE" }),

  listDocs: (kbId: number) => request<Doc[]>(`/api/kbs/${kbId}/documents`),
  uploadDoc: (kbId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Doc>(`/api/kbs/${kbId}/documents`, { method: "POST", body: form });
  },
  deleteDoc: (kbId: number, docId: number) =>
    request<void>(`/api/kbs/${kbId}/documents/${docId}`, { method: "DELETE" }),

  listConversations: (kbId: number) => request<Conversation[]>(`/api/chat/conversations?kb_id=${kbId}`),
  listMessages: (convId: number) => request<Message[]>(`/api/chat/conversations/${convId}/messages`),
  deleteConversation: (convId: number) =>
    request<void>(`/api/chat/conversations/${convId}`, { method: "DELETE" }),
  feedback: (messageId: number, rating: number) =>
    request<{ ok: boolean }>("/api/chat/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_id: messageId, rating }),
    }),
};

export interface ChatEvent {
  type: "meta" | "delta" | "done" | "error";
  conversation_id?: number;
  citations?: Citation[];
  content?: string;
  message_id?: number | null;
  latency_ms?: number;
  message?: string;
}

export async function streamChat(
  payload: { kb_id: number; question: string; conversation_id?: number | null },
  onEvent: (e: ChatEvent) => void,
): Promise<void> {
  const res = await fetch(API_BASE + "/api/chat", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (!res.ok || !res.body) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const line = chunk.trim();
      if (!line.startsWith("data:")) continue;
      try {
        onEvent(JSON.parse(line.slice(5).trim()) as ChatEvent);
      } catch {
        // 跳过坏帧，不能让一帧坏数据中断整个回答
      }
    }
  }
}

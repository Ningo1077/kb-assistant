export interface User {
  id: number;
  email: string;
  display_name: string;
  role: string;
}

export interface KB {
  id: number;
  name: string;
  description: string;
  document_count: number;
  chunk_count: number;
  created_at: string;
}

export type DocStatus = "pending" | "parsing" | "embedding" | "ready" | "failed";

export interface Doc {
  id: number;
  kb_id: number;
  filename: string;
  size_bytes: number;
  status: DocStatus;
  page_count: number;
  chunk_count: number;
  error_msg: string;
  created_at: string;
}

export interface Citation {
  index: number;
  chunk_id: number;
  doc_id: number;
  filename: string;
  page_no: number;
  snippet: string;
  score: number;
  similarity: number;
}

export interface Message {
  id?: number;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[] | null;
  latency_ms?: number;
}

export interface Conversation {
  id: number;
  kb_id: number;
  title: string;
  updated_at: string;
}

export const STATUS_LABEL: Record<DocStatus, string> = {
  pending: "排队中",
  parsing: "解析中",
  embedding: "向量化中",
  ready: "已就绪",
  failed: "失败",
};

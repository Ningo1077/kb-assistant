import { useState } from "react";
import { api } from "../api";
import type { User } from "../types";

export default function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const r =
        mode === "login"
          ? await api.login(email.trim(), password)
          : await api.register(email.trim(), password, displayName.trim());
      onLogin(r.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <h1>私有知识库问答助手</h1>
        <p className="sub">文档不出本机 · 回答必须标注出处</p>
        {error && <div className="error-box">{error}</div>}
        <div>
          <label>邮箱</label>
          <input type="text" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" required />
        </div>
        <div>
          <label>密码</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="至少 6 位" minLength={6} required />
        </div>
        {mode === "register" && (
          <div>
            <label>昵称（选填）</label>
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="怎么称呼你" />
          </div>
        )}
        <button type="submit" disabled={busy}>
          {busy ? "请稍候…" : mode === "login" ? "登录" : "注册并登录"}
        </button>
        <div className="login-switch">
          {mode === "login" ? (
            <>
              还没有账号？<a onClick={() => setMode("register")}>注册一个</a>
            </>
          ) : (
            <>
              已有账号？<a onClick={() => setMode("login")}>直接登录</a>
            </>
          )}
        </div>
      </form>
    </div>
  );
}

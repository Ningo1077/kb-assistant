import { useEffect, useState } from "react";
import Login from "./pages/Login";
import Workspace from "./pages/Workspace";
import { api, getToken } from "./api";
import type { User } from "./types";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState<boolean>(Boolean(getToken()));

  useEffect(() => {
    if (!getToken()) return;
    api
      .me()
      .then(setUser)
      .catch(() => api.logout())
      .finally(() => setChecking(false));
  }, []);

  if (checking) return <div className="page-loading">正在恢复登录状态…</div>;

  return user ? (
    <Workspace
      user={user}
      onLogout={() => {
        api.logout();
        setUser(null);
      }}
    />
  ) : (
    <Login onLogin={setUser} />
  );
}

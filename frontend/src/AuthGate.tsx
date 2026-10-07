import { useEffect, useState, type ReactNode } from "react";
import { api } from "./api";

export default function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<{
    required: boolean;
    user: { username: string } | null;
  } | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = () =>
    api<{ required: boolean; user: { username: string } | null }>(
      "/auth/me",
    ).then(setSession);
  useEffect(() => {
    refresh().catch(() => setError("서버 연결을 확인하고 새로고침해 주세요."));
  }, []);
  async function submit(register: boolean) {
    setBusy(true);
    setError("");
    try {
      await api(`/auth/${register ? "register" : "login"}`, "POST", {
        username,
        password,
      });
      setPassword("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "로그인 실패");
    } finally {
      setBusy(false);
    }
  }
  if (!session || (session.required && !session.user))
    return (
      <main className="login-screen">
        <section className="panel">
          <h1>PATH · 나의 졸업 로드맵</h1>
          <p>이 앱 전용 계정입니다. 학교 아이디·비밀번호를 입력하지 마세요.</p>
          {error && <p role="alert">{error}</p>}
          {session && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void submit(false);
              }}
            >
              <fieldset disabled={busy}>
                <label>
                  앱 계정 이름
                  <input
                    autoComplete="username"
                    value={username}
                    pattern="[a-zA-Z0-9_-]{3,40}"
                    required
                    onChange={(e) => setUsername(e.target.value)}
                  />
                </label>
                <label>
                  앱 비밀번호 (10자 이상)
                  <input
                    type="password"
                    autoComplete="current-password"
                    minLength={10}
                    maxLength={128}
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </label>
                <div className="button-row">
                  <button className="primary">로그인</button>
                  <button type="button" onClick={() => void submit(true)}>
                    새 계정 만들기
                  </button>
                </div>
              </fieldset>
            </form>
          )}
        </section>
      </main>
    );
  return (
    <>
      {session.required && (
        <div className="session-bar">
          <span>{session.user?.username} · 계정별 저장</span>
          <button
            onClick={async () => {
              if (
                !window.confirm(
                  "저장하지 않은 입력은 사라집니다. 로그아웃할까요?",
                )
              )
                return;
              await api("/auth/logout", "POST");
              setSession({ required: true, user: null });
            }}
          >
            로그아웃
          </button>
        </div>
      )}
      {children}
    </>
  );
}

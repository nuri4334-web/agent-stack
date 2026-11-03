import { useEffect, useState } from 'react';
import { API_URL, askQuestion, getCurrentUser, login, logout } from './api';

function formatLocalTime(isoString) {
  if (!isoString) return '';
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString;
  return date.toLocaleString();
}

export default function App() {
  // Session state (kept only in React memory, never in localStorage/sessionStorage)
  const [currentUser, setCurrentUser] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);

  // Page navigation: 'login' | 'chat' | 'panel'
  const [activePage, setActivePage] = useState('login');
  const [profileOpen, setProfileOpen] = useState(false);

  // Login form state
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [lockoutSecondsLeft, setLockoutSecondsLeft] = useState(0);

  // Chat flow state
  const [question, setQuestion] = useState('');
  const [sentQuestion, setSentQuestion] = useState('');
  const [typing, setTyping] = useState(false);
  const [answerData, setAnswerData] = useState(null);
  const [errorInfo, setErrorInfo] = useState(null);

  // Check active session on startup
  useEffect(() => {
    let cancelled = false;
    async function checkSession() {
      try {
        const user = await getCurrentUser();
        if (cancelled) return;
        if (user) {
          setCurrentUser(user);
          setActivePage('chat');
        } else {
          setCurrentUser(null);
          setActivePage('login');
        }
      } catch {
        if (!cancelled) {
          setCurrentUser(null);
          setActivePage('login');
        }
      } finally {
        if (!cancelled) {
          setCheckingSession(false);
        }
      }
    }
    checkSession();
    return () => {
      cancelled = true;
    };
  }, []);

  // Countdown timer when login is locked (HTTP 429)
  useEffect(() => {
    if (lockoutSecondsLeft <= 0) return undefined;
    const timer = setInterval(() => {
      setLockoutSecondsLeft((prev) => {
        if (prev <= 1) {
          setLoginError('');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [lockoutSecondsLeft]);

  const isLockedOut = lockoutSecondsLeft > 0;
  const lockoutMinutes = Math.max(1, Math.ceil(lockoutSecondsLeft / 60));

  const handleLogin = async (e) => {
    e.preventDefault();
    const trimmedUser = username.trim();
    const submittedPassword = password;
    // Always clear the password input immediately on submit
    setPassword('');

    if (!trimmedUser || !submittedPassword || loginBusy || isLockedOut) return;

    setLoginBusy(true);
    setLoginError('');

    try {
      const user = await login(trimmedUser, submittedPassword);
      setCurrentUser(user);
      setUsername('');
      setSentQuestion('');
      setAnswerData(null);
      setErrorInfo(null);
      setLockoutSecondsLeft(0);
      setActivePage('chat');
    } catch (err) {
      if (err?.status === 429) {
        const seconds = err.retryAfterSeconds || 300;
        setLockoutSecondsLeft(seconds);
      }
      setLoginError(err?.message || 'Invalid username or password.');
    } finally {
      setLoginBusy(false);
    }
  };

  const handleLogout = async () => {
    setProfileOpen(false);
    await logout();
    setCurrentUser(null);
    setQuestion('');
    setSentQuestion('');
    setAnswerData(null);
    setErrorInfo(null);
    setLoginError('');
    setActivePage('login');
  };

  const sendQuestion = async (e) => {
    e.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || typing) return;

    setSentQuestion(trimmed);
    setQuestion('');
    setTyping(true);
    setAnswerData(null);
    setErrorInfo(null);

    try {
      const result = await askQuestion(trimmed);
      setAnswerData(result);
    } catch (err) {
      if (err?.status === 401) {
        setCurrentUser(null);
        setLoginError('Please sign in.');
        setActivePage('login');
        return;
      }
      setErrorInfo({
        status: err?.status || 0,
        code: err?.code || 'ERROR',
        message: err?.message || 'Could not reach the server.',
      });
    } finally {
      setTyping(false);
    }
  };

  const isNoAccess = answerData?.status === 'no_access';
  const sources = Array.isArray(answerData?.sources) ? answerData.sources : [];
  const security = answerData?.security || { blocked: 0, masked: 0, suspicious: 0 };
  const displayName = currentUser?.name || currentUser?.username || '';
  const avatarText = (displayName || 'U').slice(0, 2).toUpperCase();

  return (
    <div>
      {/* Top Bar */}
      <header className="navbar">
        <div className="brand">
          ASP <span>Agent Stack Project</span>
        </div>

        <nav className="nav-links">
          {currentUser ? (
            <>
              <button
                className={`nav-link ${activePage === 'chat' ? 'active' : ''}`}
                onClick={() => setActivePage('chat')}
              >
                Chat
              </button>

              {/* The Security Panel is visible only to the admin role */}
              {currentUser.role === 'admin' && (
                <button
                  className={`nav-link ${activePage === 'panel' ? 'active' : ''}`}
                  onClick={() => setActivePage('panel')}
                >
                  Security Panel
                </button>
              )}

              {/* Profile & Sign Out Dropdown */}
              <div className="profile-wrapper">
                <button
                  className="profile-pill"
                  onClick={() => setProfileOpen(!profileOpen)}
                >
                  <div className="avatar">{avatarText}</div>
                  <div style={{ textAlign: 'left', fontSize: '12px' }}>
                    <div style={{ fontWeight: 600 }}>{displayName}</div>
                    <div style={{ color: '#94A3B8', fontSize: '11px' }}>
                      {currentUser.role === 'admin' ? 'Admin' : 'User'}
                    </div>
                  </div>
                  <div className="status-dot" />
                </button>

                {profileOpen && (
                  <div className="popover">
                    <div style={{ fontSize: '12px', color: '#94A3B8', marginBottom: '6px' }}>
                      Signed in as <strong>{currentUser.username}</strong>
                    </div>
                    <button className="popover-btn" onClick={handleLogout}>
                      Sign out
                    </button>
                  </div>
                )}
              </div>

              <button
                type="button"
                className="nav-link"
                onClick={handleLogout}
              >
                Logout
              </button>
            </>
          ) : (
            <button
              className="nav-link active"
              onClick={() => setActivePage('login')}
            >
              Login
            </button>
          )}
        </nav>
      </header>

      <main className="container">
        {checkingSession ? (
          <div className="card">
            <p style={{ color: '#94A3B8' }}>Checking session…</p>
          </div>
        ) : !currentUser || activePage === 'login' ? (
          /* PAGE 1: LOGIN */
          <div className="card" style={{ maxWidth: '420px', margin: '40px auto' }}>
            <h2>Sign In</h2>
            <p style={{ color: '#94A3B8', fontSize: '13px', marginTop: '6px' }}>
              Sign in with your Agent Stack account to continue.
            </p>

            {(loginError || isLockedOut) && (
              <div
                className="meta-box"
                role="alert"
                style={{
                  marginTop: '16px',
                  color: '#FCA5A5',
                  borderColor: '#EF4444',
                  backgroundColor: 'rgba(239, 68, 68, 0.08)',
                }}
              >
                {isLockedOut
                  ? `Too many attempts. Try again in ${lockoutMinutes} ${lockoutMinutes === 1 ? 'minute' : 'minutes'} (${lockoutSecondsLeft}s).`
                  : loginError}
              </div>
            )}

            <form onSubmit={handleLogin} style={{ marginTop: '16px' }}>
              <div style={{ marginBottom: '12px' }}>
                <label
                  htmlFor="login-username"
                  style={{ display: 'block', fontSize: '13px', marginBottom: '6px' }}
                >
                  Username
                </label>
                <input
                  id="login-username"
                  type="text"
                  className="text-input"
                  style={{ width: '100%' }}
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={loginBusy || isLockedOut}
                  required
                />
              </div>

              <div style={{ marginBottom: '16px' }}>
                <label
                  htmlFor="login-password"
                  style={{ display: 'block', fontSize: '13px', marginBottom: '6px' }}
                >
                  Password
                </label>
                <input
                  id="login-password"
                  type="password"
                  className="text-input"
                  style={{ width: '100%' }}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={loginBusy || isLockedOut}
                  required
                />
              </div>

              <button
                type="submit"
                className="btn-primary"
                style={{ width: '100%' }}
                disabled={loginBusy || isLockedOut || !username.trim() || !password}
              >
                {isLockedOut
                  ? `Locked (${lockoutSecondsLeft}s)`
                  : loginBusy
                    ? 'Signing in…'
                    : 'Sign In'}
              </button>
            </form>
          </div>
        ) : activePage === 'panel' && currentUser.role === 'admin' ? (
          /* PAGE 3: SECURITY PANEL */
          <div className="card">
            <h2>Security Panel</h2>
            <p style={{ color: '#94A3B8', marginTop: '8px' }}>
              Security events panel, visible only to the admin role.
            </p>
          </div>
        ) : (
          /* PAGE 2: CHAT */
          <div>
            <div className="card">
              <h2>Chat</h2>
              <p style={{ color: '#94A3B8', fontSize: '13px', marginTop: '4px' }}>
                Connected Server Address (Read from Settings): <code>{API_URL}</code>
              </p>

              {sentQuestion && (
                <div style={{ marginTop: '20px', textAlign: 'right' }}>
                  <span
                    style={{
                      display: 'inline-block',
                      backgroundColor: '#0F172A',
                      border: '1px solid #334155',
                      padding: '10px 16px',
                      borderRadius: '10px',
                    }}
                  >
                    {sentQuestion}
                  </span>
                </div>
              )}

              {/* "Typing…" Waiting State */}
              {typing && (
                <div className="meta-box" style={{ marginTop: '16px', color: '#38BDF8' }}>
                  Typing…
                </div>
              )}

              {/* Error State (422, 500, 502, 504 or Network Error) */}
              {errorInfo && !typing && (
                <div
                  className="meta-box"
                  role="alert"
                  style={{
                    marginTop: '16px',
                    color: '#FCA5A5',
                    borderColor: '#EF4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.08)',
                  }}
                >
                  <strong>Error: </strong>
                  {errorInfo.message}
                </div>
              )}

              {/* Answer, Sources and Security Summary */}
              {answerData && !typing && (
                <div style={{ marginTop: '20px' }}>
                  {isNoAccess ? (
                    <div
                      className="meta-box"
                      role="status"
                      style={{
                        backgroundColor: 'rgba(245, 158, 11, 0.1)',
                        border: '1px solid #F59E0B',
                        color: '#FDE68A',
                        padding: '16px',
                        borderRadius: '8px',
                        lineHeight: '1.5',
                      }}
                    >
                      <strong>Access Restricted: </strong>
                      {answerData.answer}
                    </div>
                  ) : (
                    <div
                      style={{
                        backgroundColor: '#0F172A',
                        border: '1px solid #334155',
                        padding: '16px',
                        borderRadius: '8px',
                        lineHeight: '1.5',
                        whiteSpace: 'pre-wrap',
                      }}
                    >
                      {/* Plain text display */}
                      {answerData.answer}
                    </div>
                  )}

                  <div className="meta-box">
                    <strong>Messages It Is Based On (Sources):</strong>
                    {sources.length === 0 ? (
                      <div>No sources</div>
                    ) : (
                      <ul style={{ marginTop: '6px', paddingLeft: '18px' }}>
                        {sources.map((s) => (
                          <li key={s.id}>
                            #{s.channel} — {s.author} ({formatLocalTime(s.time)}): &quot;{s.text}&quot;
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <div className="meta-box">
                    <strong>Security Summary: </strong>
                    Blocked: {security.blocked} | Masked: {security.masked} | Suspicious:{' '}
                    {security.suspicious}
                  </div>
                </div>
              )}

              <form className="input-row" onSubmit={sendQuestion}>
                <input
                  type="text"
                  className="text-input"
                  placeholder="Type your question... (e.g. summarize #dev)"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                />
                <button type="submit" className="btn-primary" disabled={typing}>
                  Send
                </button>
              </form>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
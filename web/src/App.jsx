import { useState } from 'react';
import { API_URL, askQuestion } from './api';

// Temporary user and role constants (will come from the session in Stage 2 / S2-08)
// If you set the role to 'admin', the Security Panel tab becomes visible
const CURRENT_USER = { name: 'ali', role: 'user' }; // 'user' | 'admin'

function formatLocalTime(isoString) {
  if (!isoString) return '';
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString;
  return date.toLocaleString();
}

export default function App() {
  // Switching between 3 pages: 'login' | 'chat' | 'panel'
  const [activePage, setActivePage] = useState('chat');
  const [profileOpen, setProfileOpen] = useState(false);

  // Chat flow state
  const [question, setQuestion] = useState('');
  const [sentQuestion, setSentQuestion] = useState('');
  const [typing, setTyping] = useState(false);
  const [answerData, setAnswerData] = useState(null);
  const [errorInfo, setErrorInfo] = useState(null);

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

  return (
    <div>
      {/* Top Menu: Switching Between 3 Pages */}
      <header className="navbar">
        <div className="brand">
          ASP <span>Agent Stack Project</span>
        </div>

        <nav className="nav-links">
          <button
            className={`nav-link ${activePage === 'login' ? 'active' : ''}`}
            onClick={() => setActivePage('login')}
          >
            Login
          </button>
          <button
            className={`nav-link ${activePage === 'chat' ? 'active' : ''}`}
            onClick={() => setActivePage('chat')}
          >
            Chat
          </button>

          {/* The Security Panel is visible only to the admin role */}
          {CURRENT_USER.role === 'admin' && (
            <button
              className={`nav-link ${activePage === 'panel' ? 'active' : ''}`}
              onClick={() => setActivePage('panel')}
            >
              Security Panel
            </button>
          )}

          {/* Profile & Linked Accounts Dropdown */}
          <div className="profile-wrapper">
            <button
              className="profile-pill"
              onClick={() => setProfileOpen(!profileOpen)}
            >
              <div className="avatar">
                {CURRENT_USER.name.slice(0, 2).toUpperCase()}
              </div>
              <div style={{ textAlign: 'left', fontSize: '12px' }}>
                <div style={{ fontWeight: 600 }}>{CURRENT_USER.name}</div>
                <div style={{ color: '#94A3B8', fontSize: '11px' }}>
                  {CURRENT_USER.role === 'admin' ? 'Admin' : 'User'}
                </div>
              </div>
              <div className="status-dot" />
            </button>

            {profileOpen && (
              <div className="popover">
                <div style={{ fontSize: '12px', color: '#94A3B8', marginBottom: '4px' }}>
                  Profile & Linked Accounts
                </div>
                <button className="popover-btn">🔗 Link Jira account</button>
                <button className="popover-btn">🔗 Link GitHub account</button>
              </div>
            )}
          </div>
        </nav>
      </header>

      <main className="container">
        {/* PAGE 1: LOGIN */}
        {activePage === 'login' && (
          <div className="card">
            <h2>Login Screen (Skeleton)</h2>
            <p style={{ color: '#94A3B8', marginTop: '8px' }}>
              Skeleton of the login and Sign in with Slack screen, active in Stage 2.
            </p>
          </div>
        )}

        {/* PAGE 2: CHAT */}
        {activePage === 'chat' && (
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

              {/* Error State (401, 422, 500, 502, 504 or Network Error) */}
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
                  <div>
                    <strong>
                      {errorInfo.status === 401 ? 'Authentication Required: ' : 'Error: '}
                    </strong>
                    {errorInfo.message}
                  </div>
                  {errorInfo.status === 401 && (
                    <button
                      type="button"
                      className="btn-primary"
                      style={{ marginTop: '10px', padding: '6px 12px', fontSize: '13px' }}
                      onClick={() => setActivePage('login')}
                    >
                      Go to Login
                    </button>
                  )}
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

        {/* PAGE 3: SECURITY PANEL */}
        {activePage === 'panel' && CURRENT_USER.role === 'admin' && (
          <div className="card">
            <h2>Security Panel (Skeleton)</h2>
            <p style={{ color: '#94A3B8', marginTop: '8px' }}>
              Skeleton of the security events panel, visible only to the admin role.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
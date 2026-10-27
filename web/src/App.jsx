import { useState } from 'react';
import { API_URL, askQuestion } from './api';

// Temporary user and role constants (will come from the session in Stage 2)
// If you set the role to 'admin', the Security Panel tab becomes visible
const CURRENT_USER = { name: 'ali', role: 'user' }; // 'user' | 'admin'

export default function App() {
  // Switching between 3 pages: 'login' | 'chat' | 'panel'
  const [activePage, setActivePage] = useState('chat');
  const [profileOpen, setProfileOpen] = useState(false);

  // Chat flow state
  const [question, setQuestion] = useState('');
  const [sentQuestion, setSentQuestion] = useState('');
  const [typing, setTyping] = useState(false);
  const [answerData, setAnswerData] = useState(null);
  const [errorMessage, setErrorMessage] = useState('');

  const sendQuestion = async (e) => {
    e.preventDefault();
    if (!question.trim() || typing) return;

    const currentQuestion = question;
    setSentQuestion(currentQuestion);
    setQuestion('');
    setTyping(true);
    setAnswerData(null);
    setErrorMessage('');

    try {
      const result = await askQuestion(currentQuestion, CURRENT_USER.name);
      if (result.error) {
        setErrorMessage(result.error.message || 'An error occurred.');
      } else {
        setAnswerData(result);
      }
    } catch (err) {
      setErrorMessage(err?.error?.message || 'Could not reach the server.');
    } finally {
      setTyping(false);
    }
  };

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

              {/* Error State */}
              {errorMessage && !typing && (
                <div
                  className="meta-box"
                  style={{
                    marginTop: '16px',
                    color: '#FCA5A5',
                    borderColor: '#EF4444',
                  }}
                >
                  {errorMessage}
                </div>
              )}

              {/* Answer, Sources and Security Summary */}
              {answerData && !typing && (
                <div style={{ marginTop: '20px' }}>
                  <div
                    style={{
                      backgroundColor: '#0F172A',
                      border: '1px solid #334155',
                      padding: '16px',
                      borderRadius: '8px',
                      lineHeight: '1.5',
                    }}
                  >
                    {/* Plain text display */}
                    {answerData.answer}
                  </div>

                  <div className="meta-box">
                    <strong>Messages It Is Based On (Sources):</strong>
                    {answerData.sources.length === 0 ? (
                      <div>No sources</div>
                    ) : (
                      <ul style={{ marginTop: '6px', paddingLeft: '18px' }}>
                        {answerData.sources.map((s) => (
                          <li key={`${s.channel}-${s.time}`}>
                            #{s.channel} — {s.author}: &quot;{s.text}&quot;
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <div className="meta-box">
                    <strong>Security Summary: </strong>
                    Blocked: {answerData.security.blocked} | Masked:{' '}
                    {answerData.security.masked} | Suspicious:{' '}
                    {answerData.security.suspicious}
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

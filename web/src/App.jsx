import { Fragment, useCallback, useEffect, useState } from 'react';
import { API_URL, askQuestion, getAdminEvents, getCurrentUser, login, logout } from './api';
import {
  SECRET_ALARM_WARNING,
  formatMaskedKinds,
  getDisplayedQuestion,
  getEventKey,
  groupEventsByRequestId,
  normalizeSecuritySummary,
} from './security';

function formatLocalTime(isoString) {
  if (!isoString) return '—';
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString;
  return date.toLocaleString();
}

function renderDecisionBadge(decision, alarm = false) {
  const isStopped = decision === 'stopped' || decision === 'error';
  return (
    <span style={{ whiteSpace: 'nowrap' }}>
      <span
        style={{
          display: 'inline-block',
          padding: '2px 8px',
          borderRadius: '999px',
          fontSize: '12px',
          fontWeight: 600,
          backgroundColor: isStopped ? 'rgba(239, 68, 68, 0.2)' : 'rgba(34, 197, 94, 0.15)',
          color: isStopped ? '#FCA5A5' : '#86EFAC',
          border: `1px solid ${isStopped ? '#EF4444' : '#22C55E'}`,
        }}
      >
        {decision}
      </span>
      {alarm === true && <span className="alarm-badge">ALARM</span>}
    </span>
  );
}

export function SecurityEventsTable({
  events,
  groupByRequest = false,
  expandedRequests = {},
  onToggleExpand,
}) {
  const groupedEvents = groupByRequest ? groupEventsByRequestId(events) : [];

  return (
    <div className="table-container">
      <table className="events-table">
        <thead>
          <tr
            style={{
              borderBottom: '1px solid #334155',
              color: '#94A3B8',
            }}
          >
            <th>Time</th>
            <th>Request ID</th>
            <th>Person</th>
            <th>Channel</th>
            <th>Step</th>
            <th>Decision</th>
            <th>Reason Code</th>
            <th>Duration (ms)</th>
            <th>Counts (Msg / Blk / Msk / Susp)</th>
            <th>Masked Kinds</th>
          </tr>
        </thead>
        <tbody>
          {!groupByRequest
            ? events.map((ev) => {
                const isStopped = ev.decision === 'stopped' || ev.decision === 'error';
                const isAlarm = ev.alarm === true;
                const kindsText = formatMaskedKinds(ev.masked_kinds);
                return (
                  <tr
                    key={getEventKey(ev)}
                    data-alarm={isAlarm ? 'true' : 'false'}
                    style={{
                      borderBottom: '1px solid #1E293B',
                      backgroundColor: isStopped
                        ? 'rgba(239, 68, 68, 0.12)'
                        : isAlarm
                          ? 'rgba(245, 158, 11, 0.12)'
                          : 'transparent',
                    }}
                  >
                    <td style={{ whiteSpace: 'nowrap' }}>{formatLocalTime(ev.created_at)}</td>
                    <td style={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                      {ev.request_id || '—'}
                    </td>
                    <td style={{ fontWeight: 600 }}>{ev.person || '—'}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {ev.channel ? `#${ev.channel}` : '—'}
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>{ev.step}</td>
                    <td>{renderDecisionBadge(ev.decision, isAlarm)}</td>
                    <td
                      style={{
                        fontFamily: 'monospace',
                        color: isStopped ? '#FCA5A5' : '#CBD5E1',
                      }}
                    >
                      {ev.reason_code || '—'}
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {typeof ev.duration_ms === 'number'
                        ? `${ev.duration_ms.toFixed(2)} ms`
                        : '—'}
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {ev.message_count} / {ev.blocked_count} / {ev.masked_count} /{' '}
                      {ev.suspicious_count}
                    </td>
                    <td
                      style={{
                        fontFamily: kindsText ? 'monospace' : 'inherit',
                        color: kindsText ? '#FDE68A' : '#94A3B8',
                      }}
                    >
                      {kindsText || '—'}
                    </td>
                  </tr>
                );
              })
            : groupedEvents.map((group) => {
                const isStopped = group.decision === 'stopped' || group.decision === 'error';
                const isAlarm = group.alarm === true;
                const kindsText = formatMaskedKinds(group.masked_kinds);
                const canExpand = Boolean(group.request_id && group.steps.length > 1);
                const isExpanded = Boolean(
                  group.request_id && expandedRequests[group.request_id],
                );
                return (
                  <Fragment key={group.groupKey}>
                    <tr
                      data-alarm={isAlarm ? 'true' : 'false'}
                      onClick={
                        canExpand && onToggleExpand
                          ? () => onToggleExpand(group.request_id)
                          : undefined
                      }
                      style={{
                        borderBottom: '1px solid #1E293B',
                        cursor: canExpand ? 'pointer' : 'default',
                        backgroundColor: isStopped
                          ? 'rgba(239, 68, 68, 0.12)'
                          : isAlarm
                            ? 'rgba(245, 158, 11, 0.12)'
                            : 'transparent',
                      }}
                    >
                      <td style={{ whiteSpace: 'nowrap' }}>{formatLocalTime(group.latest_at)}</td>
                      <td style={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                        {canExpand ? (isExpanded ? '▼ ' : '▶ ') : ''}
                        {group.request_id || '—'}
                      </td>
                      <td style={{ fontWeight: 600 }}>{group.person || '—'}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        {group.channel ? `#${group.channel}` : '—'}
                      </td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        {group.steps.length > 1
                          ? `${group.steps.length} steps`
                          : group.steps[0]?.step}
                      </td>
                      <td>{renderDecisionBadge(group.decision, isAlarm)}</td>
                      <td
                        style={{
                          fontFamily: 'monospace',
                          color: isStopped ? '#FCA5A5' : '#CBD5E1',
                        }}
                      >
                        {group.reason_code || '—'}
                      </td>
                      <td style={{ whiteSpace: 'nowrap' }}>{group.duration_ms.toFixed(2)} ms</td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        {group.message_count} / {group.blocked_count} / {group.masked_count} /{' '}
                        {group.suspicious_count}
                      </td>
                      <td
                        style={{
                          fontFamily: kindsText ? 'monospace' : 'inherit',
                          color: kindsText ? '#FDE68A' : '#94A3B8',
                        }}
                      >
                        {kindsText || '—'}
                      </td>
                    </tr>
                    {isExpanded &&
                      group.steps.map((stepEv) => {
                        const stepStopped =
                          stepEv.decision === 'stopped' || stepEv.decision === 'error';
                        const stepAlarm = stepEv.alarm === true;
                        const stepKindsText = formatMaskedKinds(stepEv.masked_kinds);
                        return (
                          <tr
                            key={getEventKey(stepEv)}
                            data-alarm={stepAlarm ? 'true' : 'false'}
                            style={{
                              borderBottom: '1px solid #1E293B',
                              backgroundColor: stepStopped
                                ? 'rgba(239, 68, 68, 0.18)'
                                : stepAlarm
                                  ? 'rgba(245, 158, 11, 0.16)'
                                  : 'rgba(15, 23, 42, 0.6)',
                              fontSize: '12px',
                            }}
                          >
                            <td
                              style={{
                                paddingLeft: '20px',
                                color: '#94A3B8',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {formatLocalTime(stepEv.created_at)}
                            </td>
                            <td style={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                              ↳ step
                            </td>
                            <td>{stepEv.person || '—'}</td>
                            <td style={{ whiteSpace: 'nowrap' }}>
                              {stepEv.channel ? `#${stepEv.channel}` : '—'}
                            </td>
                            <td style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>
                              {stepEv.step}
                            </td>
                            <td>{renderDecisionBadge(stepEv.decision, stepAlarm)}</td>
                            <td style={{ fontFamily: 'monospace' }}>
                              {stepEv.reason_code || '—'}
                            </td>
                            <td style={{ whiteSpace: 'nowrap' }}>
                              {typeof stepEv.duration_ms === 'number'
                                ? `${stepEv.duration_ms.toFixed(2)} ms`
                                : '—'}
                            </td>
                            <td style={{ whiteSpace: 'nowrap' }}>
                              {stepEv.message_count} / {stepEv.blocked_count} /{' '}
                              {stepEv.masked_count} / {stepEv.suspicious_count}
                            </td>
                            <td
                              style={{
                                fontFamily: stepKindsText ? 'monospace' : 'inherit',
                                color: stepKindsText ? '#FDE68A' : '#94A3B8',
                              }}
                            >
                              {stepKindsText || '—'}
                            </td>
                          </tr>
                        );
                      })}
                  </Fragment>
                );
              })}
        </tbody>
      </table>
    </div>
  );
}

export function ChatAnswerView({ answerData }) {
  if (!answerData) return null;

  const isNoAccess = answerData.status === 'no_access';
  const sources = Array.isArray(answerData.sources) ? answerData.sources : [];
  const security = normalizeSecuritySummary(answerData.security);

  return (
    <div style={{ marginTop: '20px' }}>
      {security.alarm && (
        <div
          className="meta-box alarm-warning-box"
          role="alert"
          style={{
            marginTop: 0,
            marginBottom: '12px',
            backgroundColor: 'rgba(245, 158, 11, 0.12)',
            border: '1px solid #F59E0B',
            color: '#FDE68A',
            padding: '12px 16px',
            borderRadius: '8px',
            lineHeight: '1.5',
          }}
        >
          {SECRET_ALARM_WARNING}
        </div>
      )}

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
  );
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

  // Security Panel state (S2-09)
  const [events, setEvents] = useState([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsError, setEventsError] = useState('');
  const [groupByRequest, setGroupByRequest] = useState(false);
  const [expandedRequests, setExpandedRequests] = useState({});

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

  const loadAdminEvents = useCallback(async () => {
    setEventsLoading(true);
    setEventsError('');
    try {
      const list = await getAdminEvents(50);
      setEvents(list);
    } catch (err) {
      if (err?.status === 401) {
        setCurrentUser(null);
        setEvents([]);
        setLoginError('Please sign in.');
        setActivePage('login');
        return;
      }
      if (err?.status === 403) {
        setEvents([]);
        setEventsError('Admins only.');
        return;
      }
      setEventsError(err?.message || 'Could not load security events.');
    } finally {
      setEventsLoading(false);
    }
  }, []);


  const openSecurityPanel = () => {
    setActivePage('panel');
    loadAdminEvents();
  };

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
      setEvents([]);
      setEventsError('');
      setLockoutSecondsLeft(0);
      setActivePage('chat');
    } catch (err) {
      if (err?.status === 429) {
        const seconds = err.retryAfterSeconds || 900;
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
    setEvents([]);
    setEventsError('');
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
      if (result?.security?.alarm === true) {
        setSentQuestion('[REDACTED]');
      }
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

  const toggleRequestExpand = (reqId) => {
    setExpandedRequests((prev) => ({
      ...prev,
      [reqId]: !prev[reqId],
    }));
  };

  const security = normalizeSecuritySummary(answerData?.security);
  const displayedQuestion = getDisplayedQuestion(sentQuestion, security);
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

              <button
                className={`nav-link ${activePage === 'panel' ? 'active' : ''}`}
                onClick={openSecurityPanel}
              >
                Security Panel
              </button>

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
        ) : activePage === 'panel' ? (
          /* PAGE 3: SECURITY PANEL (S2-09 / S3-11) */
          <div className="card">
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '12px',
              }}
            >
              <div>
                <h2>Security Panel</h2>
                <p style={{ color: '#94A3B8', fontSize: '13px', marginTop: '4px' }}>
                  Gateway audit events (newest first · contains no message or question text)
                </p>
              </div>

              {!eventsError && (
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <button
                    type="button"
                    className={`nav-link ${groupByRequest ? 'active' : ''}`}
                    onClick={() => setGroupByRequest((prev) => !prev)}
                  >
                    {groupByRequest ? 'Show All Steps' : 'Group by Request'}
                  </button>
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={loadAdminEvents}
                    disabled={eventsLoading}
                  >
                    {eventsLoading ? 'Loading…' : 'Refresh'}
                  </button>
                </div>
              )}
            </div>

            {eventsError && (
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
                {eventsError}
              </div>
            )}

            {!eventsError && eventsLoading && events.length === 0 && (
              <div className="meta-box" style={{ marginTop: '16px', color: '#94A3B8' }}>
                Loading security events…
              </div>
            )}

            {!eventsError && !eventsLoading && events.length === 0 && (
              <div className="meta-box" style={{ marginTop: '16px', color: '#94A3B8' }}>
                No security events recorded yet.
              </div>
            )}

            {!eventsError && events.length > 0 && (
              <SecurityEventsTable
                events={events}
                groupByRequest={groupByRequest}
                expandedRequests={expandedRequests}
                onToggleExpand={toggleRequestExpand}
              />
            )}
          </div>
        ) : (
          /* PAGE 2: CHAT */
          <div>
            <div className="card">
              <h2>Chat</h2>
              <p style={{ color: '#94A3B8', fontSize: '13px', marginTop: '4px' }}>
                Connected Server Address (Read from Settings): <code>{API_URL}</code>
              </p>

              {displayedQuestion && (
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
                    {displayedQuestion}
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

              {/* Answer, Warning, Sources and Security Summary */}
              {answerData && !typing && <ChatAnswerView answerData={answerData} />}

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
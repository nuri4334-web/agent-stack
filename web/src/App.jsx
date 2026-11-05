import { Fragment, useCallback, useEffect, useState } from 'react';
import { API_URL, askQuestion, getAdminEvents, getCurrentUser, login, logout } from './api';

function formatLocalTime(isoString) {
  if (!isoString) return '—';
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString;
  return date.toLocaleString();
}

function getEventKey(ev) {
  if (ev.id) return String(ev.id);
  return `${ev.created_at}-${ev.request_id || 'no-req'}-${ev.step}-${ev.person || 'anon'}-${ev.duration_ms}`;
}

function groupEventsByRequestId(events) {
  const groups = [];
  const byRequestId = new Map();

  for (const ev of events) {
    if (!ev.request_id) {
      groups.push({
        groupKey: getEventKey(ev),
        request_id: null,
        latest_at: ev.created_at,
        person: ev.person,
        channel: ev.channel,
        decision: ev.decision,
        reason_code: ev.reason_code,
        duration_ms: ev.duration_ms || 0,
        message_count: ev.message_count || 0,
        blocked_count: ev.blocked_count || 0,
        masked_count: ev.masked_count || 0,
        suspicious_count: ev.suspicious_count || 0,
        steps: [ev],
      });
      continue;
    }

    let group = byRequestId.get(ev.request_id);
    if (!group) {
      group = {
        groupKey: `req-${ev.request_id}-${ev.created_at}`,
        request_id: ev.request_id,
        latest_at: ev.created_at,
        person: ev.person,
        channel: ev.channel,
        decision: ev.decision,
        reason_code: ev.reason_code,
        duration_ms: 0,
        message_count: 0,
        blocked_count: 0,
        masked_count: 0,
        suspicious_count: 0,
        steps: [],
      };
      byRequestId.set(ev.request_id, group);
      groups.push(group);
    }

    group.steps.push(ev);
    group.duration_ms += Number(ev.duration_ms) || 0;
    if (!group.person && ev.person) group.person = ev.person;
    if (!group.channel && ev.channel) group.channel = ev.channel;
    if (ev.decision === 'stopped' || ev.decision === 'error') {
      group.decision = ev.decision;
      if (ev.reason_code) group.reason_code = ev.reason_code;
    }
    group.message_count = Math.max(group.message_count, ev.message_count || 0);
    group.blocked_count += ev.blocked_count || 0;
    group.masked_count += ev.masked_count || 0;
    group.suspicious_count += ev.suspicious_count || 0;
  }

  return groups;
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

  const isNoAccess = answerData?.status === 'no_access';
  const sources = Array.isArray(answerData?.sources) ? answerData.sources : [];
  const security = answerData?.security || { blocked: 0, masked: 0, suspicious: 0 };
  const displayName = currentUser?.name || currentUser?.username || '';
  const avatarText = (displayName || 'U').slice(0, 2).toUpperCase();
  const groupedEvents = groupByRequest ? groupEventsByRequestId(events) : [];

  const renderDecisionBadge = (decision) => {
    const isStopped = decision === 'stopped' || decision === 'error';
    return (
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
    );
  };

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
          /* PAGE 3: SECURITY PANEL (S2-09) */
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
              <div style={{ marginTop: '16px', overflowX: 'auto' }}>
                <table
                  style={{
                    width: '100%',
                    borderCollapse: 'collapse',
                    fontSize: '13px',
                    textAlign: 'left',
                  }}
                >
                  <thead>
                    <tr
                      style={{
                        borderBottom: '1px solid #334155',
                        color: '#94A3B8',
                      }}
                    >
                      <th style={{ padding: '10px 8px' }}>Time</th>
                      <th style={{ padding: '10px 8px' }}>Request ID</th>
                      <th style={{ padding: '10px 8px' }}>Person</th>
                      <th style={{ padding: '10px 8px' }}>Channel</th>
                      <th style={{ padding: '10px 8px' }}>Step</th>
                      <th style={{ padding: '10px 8px' }}>Decision</th>
                      <th style={{ padding: '10px 8px' }}>Reason Code</th>
                      <th style={{ padding: '10px 8px' }}>Duration (ms)</th>
                      <th style={{ padding: '10px 8px' }}>Counts (Msg / Blk / Msk / Susp)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!groupByRequest
                      ? events.map((ev) => {
                          const isStopped = ev.decision === 'stopped' || ev.decision === 'error';
                          return (
                            <tr
                              key={getEventKey(ev)}
                              style={{
                                borderBottom: '1px solid #1E293B',
                                backgroundColor: isStopped
                                  ? 'rgba(239, 68, 68, 0.12)'
                                  : 'transparent',
                              }}
                            >
                              <td style={{ padding: '10px 8px', whiteSpace: 'nowrap' }}>
                                {formatLocalTime(ev.created_at)}
                              </td>
                              <td style={{ padding: '10px 8px', fontFamily: 'monospace' }}>
                                {ev.request_id || '—'}
                              </td>
                              <td style={{ padding: '10px 8px', fontWeight: 600 }}>
                                {ev.person || '—'}
                              </td>
                              <td style={{ padding: '10px 8px' }}>
                                {ev.channel ? `#${ev.channel}` : '—'}
                              </td>
                              <td style={{ padding: '10px 8px' }}>{ev.step}</td>
                              <td style={{ padding: '10px 8px' }}>
                                {renderDecisionBadge(ev.decision)}
                              </td>
                              <td
                                style={{
                                  padding: '10px 8px',
                                  fontFamily: 'monospace',
                                  color: isStopped ? '#FCA5A5' : '#CBD5E1',
                                }}
                              >
                                {ev.reason_code || '—'}
                              </td>
                              <td style={{ padding: '10px 8px', whiteSpace: 'nowrap' }}>
                                {typeof ev.duration_ms === 'number'
                                  ? `${ev.duration_ms.toFixed(2)} ms`
                                  : '—'}
                              </td>
                              <td style={{ padding: '10px 8px', whiteSpace: 'nowrap' }}>
                                {ev.message_count} / {ev.blocked_count} / {ev.masked_count} /{' '}
                                {ev.suspicious_count}
                              </td>
                            </tr>
                          );
                        })
                      : groupedEvents.map((group) => {
                          const isStopped =
                            group.decision === 'stopped' || group.decision === 'error';
                          const canExpand = Boolean(group.request_id && group.steps.length > 1);
                          const isExpanded = Boolean(
                            group.request_id && expandedRequests[group.request_id],
                          );
                          return (
                            <Fragment key={group.groupKey}>
                              <tr
                                onClick={
                                  canExpand
                                    ? () => toggleRequestExpand(group.request_id)
                                    : undefined
                                }
                                style={{
                                  borderBottom: '1px solid #1E293B',
                                  cursor: canExpand ? 'pointer' : 'default',
                                  backgroundColor: isStopped
                                    ? 'rgba(239, 68, 68, 0.12)'
                                    : 'transparent',
                                }}
                              >
                                <td style={{ padding: '10px 8px', whiteSpace: 'nowrap' }}>
                                  {formatLocalTime(group.latest_at)}
                                </td>
                                <td style={{ padding: '10px 8px', fontFamily: 'monospace' }}>
                                  {canExpand ? (isExpanded ? '▼ ' : '▶ ') : ''}
                                  {group.request_id || '—'}
                                </td>
                                <td style={{ padding: '10px 8px', fontWeight: 600 }}>
                                  {group.person || '—'}
                                </td>
                                <td style={{ padding: '10px 8px' }}>
                                  {group.channel ? `#${group.channel}` : '—'}
                                </td>
                                <td style={{ padding: '10px 8px' }}>
                                  {group.steps.length > 1
                                    ? `${group.steps.length} steps`
                                    : group.steps[0]?.step}
                                </td>
                                <td style={{ padding: '10px 8px' }}>
                                  {renderDecisionBadge(group.decision)}
                                </td>
                                <td
                                  style={{
                                    padding: '10px 8px',
                                    fontFamily: 'monospace',
                                    color: isStopped ? '#FCA5A5' : '#CBD5E1',
                                  }}
                                >
                                  {group.reason_code || '—'}
                                </td>
                                <td style={{ padding: '10px 8px', whiteSpace: 'nowrap' }}>
                                  {group.duration_ms.toFixed(2)} ms
                                </td>
                                <td style={{ padding: '10px 8px', whiteSpace: 'nowrap' }}>
                                  {group.message_count} / {group.blocked_count} /{' '}
                                  {group.masked_count} / {group.suspicious_count}
                                </td>
                              </tr>
                              {isExpanded &&
                                group.steps.map((stepEv) => {
                                  const stepStopped =
                                    stepEv.decision === 'stopped' || stepEv.decision === 'error';
                                  return (
                                    <tr
                                      key={getEventKey(stepEv)}
                                      style={{
                                        borderBottom: '1px solid #1E293B',
                                        backgroundColor: stepStopped
                                          ? 'rgba(239, 68, 68, 0.18)'
                                          : 'rgba(15, 23, 42, 0.6)',
                                        fontSize: '12px',
                                      }}
                                    >
                                      <td style={{ padding: '8px 8px 8px 24px', color: '#94A3B8' }}>
                                        {formatLocalTime(stepEv.created_at)}
                                      </td>
                                      <td style={{ padding: '8px', fontFamily: 'monospace' }}>
                                        ↳ step
                                      </td>
                                      <td style={{ padding: '8px' }}>{stepEv.person || '—'}</td>
                                      <td style={{ padding: '8px' }}>
                                        {stepEv.channel ? `#${stepEv.channel}` : '—'}
                                      </td>
                                      <td style={{ padding: '8px', fontWeight: 600 }}>
                                        {stepEv.step}
                                      </td>
                                      <td style={{ padding: '8px' }}>
                                        {renderDecisionBadge(stepEv.decision)}
                                      </td>
                                      <td style={{ padding: '8px', fontFamily: 'monospace' }}>
                                        {stepEv.reason_code || '—'}
                                      </td>
                                      <td style={{ padding: '8px' }}>
                                        {typeof stepEv.duration_ms === 'number'
                                          ? `${stepEv.duration_ms.toFixed(2)} ms`
                                          : '—'}
                                      </td>
                                      <td style={{ padding: '8px' }}>
                                        {stepEv.message_count} / {stepEv.blocked_count} /{' '}
                                        {stepEv.masked_count} / {stepEv.suspicious_count}
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
// The server address is read from a setting (the frontend has no secret keys)
export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export class ApiError extends Error {
  constructor(status, code, message, retryAfterSeconds = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

async function parseJsonSafe(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function parseRetryAfter(response) {
  const raw = response.headers.get('Retry-After');
  if (!raw) return null;
  const seconds = Number.parseInt(raw, 10);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

// S2-08: Check current session on startup (GET /api/auth/me)
export async function getCurrentUser() {
  let response;
  try {
    response = await fetch(`${API_URL}/api/auth/me`, {
      method: 'GET',
      credentials: 'include',
    });
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Could not reach the server. Check that the server is running.');
  }

  if (response.status === 401) {
    return null;
  }

  const data = await parseJsonSafe(response);
  if (!response.ok) {
    throw new ApiError(
      response.status,
      data?.error?.code || 'HTTP_ERROR',
      data?.error?.message || `Request failed (HTTP ${response.status}).`,
    );
  }

  return data;
}

// S2-08: Sign in with username and password (POST /api/auth/login)
export async function login(username, password) {
  let response;
  try {
    response = await fetch(`${API_URL}/api/auth/login`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ username, password }),
    });
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Could not reach the server. Check that the server is running.');
  }

  const data = await parseJsonSafe(response);

  if (response.status === 401) {
    throw new ApiError(401, 'INVALID_CREDENTIALS', 'Invalid username or password.');
  }

  if (response.status === 429) {
    const retrySeconds = parseRetryAfter(response) || 900;
    const minutes = Math.max(1, Math.ceil(retrySeconds / 60));
    throw new ApiError(
      429,
      'TOO_MANY_ATTEMPTS',
      `Too many attempts. Try again in ${minutes} ${minutes === 1 ? 'minute' : 'minutes'}.`,
      retrySeconds,
    );
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      data?.error?.code || 'HTTP_ERROR',
      'Unable to sign in right now. Please try again.',
    );
  }

  return data;
}

// S2-08: Sign out and clear session cookie (POST /api/auth/logout -> 204)
export async function logout() {
  try {
    await fetch(`${API_URL}/api/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    });
  } catch {
    // Even on network error, the frontend clears its in-memory user state
  }
}

// S2-07: Connect chat screen to the server (API contract v3)
export async function askQuestion(question) {
  let response;
  try {
    response = await fetch(`${API_URL}/api/ask`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ question }),
    });
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Could not reach the server. Check that the server is running.');
  }

  const data = await parseJsonSafe(response);

  if (!response.ok) {
    const code = data?.error?.code || 'HTTP_ERROR';
    const message =
      response.status === 401
        ? data?.error?.message || 'Please sign in to ask a question.'
        : data?.error?.message || `Request failed (HTTP ${response.status}).`;
    throw new ApiError(response.status, code, message);
  }

  return data;
}
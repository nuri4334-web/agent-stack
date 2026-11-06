export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export class ApiError extends Error {
  constructor(status, code, message, retryAfterSeconds = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

function parseRetryAfter(response) {
  const raw = response.headers.get('Retry-After');
  if (!raw) return null;
  const seconds = Number.parseInt(raw, 10);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

/**
 * Checks who is currently signed in via the session cookie.
 * Returns the user object on 200, or null on 401.
 */
export async function getCurrentUser() {
  let response;
  try {
    response = await fetch(`${API_URL}/api/auth/me`, {
      method: 'GET',
      credentials: 'include',
    });
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Could not reach the server.');
  }

  if (response.status === 401) {
    return null;
  }

  let data;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(response.status, 'INVALID_RESPONSE', 'Received an invalid response from the server.');
  }

  if (!response.ok) {
    const code = data?.error?.code || 'SERVER_ERROR';
    const message = data?.error?.message || 'An unexpected error occurred.';
    throw new ApiError(response.status, code, message);
  }

  return data;
}

/**
 * Signs in with username and password (POST /api/auth/login).
 */
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
    throw new ApiError(0, 'NETWORK_ERROR', 'Unable to sign in right now. Please try again.');
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

  if (response.status === 401) {
    throw new ApiError(401, 'INVALID_CREDENTIALS', 'Invalid username or password.');
  }

  let data;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(response.status, 'INVALID_RESPONSE', 'Unable to sign in right now. Please try again.');
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      data?.error?.code || 'SERVER_ERROR',
      'Unable to sign in right now. Please try again.',
    );
  }

  return data;
}

/**
 * Signs out the current session (POST /api/auth/logout).
 */
export async function logout() {
  try {
    await fetch(`${API_URL}/api/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    });
  } catch {
    // Even if the network fails, clear client state so the user returns to login.
  }
}

/**
 * Sends a question to POST /api/ask using the active session cookie.
 */
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
    throw new ApiError(0, 'NETWORK_ERROR', 'Could not reach the server. Please check your connection.');
  }

  let data;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(response.status, 'INVALID_RESPONSE', 'Received an invalid response from the server.');
  }

  if (!response.ok) {
    const code = data?.error?.code || 'SERVER_ERROR';
    const message = data?.error?.message || 'An unexpected error occurred.';
    throw new ApiError(response.status, code, message);
  }

  return data;
}

/**
 * Fetches security audit events for the admin panel (GET /api/admin/events).
 */
export async function getAdminEvents(limit = 50) {
  let response;
  try {
    response = await fetch(`${API_URL}/api/admin/events?limit=${limit}`, {
      method: 'GET',
      credentials: 'include',
    });
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Could not reach the server.');
  }

  if (response.status === 401) {
    throw new ApiError(401, 'UNAUTHENTICATED', 'Please sign in.');
  }

  if (response.status === 403) {
    throw new ApiError(403, 'FORBIDDEN', 'Admins only.');
  }

  let data;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(response.status, 'INVALID_RESPONSE', 'Received an invalid response from the server.');
  }

  if (!response.ok) {
    const code = data?.error?.code || 'SERVER_ERROR';
    const message = data?.error?.message || 'Could not load security events.';
    throw new ApiError(response.status, code, message);
  }

  return Array.isArray(data?.events) ? data.events : [];
}
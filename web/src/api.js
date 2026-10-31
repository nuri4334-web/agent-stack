// The server address is read from a setting (the frontend has no secret keys)
export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
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

  let data;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

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
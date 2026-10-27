// The server address is read from a setting (the frontend has no secret keys)
export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// S1-07: Fake chat flow (S1-09 will only switch this to fetch)
export async function askQuestion(question, user = 'ali') {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        request_id: 'fake-request-001',
        status: 'ok',
        answer: `Fake answer for the question "${question}" (${user}): this week in #dev the login page and API connections were discussed.`,
        sources: [
          {
            channel: 'dev',
            author: 'Deniz',
            time: '2026-10-22T14:05:00+03:00',
            text: '@Ali you take the login page',
          },
        ],
        security: { blocked: 0, masked: 0, suspicious: 0 },
      });
    }, 1000);
  });
}
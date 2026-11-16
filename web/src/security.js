export const SECRET_ALARM_WARNING =
  'A secret was found in your message and was not sent to the AI. Please rotate this key.';

/**
 * Normalizes the `security` object from `POST /api/ask`.
 * Missing `alarm` is treated as `false` (API contract v4, section 0).
 */
export function normalizeSecuritySummary(security) {
  if (!security || typeof security !== 'object') {
    return { blocked: 0, masked: 0, suspicious: 0, alarm: false };
  }
  return {
    blocked: Number(security.blocked) || 0,
    masked: Number(security.masked) || 0,
    suspicious: Number(security.suspicious) || 0,
    alarm: security.alarm === true,
  };
}

/**
 * Returns the question text safe to display in the chat bubble.
 * When `security.alarm` is true, the raw question contained a secret and is never shown.
 */
export function getDisplayedQuestion(sentQuestion, security) {
  if (!sentQuestion) return '';
  if (security?.alarm === true) {
    return '[REDACTED]';
  }
  return sentQuestion;
}

/**
 * Normalizes an event's `masked_kinds` map (kind -> positive integer count).
 * Missing or invalid `masked_kinds` is treated as `{}` (API contract v4, section 0).
 */
export function normalizeMaskedKinds(maskedKinds) {
  if (!maskedKinds || typeof maskedKinds !== 'object' || Array.isArray(maskedKinds)) {
    return {};
  }
  const normalized = {};
  for (const [kind, count] of Object.entries(maskedKinds)) {
    const num = Number(count);
    if (kind && Number.isFinite(num) && num > 0) {
      normalized[kind] = Math.floor(num);
    }
  }
  return normalized;
}

/**
 * Formats `masked_kinds` as `"1 slack_token, 2 email"` (count + kind, never values).
 * Returns `""` when no kinds were masked.
 */
export function formatMaskedKinds(maskedKinds) {
  const normalized = normalizeMaskedKinds(maskedKinds);
  const entries = Object.entries(normalized);
  if (entries.length === 0) return '';
  return entries.map(([kind, count]) => `${count} ${kind}`).join(', ');
}

export function getEventKey(ev) {
  if (ev.id) return String(ev.id);
  return `${ev.created_at}-${ev.request_id || 'no-req'}-${ev.step}-${ev.person || 'anon'}-${ev.duration_ms}`;
}

/**
 * Groups audit events by `request_id`, summing counts and `masked_kinds` across steps
 * and marking the group with `alarm: true` if any step triggered an alarm.
 */
export function groupEventsByRequestId(events) {
  const groups = [];
  const byRequestId = new Map();

  if (!Array.isArray(events)) return groups;

  for (const ev of events) {
    const evKinds = normalizeMaskedKinds(ev.masked_kinds);
    const evAlarm = ev.alarm === true;

    if (!ev.request_id) {
      groups.push({
        groupKey: getEventKey(ev),
        request_id: null,
        latest_at: ev.created_at,
        person: ev.person,
        channel: ev.channel,
        decision: ev.decision,
        reason_code: ev.reason_code,
        duration_ms: Number(ev.duration_ms) || 0,
        message_count: ev.message_count || 0,
        blocked_count: ev.blocked_count || 0,
        masked_count: ev.masked_count || 0,
        suspicious_count: ev.suspicious_count || 0,
        masked_kinds: evKinds,
        alarm: evAlarm,
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
        masked_kinds: {},
        alarm: false,
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
    if (evAlarm) {
      group.alarm = true;
    }
    for (const [kind, count] of Object.entries(evKinds)) {
      group.masked_kinds[kind] = (group.masked_kinds[kind] || 0) + count;
    }
  }

  return groups;
}

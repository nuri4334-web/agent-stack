export const SECRET_ALARM_WARNING = // UI warning text (for example when security.alarm is true)
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
 * Returns the warning text when suspicious messages were removed before reaching the AI.
 * Accepts either a `security` summary object (`{ suspicious }`) or a raw count.
 */
export function getSuspiciousWarning(securityOrCount) {
  const raw =
    typeof securityOrCount === 'object' && securityOrCount !== null
      ? securityOrCount.suspicious
      : securityOrCount;
  if (typeof raw === 'boolean') {
    return '';
  }
  const num = Number(raw);
  if (!Number.isFinite(num) || num <= 0) {
    return '';
  }
  const count = Math.floor(num);
  if (count <= 0) {
    return '';
  }
  if (count === 1) {
    return '1 message was removed for security reasons.';
  }
  return `${count} messages were removed for security reasons.`;
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

export const CHANNEL_PICKER_HINT =
  'To ask about a channel, start with # and pick it from the list.';

/**
 * Normalizes a list of channel objects (`[{ name }]`) or strings (`["dev"]`)
 * into a deduplicated array of lowercase, non-empty channel names.
 */
export function normalizeChannelList(channels) {
  if (!Array.isArray(channels)) {
    return [];
  }
  const seen = new Set();
  const result = [];
  for (const item of channels) {
    let raw = '';
    if (typeof item === 'string') {
      raw = item;
    } else if (item && typeof item === 'object' && typeof item.name === 'string') {
      raw = item.name;
    }
    const cleaned = raw.toLowerCase().trim();
    if (cleaned && !seen.has(cleaned)) {
      seen.add(cleaned);
      result.push(cleaned);
    }
  }
  return result;
}

/**
 * Filters channels by prefix query (ignoring a leading `#`, case-insensitive).
 */
export function filterChannels(channels, query = '') {
  const list = normalizeChannelList(channels);
  if (typeof query !== 'string') {
    return list;
  }
  const prefix = (query.startsWith('#') ? query.slice(1) : query).toLowerCase();
  if (!prefix) {
    return list;
  }
  return list.filter((name) => name.startsWith(prefix));
}

/**
 * Determines the highlight color ('blue' | 'red' | null) for a single token.
 * Apostrophe suffixes (e.g. `#genel'i`, `#genel’i`) are not part of the channel name.
 * Pure numeric tokens (`#42`) and tokens not starting with `#` (`C#`) return `null`.
 */
export function getChannelTokenColor(token, knownChannels) {
  if (typeof token !== 'string' || !token.startsWith('#')) {
    return null;
  }
  const match = /^#([\p{L}\p{N}_-]+)(?:['’][\p{L}\p{N}_-]*)?$/u.exec(token);
  if (!match) {
    return null;
  }
  const channelName = match[1];
  if (/^\d+$/.test(channelName)) {
    return null;
  }
  const known = normalizeChannelList(knownChannels);
  return known.includes(channelName.toLowerCase()) ? 'blue' : 'red';
}

/**
 * Splits question text into contiguous segments without losing any characters:
 * `{ text: string, color: 'blue' | 'red' | null, channel: string | null }`.
 */
export function tokenizeQuestionChannels(text, knownChannels) {
  if (typeof text !== 'string' || text.length === 0) {
    return [];
  }
  const knownSet = new Set(normalizeChannelList(knownChannels));
  const segments = [];
  const regex = /#([\p{L}\p{N}_-]+)/gu;
  let plainStart = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    const matchIndex = match.index;
    const fullToken = match[0];
    const rawChannel = match[1];
    const prevChar = matchIndex > 0 ? text[matchIndex - 1] : '';

    if ((prevChar && /[\p{L}\p{N}_]/u.test(prevChar)) || /^\d+$/.test(rawChannel)) {
      continue;
    }

    if (matchIndex > plainStart) {
      segments.push({
        text: text.slice(plainStart, matchIndex),
        color: null,
        channel: null,
      });
    }

    const channel = rawChannel.toLowerCase();
    const color = knownSet.has(channel) ? 'blue' : 'red';
    segments.push({
      text: fullToken,
      color,
      channel,
    });

    plainStart = matchIndex + fullToken.length;
  }

  if (plainStart < text.length) {
    segments.push({
      text: text.slice(plainStart),
      color: null,
      channel: null,
    });
  }

  return segments;
}

/**
 * Finds an active `#query` at the end of `text.slice(0, cursorIndex)`.
 * `#` must be at the start of `text` or preceded by whitespace.
 */
export function getActiveChannelQuery(text, cursorIndex = text?.length) {
  if (typeof text !== 'string' || text.length === 0) {
    return null;
  }
  const resolvedCursor =
    typeof cursorIndex === 'number' && !Number.isNaN(cursorIndex)
      ? Math.min(Math.max(0, cursorIndex), text.length)
      : text.length;
  const prefix = text.slice(0, resolvedCursor);
  const match = /(?:^|\s)#([\p{L}\p{N}_-]*)$/u.exec(prefix);
  if (!match) {
    return null;
  }
  const query = match[1];
  const start = resolvedCursor - query.length - 1;
  return {
    query,
    start,
    end: resolvedCursor,
  };
}

/**
 * Replaces the active `#query` up to `cursorIndex` with `#${channelName} `
 * and returns the updated text string.
 */
export function applyChannelSelection(text, channelName, cursorIndex = text?.length) {
  if (typeof text !== 'string') {
    return '';
  }
  if (typeof channelName !== 'string') {
    return text;
  }
  const cleanedChannel = channelName.trim().replace(/^#+/, '').toLowerCase();
  if (!cleanedChannel) {
    return text;
  }
  const active = getActiveChannelQuery(text, cursorIndex);
  if (!active) {
    return text;
  }
  return `${text.slice(0, active.start)}#${cleanedChannel} ${text.slice(active.end)}`;
}

/**
 * Returns whether the question form can be submitted.
 * Unrecognized (red) channel names are still allowed to be submitted (K4).
 */
export function canSubmitQuestion(question, isSubmitting = false) {
  if (isSubmitting) {
    return false;
  }
  if (typeof question !== 'string') {
    return false;
  }
  return question.trim().length > 0;
}

export const MASKED_TEXT_PREVIEW_LENGTH = 120;
export const EMPTY_MASKED_TEXTS_MESSAGE = 'No masked texts yet.';
export const FORBIDDEN_MASKED_TEXTS_MESSAGE = "You don't have permission.";

/**
 * Formats the `kind` field of a masked text entry for display in the Security Panel (K2, K3).
 */
export function formatMaskedTextKind(kind) {
  if (kind === 'sent') {
    return 'Sent to AI';
  }
  if (kind === 'removed_suspicious') {
    return 'Removed as suspicious';
  }
  if (kind === null || kind === undefined || kind === '') {
    return '—';
  }
  if (typeof kind === 'string') {
    return kind.trim() ? kind : '—';
  }
  return '—';
}

/**
 * Returns true when a masked text entry represents a message removed as suspicious (K3).
 */
export function isSuspiciousMaskedTextKind(kind) {
  return kind === 'removed_suspicious';
}

/**
 * Truncates long masked text for preview while keeping placeholders ([REDACTED], PERSON_1, etc.) untouched (K4).
 */
export function truncateMaskedText(
  text,
  maxLength = MASKED_TEXT_PREVIEW_LENGTH,
  expanded = false,
) {
  if (typeof text !== 'string' || text.length === 0) {
    return { displayText: '', isTruncated: false, canToggle: false };
  }
  const limit =
    typeof maxLength === 'number' && maxLength > 0
      ? maxLength
      : MASKED_TEXT_PREVIEW_LENGTH;
  if (text.length <= limit) {
    return { displayText: text, isTruncated: false, canToggle: false };
  }
  if (!expanded) {
    return {
      displayText: `${text.slice(0, limit)}…`,
      isTruncated: true,
      canToggle: true,
    };
  }
  return {
    displayText: text,
    isTruncated: false,
    canToggle: true,
  };
}

/**
 * Generates a stable row key for a masked text entry.
 */
export function getMaskedTextKey(item, index = 0) {
  return `${item?.created_at || ''}-${item?.request_id || 'no-req'}-${item?.kind || ''}-${item?.channel || 'no-ch'}-${index}`;
}



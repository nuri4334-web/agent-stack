import assert from 'node:assert/strict';
import { before, describe, it } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { runnerImport } from 'vite';

import {
  SECRET_ALARM_WARNING,
  formatMaskedKinds,
  getDisplayedQuestion,
  groupEventsByRequestId,
  normalizeMaskedKinds,
  normalizeSecuritySummary,
} from '../src/security.js';

describe('S3-11: Secret rotation warning and security panel masked kinds', () => {
  let ChatAnswerView;
  let SecurityEventsTable;

  before(async () => {
    const appModule = await runnerImport('./src/App.jsx');
    ChatAnswerView = appModule.module.ChatAnswerView;
    SecurityEventsTable = appModule.module.SecurityEventsTable;
  });

  describe('1. Warning text and security summary normalization', () => {
    it('defines the exact English rotation warning text required by S3-11', () => {
      assert.equal(
        SECRET_ALARM_WARNING,
        'A secret was found in your message and was not sent to the AI. Please rotate this key.',
      );
    });

    it('treats missing security or missing alarm as false (API contract v4 section 0)', () => {
      assert.deepEqual(normalizeSecuritySummary(undefined), {
        blocked: 0,
        masked: 0,
        suspicious: 0,
        alarm: false,
      });
      assert.deepEqual(normalizeSecuritySummary({ blocked: 1, masked: 2, suspicious: 0 }), {
        blocked: 1,
        masked: 2,
        suspicious: 0,
        alarm: false,
      });
    });

    it('sets alarm to true only when security.alarm is strictly true', () => {
      assert.equal(
        normalizeSecuritySummary({ blocked: 0, masked: 1, suspicious: 0, alarm: true }).alarm,
        true,
      );
      assert.equal(
        normalizeSecuritySummary({ blocked: 0, masked: 1, suspicious: 0, alarm: false }).alarm,
        false,
      );
      assert.equal(
        normalizeSecuritySummary({ blocked: 0, masked: 1, suspicious: 0, alarm: 'true' }).alarm,
        false,
      );
    });

    it('hides the raw sent question when security.alarm is true so the secret value is never shown', () => {
      const fakeToken = ['xoxb', '0000', 'EXAMPLE'].join('-');
      const fakeQuestionWithKey = `try with this key: ${fakeToken}`;
      const displayedOnAlarm = getDisplayedQuestion(fakeQuestionWithKey, { alarm: true });
      assert.equal(displayedOnAlarm, '[REDACTED]');
      assert.equal(displayedOnAlarm.includes(fakeToken), false);

      const normalQuestion = 'summarize #dev';
      assert.equal(getDisplayedQuestion(normalQuestion, { alarm: false }), 'summarize #dev');
      assert.equal(getDisplayedQuestion(normalQuestion, {}), 'summarize #dev');
      assert.equal(getDisplayedQuestion('', { alarm: true }), '');
    });
  });

  describe('2. ChatAnswerView component rendering (Step 1)', () => {
    it('renders the yellow warning box above the answer when security.alarm is true and never shows secret values', () => {
      const answerData = {
        request_id: '7c2e9a0b1d3f',
        status: 'ok',
        answer: 'The deploy in #dev failed because the token was refused.',
        sources: [
          {
            id: 'C0C83M051QD:1792665328.994119',
            channel: 'dev',
            author: 'Deniz Aydın',
            time: '2026-10-22T11:05:00+00:00',
            text: 'deploy failed again, the token is [REDACTED]',
          },
        ],
        security: { blocked: 0, masked: 2, suspicious: 0, alarm: true },
      };

      const html = renderToStaticMarkup(React.createElement(ChatAnswerView, { answerData }));

      assert.ok(html.includes(SECRET_ALARM_WARNING), 'Warning text must be rendered');
      assert.ok(html.includes('alarm-warning-box'), 'Warning box must have alarm-warning-box class');
      assert.ok(html.includes('role="alert"'), 'Warning box must have role="alert"');

      const warningIndex = html.indexOf(SECRET_ALARM_WARNING);
      const answerIndex = html.indexOf(answerData.answer);
      assert.ok(
        warningIndex !== -1 && answerIndex !== -1 && warningIndex < answerIndex,
        'Warning box must appear above the answer',
      );
      assert.ok(!html.includes('xoxb-'), 'Secret value must never appear in the rendered HTML');
    });

    it('does not render the warning box when security.alarm is false or omitted', () => {
      const normalAnswer = {
        request_id: '3f9c2a1b7d4e',
        status: 'ok',
        answer: 'This week in #dev the login page was discussed.',
        sources: [],
        security: { blocked: 0, masked: 0, suspicious: 0, alarm: false },
      };
      const htmlFalse = renderToStaticMarkup(
        React.createElement(ChatAnswerView, { answerData: normalAnswer }),
      );
      assert.equal(htmlFalse.includes(SECRET_ALARM_WARNING), false);

      const preS308Answer = {
        request_id: '3f9c2a1b7d4e',
        status: 'ok',
        answer: 'This week in #dev the login page was discussed.',
        sources: [],
        security: { blocked: 0, masked: 1, suspicious: 0 },
      };
      const htmlMissing = renderToStaticMarkup(
        React.createElement(ChatAnswerView, { answerData: preS308Answer }),
      );
      assert.equal(htmlMissing.includes(SECRET_ALARM_WARNING), false);
    });

    it('does not render the secret warning box on a no_access response', () => {
      const noAccessAnswer = {
        request_id: '9a1b2c3d4e5f',
        status: 'no_access',
        answer: "You don't have access to this information.",
        sources: [],
        security: { blocked: 0, masked: 0, suspicious: 0, alarm: false },
      };
      const html = renderToStaticMarkup(
        React.createElement(ChatAnswerView, { answerData: noAccessAnswer }),
      );
      assert.equal(html.includes(SECRET_ALARM_WARNING), false);
      assert.ok(html.includes('Access Restricted:'));
    });
  });

  describe('3. Masked kinds formatting and event grouping (Step 2)', () => {
    it('formats masked_kinds as "<count> <kind>" separated by commas', () => {
      assert.equal(
        formatMaskedKinds({ slack_token: 1, email: 2 }),
        '1 slack_token, 2 email',
      );
      assert.equal(
        formatMaskedKinds({ slack_token: 2, person: 3 }),
        '2 slack_token, 3 person',
      );
    });

    it('treats missing, empty, or zero-count masked_kinds as empty', () => {
      assert.deepEqual(normalizeMaskedKinds(undefined), {});
      assert.deepEqual(normalizeMaskedKinds(null), {});
      assert.deepEqual(normalizeMaskedKinds({}), {});
      assert.deepEqual(normalizeMaskedKinds({ slack_token: 0, email: -1 }), {});
      assert.equal(formatMaskedKinds(undefined), '');
      assert.equal(formatMaskedKinds({}), '');
    });

    it('aggregates masked_kinds and propagates alarm across steps when grouping by request_id', () => {
      const sampleEvents = [
        {
          created_at: '2026-11-12T09:12:05+00:00',
          request_id: '7c2e9a0b1d3f',
          person: 'ali',
          channel: 'dev',
          step: 'response_check',
          decision: 'passed',
          reason_code: null,
          message_count: 2,
          blocked_count: 1,
          masked_count: 1,
          suspicious_count: 0,
          masked_kinds: { slack_token: 1 },
          alarm: false,
          duration_ms: 0.5,
        },
        {
          created_at: '2026-11-12T09:12:03+00:00',
          request_id: '7c2e9a0b1d3f',
          person: 'ali',
          channel: 'dev',
          step: 'sanitization',
          decision: 'passed',
          reason_code: null,
          message_count: 2,
          blocked_count: 0,
          masked_count: 3,
          suspicious_count: 0,
          masked_kinds: { slack_token: 1, email: 2 },
          alarm: true,
          duration_ms: 0.81,
        },
        {
          created_at: '2026-11-12T09:10:00+00:00',
          request_id: '3f9c2a1b7d4e',
          person: 'ali',
          channel: 'yonetim',
          step: 'authorization',
          decision: 'stopped',
          reason_code: 'NOT_CHANNEL_MEMBER',
          message_count: 0,
          blocked_count: 0,
          masked_count: 0,
          suspicious_count: 0,
          masked_kinds: {},
          alarm: false,
          duration_ms: 0.42,
        },
      ];

      const groups = groupEventsByRequestId(sampleEvents);
      assert.equal(groups.length, 2);

      const alarmGroup = groups[0];
      assert.equal(alarmGroup.request_id, '7c2e9a0b1d3f');
      assert.equal(alarmGroup.alarm, true);
      assert.equal(alarmGroup.masked_count, 4);
      assert.deepEqual(alarmGroup.masked_kinds, { slack_token: 2, email: 2 });
      assert.equal(formatMaskedKinds(alarmGroup.masked_kinds), '2 slack_token, 2 email');

      const stoppedGroup = groups[1];
      assert.equal(stoppedGroup.request_id, '3f9c2a1b7d4e');
      assert.equal(stoppedGroup.alarm, false);
      assert.deepEqual(stoppedGroup.masked_kinds, {});
    });
  });

  describe('4. SecurityEventsTable component rendering (Steps 2 & 3)', () => {
    const events = [
      {
        created_at: '2026-11-12T09:12:03+00:00',
        request_id: '7c2e9a0b1d3f',
        person: 'ali',
        channel: 'dev',
        step: 'sanitization',
        decision: 'passed',
        reason_code: null,
        message_count: 0,
        blocked_count: 0,
        masked_count: 3,
        suspicious_count: 0,
        masked_kinds: { slack_token: 1, email: 2 },
        alarm: true,
        duration_ms: 0.81,
      },
      {
        created_at: '2026-11-12T09:12:01+00:00',
        request_id: '7c2e9a0b1d3f',
        person: 'ali',
        channel: 'dev',
        step: 'identity',
        decision: 'passed',
        reason_code: null,
        message_count: 0,
        blocked_count: 0,
        masked_count: 0,
        suspicious_count: 0,
        masked_kinds: {},
        alarm: false,
        duration_ms: 0.12,
      },
      {
        created_at: '2026-10-30T09:12:03+00:00',
        request_id: '3f9c2a1b7d4e',
        person: 'ali',
        channel: 'yonetim',
        step: 'authorization',
        decision: 'stopped',
        reason_code: 'NOT_CHANNEL_MEMBER',
        message_count: 0,
        blocked_count: 0,
        masked_count: 0,
        suspicious_count: 0,
        duration_ms: 0.42,
      },
    ];

    it('renders Masked Kinds column, kind counts, and ALARM indicator in all-steps view', () => {
      const html = renderToStaticMarkup(
        React.createElement(SecurityEventsTable, {
          events,
          groupByRequest: false,
          expandedRequests: {},
        }),
      );

      assert.ok(html.includes('table-container'), 'Table must be wrapped in .table-container');
      assert.ok(html.includes('Masked Kinds'), 'Table header must include Masked Kinds column');
      assert.ok(
        html.includes('1 slack_token, 2 email'),
        'Event row must display formatted masked_kinds',
      );
      assert.ok(
        html.includes('<span class="alarm-badge">ALARM</span>'),
        'Alarm event row must display ALARM badge',
      );
      assert.ok(html.includes('data-alarm="true"'), 'Alarm event row must have data-alarm="true"');
      assert.ok(
        html.includes('data-alarm="false"'),
        'Non-alarm event rows must have data-alarm="false"',
      );
    });

    it('marks the grouped request row with ALARM and shows aggregated masked_kinds in grouped view', () => {
      const html = renderToStaticMarkup(
        React.createElement(SecurityEventsTable, {
          events,
          groupByRequest: true,
          expandedRequests: { '7c2e9a0b1d3f': true },
        }),
      );

      assert.ok(html.includes('2 steps'), 'Grouped row must summarize step count');
      assert.ok(
        html.includes('1 slack_token, 2 email'),
        'Grouped row must display aggregated masked_kinds',
      );
      assert.ok(
        html.includes('<span class="alarm-badge">ALARM</span>'),
        'Grouped request with alarm must display ALARM badge',
      );
      assert.ok(html.includes('↳ step'), 'Expanded group must render child step rows');
    });
  });
});

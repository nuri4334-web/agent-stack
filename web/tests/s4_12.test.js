import assert from 'node:assert/strict';
import { before, describe, it } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { runnerImport } from 'vite';

import {
  SECRET_ALARM_WARNING,
  getSuspiciousWarning,
  normalizeSecuritySummary,
} from '../src/security.js';

describe('S4-12: Suspicious message warning and security summary', () => {
  let ChatAnswerView;

  before(async () => {
    const appModule = await runnerImport('./src/App.jsx');
    ChatAnswerView = appModule.module.ChatAnswerView;
  });

  describe('K5 & K1: getSuspiciousWarning pure function', () => {
    it('test_k5_get_suspicious_warning_returns_empty_for_zero_or_missing', () => {
      assert.equal(getSuspiciousWarning(0), '');
      assert.equal(getSuspiciousWarning({ suspicious: 0 }), '');
      assert.equal(getSuspiciousWarning({}), '');
      assert.equal(getSuspiciousWarning(undefined), '');
      assert.equal(getSuspiciousWarning(null), '');
      assert.equal(getSuspiciousWarning({ suspicious: -1 }), '');
      assert.equal(getSuspiciousWarning({ suspicious: 'invalid' }), '');
    });

    it('test_k5_get_suspicious_warning_returns_singular_for_one', () => {
      assert.equal(
        getSuspiciousWarning(1),
        '1 message was removed for security reasons.',
      );
      assert.equal(
        getSuspiciousWarning({ suspicious: 1 }),
        '1 message was removed for security reasons.',
      );
    });

    it('test_k5_get_suspicious_warning_returns_plural_for_two_or_more', () => {
      assert.equal(
        getSuspiciousWarning(2),
        '2 messages were removed for security reasons.',
      );
      assert.equal(
        getSuspiciousWarning({ suspicious: 2 }),
        '2 messages were removed for security reasons.',
      );
      assert.equal(
        getSuspiciousWarning(5),
        '5 messages were removed for security reasons.',
      );
      assert.equal(
        getSuspiciousWarning({ blocked: 0, masked: 1, suspicious: 3, alarm: false }),
        '3 messages were removed for security reasons.',
      );
    });
  });

  describe('K1, K2 & K4: ChatAnswerView component rendering', () => {
    it('test_k1_chat_answer_view_renders_singular_warning_above_answer_when_suspicious_is_1', () => {
      const answerData = {
        request_id: 'a1b2c3d4e5f6',
        status: 'ok',
        answer: 'The release notes were shared in #dev.',
        sources: [
          {
            id: 'C01:1700000000.000100',
            channel: 'dev',
            author: 'Ali',
            time: '2026-11-22T10:00:00+00:00',
            text: 'Release notes are ready.',
          },
        ],
        security: { blocked: 0, masked: 0, suspicious: 1, alarm: false },
      };

      const html = renderToStaticMarkup(React.createElement(ChatAnswerView, { answerData }));
      const expectedWarning = '1 message was removed for security reasons.';

      assert.ok(html.includes(expectedWarning), 'Singular suspicious warning must be rendered');
      assert.equal(html.includes(SECRET_ALARM_WARNING), false);

      const warningIndex = html.indexOf(expectedWarning);
      const answerIndex = html.indexOf(answerData.answer);
      assert.ok(
        warningIndex !== -1 && answerIndex !== -1 && warningIndex < answerIndex,
        'Suspicious warning must appear above the answer',
      );
    });

    it('test_k1_chat_answer_view_renders_plural_warning_above_answer_when_suspicious_is_2_or_more', () => {
      const answerData = {
        request_id: 'b2c3d4e5f6a1',
        status: 'ok',
        answer: 'No messages were found for this question.',
        sources: [],
        security: { blocked: 0, masked: 0, suspicious: 2, alarm: false },
      };

      const html = renderToStaticMarkup(React.createElement(ChatAnswerView, { answerData }));
      const expectedWarning = '2 messages were removed for security reasons.';

      assert.ok(html.includes(expectedWarning), 'Plural suspicious warning must be rendered');

      const warningIndex = html.indexOf(expectedWarning);
      const answerIndex = html.indexOf(answerData.answer);
      assert.ok(
        warningIndex !== -1 && answerIndex !== -1 && warningIndex < answerIndex,
        'Plural suspicious warning must appear above the answer',
      );
    });

    it('test_k1_chat_answer_view_omits_suspicious_warning_when_suspicious_is_0_or_missing', () => {
      const zeroSuspiciousAnswer = {
        request_id: 'c3d4e5f6a1b2',
        status: 'ok',
        answer: 'Normal discussion in #general.',
        sources: [],
        security: { blocked: 0, masked: 0, suspicious: 0, alarm: false },
      };

      const htmlZero = renderToStaticMarkup(
        React.createElement(ChatAnswerView, { answerData: zeroSuspiciousAnswer }),
      );
      assert.equal(htmlZero.includes('removed for security reasons.'), false);

      const missingSuspiciousAnswer = {
        request_id: 'd4e5f6a1b2c3',
        status: 'ok',
        answer: 'Normal discussion in #general.',
        sources: [],
        security: {},
      };

      const htmlMissing = renderToStaticMarkup(
        React.createElement(ChatAnswerView, { answerData: missingSuspiciousAnswer }),
      );
      assert.equal(htmlMissing.includes('removed for security reasons.'), false);
    });

    it('test_k2_chat_answer_view_renders_suspicious_and_rotate_key_warnings_together_without_mixing', () => {
      const answerData = {
        request_id: 'e5f6a1b2c3d4',
        status: 'ok',
        answer: 'Summary after filtering suspicious message and redacting user secret.',
        sources: [],
        security: { blocked: 0, masked: 1, suspicious: 2, alarm: true },
      };

      const html = renderToStaticMarkup(React.createElement(ChatAnswerView, { answerData }));
      const suspiciousWarning = '2 messages were removed for security reasons.';

      assert.ok(html.includes(SECRET_ALARM_WARNING), 'Secret rotation warning must be visible');
      assert.ok(html.includes(suspiciousWarning), 'Suspicious message warning must be visible');

      const alarmIndex = html.indexOf(SECRET_ALARM_WARNING);
      const suspiciousIndex = html.indexOf(suspiciousWarning);
      const answerIndex = html.indexOf(answerData.answer);

      assert.ok(
        alarmIndex !== -1 && alarmIndex < answerIndex,
        'Secret rotation warning must appear above the answer',
      );
      assert.ok(
        suspiciousIndex !== -1 && suspiciousIndex < answerIndex,
        'Suspicious warning must appear above the answer',
      );

      const firstWarningEnd = Math.min(alarmIndex, suspiciousIndex);
      const secondWarningStart = Math.max(alarmIndex, suspiciousIndex);
      const betweenWarnings = html.slice(firstWarningEnd, secondWarningStart);
      assert.ok(
        betweenWarnings.includes('</div>'),
        'Both warnings must be rendered in separate elements and not mixed together',
      );
    });

    it('test_k4_chat_answer_view_shows_suspicious_count_in_security_summary', () => {
      const answerData = {
        request_id: 'f6a1b2c3d4e5',
        status: 'ok',
        answer: 'Checked messages.',
        sources: [],
        security: { blocked: 1, masked: 2, suspicious: 3, alarm: false },
      };

      assert.equal(normalizeSecuritySummary(answerData.security).suspicious, 3);

      const html = renderToStaticMarkup(React.createElement(ChatAnswerView, { answerData }));
      assert.ok(
        html.includes('Blocked: 1 | Masked: 2 | Suspicious: 3'),
        'Security Summary row must display the suspicious count from security.suspicious',
      );
    });
  });
});

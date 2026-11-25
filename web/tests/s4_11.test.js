import assert from 'node:assert/strict';
import { before, describe, it } from 'node:test';
import { runnerImport } from 'vite';

import {
  CHANNEL_PICKER_HINT,
  applyChannelSelection,
  canSubmitQuestion,
  filterChannels,
  getActiveChannelQuery,
  getChannelTokenColor,
  normalizeChannelList,
  tokenizeQuestionChannels,
} from '../src/security.js';

describe('S4-11: Question box # channel picker and blue/red highlighting', () => {
  let getChannels;
  let ApiError;

  before(async () => {
    const apiModule = await runnerImport('./src/api.js');
    getChannels = apiModule.module.getChannels;
    ApiError = apiModule.module.ApiError;
  });

  describe('K1: Channel list fetching and normalization', () => {
    it('test_k1_get_channels_fetches_channel_list_and_throws_api_error_on_failure', async () => {
      const originalFetch = globalThis.fetch;
      const calls = [];
      try {
        globalThis.fetch = async (url, options) => {
          calls.push({ url, options });
          return {
            ok: true,
            status: 200,
            json: async () => ({
              channels: [{ name: 'dev' }, { name: 'genel' }],
            }),
          };
        };

        const channels = await getChannels();
        assert.equal(calls.length, 1);
        assert.ok(calls[0].url.endsWith('/api/channels'));
        assert.equal(calls[0].options?.credentials, 'include');
        assert.deepEqual(channels, [{ name: 'dev' }, { name: 'genel' }]);

        globalThis.fetch = async () => ({
          ok: false,
          status: 401,
          json: async () => ({
            error: { code: 'UNAUTHENTICATED', message: 'Not signed in.' },
          }),
        });

        await assert.rejects(
          () => getChannels(),
          (err) => err instanceof ApiError && err.status === 401,
        );
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('test_k1_normalize_channel_list_handles_objects_strings_and_empty_fallbacks', () => {
      assert.deepEqual(
        normalizeChannelList([{ name: 'dev' }, { name: 'genel' }]),
        ['dev', 'genel'],
      );
      assert.deepEqual(normalizeChannelList(['DEV', 'Genel']), ['dev', 'genel']);
      assert.deepEqual(normalizeChannelList(null), []);
      assert.deepEqual(normalizeChannelList(undefined), []);
      assert.deepEqual(normalizeChannelList([]), []);
    });
  });

  describe('K2 & K7: Active # query detection, channel filtering, and selection', () => {
    const channels = [{ name: 'dev' }, { name: 'genel' }];

    it('test_k2_filter_channels_opens_on_hash_and_filters_by_prefix_as_user_types', () => {
      assert.deepEqual(filterChannels(channels, ''), ['dev', 'genel']);
      assert.deepEqual(filterChannels(channels, '#'), ['dev', 'genel']);
      assert.deepEqual(filterChannels(channels, 'ge'), ['genel']);
      assert.deepEqual(filterChannels(channels, '#ge'), ['genel']);
      assert.deepEqual(filterChannels(channels, 'DEV'), ['dev']);
      assert.deepEqual(filterChannels(channels, '#yon'), []);
    });

    it('test_k2_get_active_channel_query_and_apply_channel_selection', () => {
      assert.deepEqual(getActiveChannelQuery('merhaba #ge', 11), {
        query: 'ge',
        start: 8,
        end: 11,
      });
      assert.deepEqual(getActiveChannelQuery('#', 1), {
        query: '',
        start: 0,
        end: 1,
      });
      assert.equal(getActiveChannelQuery('C#', 2), null);
      assert.equal(getActiveChannelQuery("#genel'i", 8), null);
      assert.equal(getActiveChannelQuery('#genel özet', 11), null);

      assert.equal(
        applyChannelSelection('merhaba #ge', 'genel', 11),
        'merhaba #genel ',
      );
      assert.equal(applyChannelSelection('#', 'dev', 1), '#dev ');
    });
  });

  describe('K3 & K7: Blue/red channel token coloring and question tokenization', () => {
    const knownChannels = [{ name: 'dev' }, { name: 'genel' }];

    it('test_k3_get_channel_token_color_covers_known_unknown_apostrophe_numeric_and_c_sharp', () => {
      assert.equal(getChannelTokenColor('#genel', knownChannels), 'blue');
      assert.equal(getChannelTokenColor('#dev', knownChannels), 'blue');
      assert.equal(getChannelTokenColor("#genel'i", knownChannels), 'blue');
      assert.equal(getChannelTokenColor('#genel’i', knownChannels), 'blue');
      assert.equal(getChannelTokenColor('#geneli', knownChannels), 'red');
      assert.equal(getChannelTokenColor('#yonetim', knownChannels), 'red');
      assert.equal(getChannelTokenColor('#42', knownChannels), null);
      assert.equal(getChannelTokenColor('C#', knownChannels), null);
      assert.equal(getChannelTokenColor('#', knownChannels), null);
      assert.equal(getChannelTokenColor('genel', knownChannels), null);
    });

    it('test_k3_tokenize_question_channels_splits_apostrophe_suffix_and_preserves_text', () => {
      const text = "#genel'i ve #geneli özetle";
      const segments = tokenizeQuestionChannels(text, knownChannels);

      assert.equal(
        segments.map((s) => s.text).join(''),
        text,
      );

      const blueSegment = segments.find((s) => s.text === '#genel');
      assert.deepEqual(blueSegment, {
        text: '#genel',
        color: 'blue',
        channel: 'genel',
      });

      const redSegment = segments.find((s) => s.text === '#geneli');
      assert.deepEqual(redSegment, {
        text: '#geneli',
        color: 'red',
        channel: 'geneli',
      });

      const apostrophePiece = segments.find((s) => s.text.startsWith("'i"));
      assert.ok(apostrophePiece);
      assert.equal(apostrophePiece.color, null);
      assert.equal(apostrophePiece.channel, null);
    });

    it('test_k7_tokenize_question_channels_ignores_numeric_hashes_and_c_sharp_in_sentence', () => {
      const text = 'C# geliştiricisi PR #42 hakkında #dev ve #yonetim kanallarına yazdı';
      const segments = tokenizeQuestionChannels(text, ['dev', 'genel']);

      assert.equal(
        segments.map((s) => s.text).join(''),
        text,
      );

      const colored = segments.filter((s) => s.color !== null);
      assert.deepEqual(colored, [
        { text: '#dev', color: 'blue', channel: 'dev' },
        { text: '#yonetim', color: 'red', channel: 'yonetim' },
      ]);
    });
  });

  describe('K4, K5 & K6: Submission with red channel, hint text, and double-click guard', () => {
    it('test_k4_can_submit_question_allows_sending_with_unrecognized_red_channel', () => {
      assert.equal(canSubmitQuestion('#geneli özetle', false), true);
      assert.equal(canSubmitQuestion('#yonetim kanalında ne konuşuldu?', false), true);
    });

    it('test_k5_channel_picker_hint_matches_exact_specification', () => {
      assert.equal(
        CHANNEL_PICKER_HINT,
        'To ask about a channel, start with # and pick it from the list.',
      );
    });

    it('test_k6_can_submit_question_blocks_second_rapid_submit_and_empty_input', () => {
      assert.equal(canSubmitQuestion('#genel özetle', false), true);
      assert.equal(canSubmitQuestion('#genel özetle', true), false);
      assert.equal(canSubmitQuestion('', false), false);
      assert.equal(canSubmitQuestion('   ', false), false);
    });
  });
});

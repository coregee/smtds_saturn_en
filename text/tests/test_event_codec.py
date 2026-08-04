import unittest

from text.script.encoding.event_codec import (
    MAX_EXPANSION,
    base_token_runs,
    dictionary_from_manifest,
    train_event_dictionary,
)


class EventCodecTests(unittest.TestCase):
    def test_dictionary_is_deterministic_and_bounded(self) -> None:
        sequences = [
            [56, 44, 41, 0, 56, 44, 41, 0],
            [61, 51, 57, 0, 56, 44, 41, 0],
            [56, 51, 0, 56, 44, 41, 54, 41],
        ]
        first = train_event_dictionary(sequences)
        second = train_event_dictionary(sequences)
        self.assertEqual(first, second)
        self.assertTrue(all(2 <= len(row) <= MAX_EXPANSION for row in first.expansions))
        self.assertEqual(dictionary_from_manifest(first.manifest()), first)

    def test_dictionary_stream_round_trips_direct_words_and_controls(self) -> None:
        training_codes = [
            56,
            44,
            41,
            267,
            56,
            44,
            41,
            267,
            61,
            51,
            57,
            267,
            56,
            44,
            41,
            54,
            41,
        ]
        dictionary = train_event_dictionary(base_token_runs(training_codes))
        words = [
            56,
            44,
            41,
            267,
            61,
            51,
            57,
            176,  # punctuation remains a direct FONT16 word
            0x8001,  # EVENT newline remains a direct control word
            56,
            44,
            41,
            54,
            41,
        ]
        encoded = dictionary.encode_codes(words)
        self.assertLess(len(encoded), len(words))
        self.assertEqual(dictionary.decode_words(encoded), words)


if __name__ == "__main__":
    unittest.main()

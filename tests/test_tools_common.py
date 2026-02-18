from __future__ import annotations

import unittest

from minerva.tools.common import resolve_telegram_chat_ids


class ResolveTelegramChatIdsTests(unittest.TestCase):
    def test_none_or_empty_returns_empty_list(self) -> None:
        self.assertEqual(resolve_telegram_chat_ids(None), [])
        self.assertEqual(resolve_telegram_chat_ids([]), [])
        self.assertEqual(resolve_telegram_chat_ids([""]), [])

    def test_comma_separated_values_are_split(self) -> None:
        self.assertEqual(
            resolve_telegram_chat_ids(["chat-a,chat-b", "chat-c"]),
            ["chat-a", "chat-b", "chat-c"],
        )

    def test_repeated_flags_are_preserved_in_order(self) -> None:
        self.assertEqual(
            resolve_telegram_chat_ids(["chat-a", "chat-b", "chat-a"]),
            ["chat-a", "chat-b", "chat-a"],
        )

    def test_whitespace_is_trimmed_and_empty_segments_ignored(self) -> None:
        self.assertEqual(
            resolve_telegram_chat_ids(["  chat-a  ,   , chat-b  ", "   chat-c   "]),
            ["chat-a", "chat-b", "chat-c"],
        )


if __name__ == "__main__":
    unittest.main()

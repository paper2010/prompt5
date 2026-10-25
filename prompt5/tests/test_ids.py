"""M0 · ids 测试：ULID 形态/唯一性、item_id 派生确定性与碰撞扩展、文法校验。"""

from __future__ import annotations

import re
import unittest

from prompt5.ids import (
    CROCKFORD,
    derive_item_id,
    is_valid_item_id,
    new_patch_id,
)

_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


class PatchIdTest(unittest.TestCase):
    def test_ulid_shape(self) -> None:
        pid = new_patch_id()
        self.assertEqual(len(pid), 26)
        self.assertRegex(pid, _ULID_RE)
        self.assertTrue(set(pid) <= set(CROCKFORD))

    def test_uniqueness(self) -> None:
        ids = {new_patch_id() for _ in range(500)}
        self.assertEqual(len(ids), 500)

    def test_timestamp_prefix_is_lexicographically_ordered(self) -> None:
        early = new_patch_id(timestamp_ms=1_700_000_000_000)
        late = new_patch_id(timestamp_ms=1_800_000_000_000)
        self.assertLess(early, late)


class ItemIdTest(unittest.TestCase):
    def test_deterministic(self) -> None:
        first = derive_item_id("01ARZ3NDEKTSV4RRFFQ69G5FAV", 0)
        second = derive_item_id("01ARZ3NDEKTSV4RRFFQ69G5FAV", 0)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 10)

    def test_different_op_index_differs(self) -> None:
        pid = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
        self.assertNotEqual(derive_item_id(pid, 0), derive_item_id(pid, 1))

    def test_collision_extends_by_two(self) -> None:
        pid = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
        base = derive_item_id(pid, 3)
        widened = derive_item_id(pid, 3, existing={base})
        self.assertEqual(len(widened), 12)
        self.assertTrue(widened.startswith(base))

    def test_grammar(self) -> None:
        self.assertTrue(is_valid_item_id(derive_item_id("01ARZ3NDEKTSV4RRFFQ69G5FAV", 7)))

    def test_rejects_negative_op_index(self) -> None:
        with self.assertRaises(ValueError):
            derive_item_id("01ARZ3NDEKTSV4RRFFQ69G5FAV", -1)


class GrammarTest(unittest.TestCase):
    def test_valid(self) -> None:
        for candidate in ("c-must-001", "f-a1b2c3", "abc-01", "a12345"):
            with self.subTest(candidate=candidate):
                self.assertTrue(is_valid_item_id(candidate))

    def test_invalid(self) -> None:
        for candidate in ("F-3", "ABC123", "abc", "abc_01", "-abc01", "abc01-", "a" * 17):
            with self.subTest(candidate=candidate):
                self.assertFalse(is_valid_item_id(candidate), candidate)


if __name__ == "__main__":
    unittest.main()

"""M0 · canonical（RFC 8785 JCS）测试：官方示例 + 数字格式 + UTF-16 键序 + 拒绝规则。"""

from __future__ import annotations

import unittest

from prompt5.canonical import (
    CanonicalError,
    dumps,
    number_to_string,
    sha256_hex,
    tuple_hash,
)


class NumberFormattingTest(unittest.TestCase):
    CASES = [
        (0, "0"),
        (-0.0, "0"),
        (0.5, "0.5"),
        (4.5, "4.5"),
        (100.0, "100"),
        (-1.5, "-1.5"),
        (123.456, "123.456"),
        (1e20, "100000000000000000000"),
        (10**20, "100000000000000000000"),
        (1e21, "1e+21"),
        (1e30, "1e+30"),
        (1e-6, "0.000001"),
        (1e-7, "1e-7"),
        (1e-27, "1e-27"),
        (2e-3, "0.002"),
        (333333333.33333329, "333333333.3333333"),
    ]

    def test_es_number_formatting(self) -> None:
        for value, expected in self.CASES:
            with self.subTest(value=value):
                self.assertEqual(number_to_string(value), expected)

    def test_rejects_non_finite(self) -> None:
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=bad), self.assertRaises(CanonicalError):
                number_to_string(bad)


class Rfc8785ExampleTest(unittest.TestCase):
    """RFC 8785 Appendix B 示例（键序、数字、字符串转义三项同时校验）。"""

    def test_appendix_example(self) -> None:
        data = {
            "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 0.000000000000000000000000001],
            "string": "€$\u000f\nA'B\"\\\\\"/",
            "literals": [None, True, False],
        }
        out = dumps(data)

        self.assertTrue(
            out.startswith('{"literals":[null,true,false],"numbers":['),
            f"键序错误：{out[:60]!r}",
        )
        self.assertIn("333333333.3333333,1e+30,4.5,0.002,1e-27", out)

        expected_value = (
            "€$" + "\\u000f" + "\\n" + "A'B" + '\\"' + "\\\\" + "\\\\" + '\\"' + "/"
        )
        self.assertIn('"string":"' + expected_value + '"', out)


class KeyOrderTest(unittest.TestCase):
    def test_ascii_and_bmp_order(self) -> None:
        self.assertEqual(dumps({"é": 1, "e": 2}), '{"e":2,"é":1}')

    def test_utf16_units_differs_from_codepoint(self) -> None:
        # U+10000 的 UTF-16 首单元 D800 < U+FFFF 的 FFFF：按 UTF-16 序它排前面，
        # 而按 Unicode 码点序 U+FFFF < U+10000 —— 此用例专门锚定 RFC 要求。
        self.assertEqual(dumps({"\uffff": 1, "\U00010000": 2}), '{"\U00010000":2,"\uffff":1}')

    def test_nested_sorting_is_stable(self) -> None:
        self.assertEqual(dumps({"b": {"z": 1, "a": 2}, "a": []}), '{"a":[],"b":{"a":2,"z":1}}')


class RejectionTest(unittest.TestCase):
    def test_lone_surrogate_string(self) -> None:
        with self.assertRaises(CanonicalError):
            dumps("\ud800")

    def test_lone_surrogate_key(self) -> None:
        with self.assertRaises(CanonicalError):
            dumps({"\udfff": 1})

    def test_non_string_key(self) -> None:
        with self.assertRaises(CanonicalError):
            dumps({1: "x"})

    def test_unsupported_type(self) -> None:
        with self.assertRaises(CanonicalError):
            dumps(object())


class ChecksumTest(unittest.TestCase):
    def test_checksum_is_key_order_independent(self) -> None:
        self.assertEqual(sha256_hex({"b": 2, "a": 1}), sha256_hex({"a": 1, "b": 2}))

    def test_checksum_shape(self) -> None:
        digest = sha256_hex({"a": 1})
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in digest))

    def test_tuple_hash_has_field_names(self) -> None:
        self.assertEqual(tuple_hash([("k", "v")]), sha256_hex([["k", "v"]]))
        self.assertNotEqual(tuple_hash([("k", "v1")]), tuple_hash([("k", "v2")]))
        self.assertNotEqual(tuple_hash([("a", "bc")]), tuple_hash([("ab", "c")]))

    def test_tuple_hash_rejects_wrong_arity(self) -> None:
        with self.assertRaises(CanonicalError):
            tuple_hash([("a", "b", "c")])  # type: ignore[list-item]


if __name__ == "__main__":
    unittest.main()

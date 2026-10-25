"""M3 · 统计检验测试：Wilcoxon 精确/近似、McNemar、bootstrap CI、TOST。"""

from __future__ import annotations

import pytest

from prompt5.modules.m5_eval.stats import (
    bootstrap_ci,
    mcnemar_exact,
    mean,
    tost_paired,
    wilcoxon_signed_rank,
)


class TestWilcoxon:
    def test_all_zero_diffs(self) -> None:
        result = wilcoxon_signed_rank([1, 2, 3], [1, 2, 3])
        assert result.p_value == 1.0
        assert result.method == "degenerate"

    def test_known_exact_small_sample(self) -> None:
        # 5 对全部同向差异 → 双侧精确 p = 2 * (1/32) = 0.0625
        result = wilcoxon_signed_rank([1.0, 1.0, 1.0, 1.0, 1.0], [0, 0, 0, 0, 0])
        assert result.method == "exact"
        assert result.p_value == pytest.approx(0.0625, abs=1e-9)

    def test_mixed_signs_not_significant(self) -> None:
        first = [1, 2, 3, 4, 5, 6]
        second = [0, 3, 2, 5, 4, 7]
        result = wilcoxon_signed_rank(first, second)
        assert result.p_value > 0.5

    def test_ties_use_average_ranks(self) -> None:
        result = wilcoxon_signed_rank([2, 2, 2, 2], [1, 1, 1, 1])
        assert result.n == 4
        assert result.p_value == pytest.approx(0.125, abs=1e-9)

    def test_normal_approximation_path(self) -> None:
        first = list(range(1, 30))
        second = [0] * 29
        result = wilcoxon_signed_rank(first, second, exact_limit=10)
        assert result.method == "normal"
        assert 0 < result.p_value < 0.05

    def test_length_mismatch(self) -> None:
        with pytest.raises(ValueError):
            wilcoxon_signed_rank([1, 2], [1])


class TestMcNemar:
    def test_no_discordant(self) -> None:
        assert mcnemar_exact(0, 0).p_value == 1.0

    def test_classic_b3_c0(self) -> None:
        result = mcnemar_exact(3, 0)
        assert result.p_value == pytest.approx(0.25, abs=1e-9)

    def test_balanced_not_significant(self) -> None:
        assert mcnemar_exact(5, 5).p_value == pytest.approx(1.0, abs=1e-9)

    def test_symmetric(self) -> None:
        assert mcnemar_exact(2, 7).p_value == mcnemar_exact(7, 2).p_value

    def test_large_discordant_is_significant(self) -> None:
        assert mcnemar_exact(15, 0).p_value < 0.001


class TestBootstrap:
    def test_deterministic(self) -> None:
        values = [0.1, 0.2, 0.3, 0.4, 0.5]
        assert bootstrap_ci(values) == bootstrap_ci(values)

    def test_ci_brackets_mean(self) -> None:
        point, low, high = bootstrap_ci([1.0, 1.0, 1.0, 1.0])
        assert point == 1.0 and low == pytest.approx(1.0) and high == pytest.approx(1.0)

    def test_empty(self) -> None:
        assert bootstrap_ci([]) == (0.0, 0.0, 0.0)

    def test_mean_helper(self) -> None:
        assert mean([1, 2, 3]) == 2
        assert mean([]) == 0.0


class TestTOST:
    def test_equivalent_when_within_margin(self) -> None:
        result = tost_paired([0.01, -0.01, 0.0, 0.02, -0.02], margin=0.1)
        assert result["equivalent"] is True

    def test_not_equivalent_when_shifted(self) -> None:
        result = tost_paired([0.5, 0.6, 0.55, 0.52, 0.58], margin=0.1)
        assert result["equivalent"] is False
        assert result["mean_diff"] > 0.5

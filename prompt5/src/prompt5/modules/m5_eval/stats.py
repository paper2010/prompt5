"""统计检验（纯 Python 实现，不依赖 scipy）：Wilcoxon 符号秩、McNemar 精确检验、配对 bootstrap CI、TOST。

口径（执行方案 §3.2/§9.2）：
- 样本单位 = 任务；repeats 先在任务内聚合，禁止把重复当独立样本（防伪重复）。
- 「未检出差异」≠「等效」；等效必须用 TOST（此处以 90% CI 落在 (±margin) 内判定）。
- 所有随机过程使用固定种子，保证结果可复现。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "StatResult",
    "wilcoxon_signed_rank",
    "mcnemar_exact",
    "bootstrap_ci",
    "tost_paired",
    "mean",
]


@dataclass
class StatResult:
    statistic: float
    p_value: float
    n: int
    method: str
    detail: dict | None = None


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------- Wilcoxon
def _average_ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average = (position + 1 + end + 1) / 2
        for cursor in range(position, end + 1):
            ranks[order[cursor]] = average
        position = end + 1
    return ranks


def wilcoxon_signed_rank(
    first: Sequence[float], second: Sequence[float], *, exact_limit: int = 20
) -> StatResult:
    """配对 Wilcoxon 符号秩（零差异剔除；n≤20 精确枚举，否则正态近似 + 并列校正）。"""
    if len(first) != len(second):
        raise ValueError("paired samples must have equal length")
    diffs = [a - b for a, b in zip(first, second) if a != b]
    n = len(diffs)
    if n == 0:
        return StatResult(0.0, 1.0, 0, "degenerate", {"reason": "all differences are zero"})

    ranks = _average_ranks([abs(d) for d in diffs])
    w_plus = sum(rank for rank, diff in zip(ranks, diffs) if diff > 0)
    scaled = [int(round(rank * 2)) for rank in ranks]

    if n <= exact_limit:
        distribution: dict[int, int] = {0: 1}
        for weight in scaled:
            updated = dict(distribution)
            for total, count in distribution.items():
                updated[total + weight] = updated.get(total + weight, 0) + count
            distribution = updated
        observed = int(round(w_plus * 2))
        grand_total = sum(scaled)
        lower = min(observed, grand_total - observed)
        cumulative = sum(count for total, count in distribution.items() if total <= lower)
        p_value = min(1.0, 2 * cumulative / (2**n))
        return StatResult(w_plus, p_value, n, "exact")

    tie_counts: dict[float, int] = {}
    for value in [abs(d) for d in diffs]:
        tie_counts[value] = tie_counts.get(value, 0) + 1
    tie_correction = sum(count**3 - count for count in tie_counts.values()) / 48.0
    mu = n * (n + 1) / 4
    sigma_sq = n * (n + 1) * (2 * n + 1) / 24 - tie_correction
    if sigma_sq <= 0:
        return StatResult(w_plus, 1.0, n, "normal", {"reason": "degenerate variance"})
    z = (abs(w_plus - mu) - 0.5) / math.sqrt(sigma_sq)
    p_value = math.erfc(abs(z) / math.sqrt(2))
    return StatResult(w_plus, min(1.0, p_value), n, "normal", {"z": z})


# ---------------------------------------------------------------- McNemar
def mcnemar_exact(b: int, c: int) -> StatResult:
    """精确 McNemar（双侧）：b/c 为不一致对计数。"""
    total = b + c
    if total == 0:
        return StatResult(0, 1.0, 0, "degenerate")
    k = min(b, c)
    tail = sum(math.comb(total, index) for index in range(k + 1)) / (2**total)
    return StatResult(float(min(b, c)), min(1.0, 2 * tail), total, "exact", {"b": b, "c": c})


# ---------------------------------------------------------------- bootstrap
def bootstrap_ci(
    values: Sequence[float],
    *,
    level: float = 0.95,
    n_boot: int = 2000,
    seed: int = 1729,
) -> tuple[float, float, float]:
    """配对差值的均值 bootstrap 百分位 CI，返回 (点估计, 下限, 上限)。"""
    if not values:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    n = len(values)
    estimates = []
    for _ in range(n_boot):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        estimates.append(total / n)
    estimates.sort()
    alpha = (1 - level) / 2
    lo_index = max(0, int(alpha * n_boot) - 1)
    hi_index = min(n_boot - 1, int((1 - alpha) * n_boot))
    return mean(values), estimates[lo_index], estimates[hi_index]


def tost_paired(
    values: Sequence[float], *, margin: float, level: float = 0.90, seed: int = 1729
) -> dict:
    """TOST 等效判定（CI 法）：90% CI 完整落在 (±margin) 内 → 判等效。"""
    point, lo, hi = bootstrap_ci(values, level=level, seed=seed)
    return {
        "margin": margin,
        "mean_diff": point,
        "ci_level": level,
        "ci_low": lo,
        "ci_high": hi,
        "equivalent": lo > -margin and hi < margin,
    }

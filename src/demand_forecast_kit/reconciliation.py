"""Non-negative MinT reconciliation for cross-sectional hierarchy forecast paths.

The reconciler accepts aligned base forecast samples and out-of-sample residual
vectors. It estimates a shrinkage covariance matrix, projects each sample onto
the coherent hierarchy subspace, clips bottom-level demand at zero, and rebuilds
all aggregates from those bottom-level values. Quantiles are calculated only
after reconciliation, preserving coherence and quantile monotonicity.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from math import isfinite
from typing import TYPE_CHECKING

from demand_forecast_kit.contracts import QuantileForecast

if TYPE_CHECKING:
    import polars as pl


@dataclass(frozen=True, slots=True)
class MinTReconciler:
    """MinT reconciler for an ordered summing matrix.

    summing_matrix has one row per node_id and one column per bottom_id.
    Every bottom-level row must be the corresponding identity row. Residuals
    passed to fit must contain aligned, genuinely out-of-sample errors for
    every node in the same order.
    """
    node_ids: tuple[str, ...]
    bottom_ids: tuple[str, ...]
    summing_matrix: tuple[tuple[float, ...], ...]
    shrinkage: float = 0.2
    ridge: float = 1e-8
    _weight_covariance: tuple[tuple[float, ...], ...] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        nodes = tuple(self.node_ids)
        bottoms = tuple(self.bottom_ids)
        matrix = tuple(tuple(float(value) for value in row) for row in self.summing_matrix)
        if not nodes or not bottoms:
            raise ValueError("node_ids and bottom_ids must be non-empty")
        if any(not value.strip() for value in (*nodes, *bottoms)):
            raise ValueError("hierarchy identifiers must not be blank")
        if len(set(nodes)) != len(nodes) or len(set(bottoms)) != len(bottoms):
            raise ValueError("hierarchy identifiers must be unique")
        if not set(bottoms).issubset(nodes):
            raise ValueError("every bottom_id must also appear in node_ids")
        if len(matrix) != len(nodes) or any(len(row) != len(bottoms) for row in matrix):
            raise ValueError("summing_matrix dimensions must match node_ids and bottom_ids")
        if any(not isfinite(value) or value not in (0.0, 1.0) for row in matrix for value in row):
            raise ValueError("summing_matrix must contain only finite 0/1 membership values")
        if any(not any(row) for row in matrix):
            raise ValueError("every hierarchy node must include at least one bottom series")
        if not isfinite(self.shrinkage) or not 0.0 < self.shrinkage <= 1.0:
            raise ValueError("shrinkage must be finite and in (0, 1]")
        if not isfinite(self.ridge) or self.ridge <= 0.0:
            raise ValueError("ridge must be finite and positive")
        for bottom_index, bottom_id in enumerate(bottoms):
            row = matrix[nodes.index(bottom_id)]
            expected = tuple(1.0 if index == bottom_index else 0.0 for index in range(len(bottoms)))
            if row != expected:
                raise ValueError("bottom-level rows must form the identity matrix")
        object.__setattr__(self, "node_ids", nodes)
        object.__setattr__(self, "bottom_ids", bottoms)
        object.__setattr__(self, "summing_matrix", matrix)

    @classmethod
    def from_hierarchical_history(
        cls, frame: pl.DataFrame, *, shrinkage: float = 0.2, ridge: float = 1e-8
    ) -> MinTReconciler:
        """Build a summing matrix from build_hierarchical_history output.

        The current SKU/location contract is a two-axis DAG: each leaf has a
        SKU parent and a location parent. Aggregate axes are not summed together.
        """
        required = {"series_id", "parent_series_ids", "hierarchy_level"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"missing hierarchy metadata columns: {', '.join(missing)}")
        metadata: dict[str, tuple[str, ...]] = {}
        levels: dict[str, str] = {}
        selected = frame.select("series_id", "parent_series_ids", "hierarchy_level")
        for row in selected.iter_rows(named=True):
            node_id = str(row["series_id"])
            parents = tuple(str(value) for value in (row["parent_series_ids"] or ()))
            level = str(row["hierarchy_level"])
            existing = metadata.get(node_id)
            if existing is not None and (existing != parents or levels[node_id] != level):
                raise ValueError(f"inconsistent hierarchy metadata for node {node_id!r}")
            metadata[node_id] = parents
            levels[node_id] = level
        bottom_ids = tuple(
            sorted(node for node, level in levels.items() if level == "sku-location")
        )
        node_ids = tuple(sorted(metadata))
        if not bottom_ids:
            raise ValueError("hierarchy history contains no sku-location bottom series")
        for node_id, parents in metadata.items():
            if any(parent not in metadata for parent in parents):
                raise ValueError(f"hierarchy node {node_id!r} references an unknown parent")
            if levels[node_id] == "sku-location" and not parents:
                raise ValueError(f"bottom node {node_id!r} must reference its aggregate parents")
            if levels[node_id] != "sku-location" and parents:
                raise ValueError("only sku-location leaves may have direct parents in this DAG")
        matrix = tuple(
            tuple(
                1.0 if node_id == bottom_id or node_id in metadata[bottom_id] else 0.0
                for bottom_id in bottom_ids
            )
            for node_id in node_ids
        )
        return cls(node_ids, bottom_ids, matrix, shrinkage=shrinkage, ridge=ridge)

    def fit(self, residuals: Sequence[Sequence[float]]) -> MinTReconciler:
        """Estimate a shrinkage covariance from aligned out-of-sample residuals."""
        rows = tuple(tuple(float(value) for value in row) for row in residuals)
        if len(rows) < 2:
            raise ValueError("at least two aligned residual observations are required")
        width = len(self.node_ids)
        if any(len(row) != width for row in rows):
            raise ValueError("each residual row must contain one value per hierarchy node")
        if any(not isfinite(value) for row in rows for value in row):
            raise ValueError("residuals must be finite")
        means = tuple(sum(row[column] for row in rows) / len(rows) for column in range(width))
        covariance = [[0.0] * width for _ in range(width)]
        for left in range(width):
            for right in range(width):
                covariance[left][right] = sum(
                    (row[left] - means[left]) * (row[right] - means[right]) for row in rows
                ) / (len(rows) - 1)
        diagonal = tuple(max(0.0, covariance[index][index]) for index in range(width))
        scale = max(sum(diagonal) / width, 1.0)
        regularized = tuple(
            tuple(
                (1.0 - self.shrinkage) * covariance[left][right]
                + (self.shrinkage * diagonal[left] if left == right else 0.0)
                + (self.ridge * scale if left == right else 0.0)
                for right in range(width)
            )
            for left in range(width)
        )
        object.__setattr__(self, "_weight_covariance", regularized)
        return self

    def reconcile_samples(
        self, base_samples: Sequence[Sequence[float]]
    ) -> tuple[tuple[float, ...], ...]:
        """Reconcile aligned samples; each row contains one forecast per node."""
        if self._weight_covariance is None:
            raise RuntimeError("fit must be called with historical residuals before reconciliation")
        samples = tuple(tuple(float(value) for value in row) for row in base_samples)
        if not samples:
            raise ValueError("base_samples must not be empty")
        if any(len(row) != len(self.node_ids) for row in samples):
            raise ValueError("each base sample must contain one value per hierarchy node")
        if any(not isfinite(value) for row in samples for value in row):
            raise ValueError("base forecast samples must be finite")
        covariance = self._weight_covariance
        matrix = self.summing_matrix
        node_count = len(self.node_ids)
        bottom_count = len(self.bottom_ids)
        weighted_summing = tuple(
            _solve(covariance, tuple(matrix[row][column] for row in range(node_count)))
            for column in range(bottom_count)
        )
        normal = tuple(
            tuple(
                sum(matrix[row][left] * weighted_summing[right][row] for row in range(node_count))
                for right in range(bottom_count)
            )
            for left in range(bottom_count)
        )
        reconciled: list[tuple[float, ...]] = []
        for sample in samples:
            weighted_sample = _solve(covariance, sample)
            rhs = tuple(
                sum(matrix[row][column] * weighted_sample[row] for row in range(node_count))
                for column in range(bottom_count)
            )
            bottom = tuple(max(0.0, value) for value in _solve(normal, rhs))
            reconciled.append(
                tuple(
                    sum(matrix[row][column] * bottom[column] for column in range(bottom_count))
                    for row in range(node_count)
                )
            )
        return tuple(reconciled)

    def reconcile_quantile_paths(
        self,
        base_samples: Sequence[Sequence[Sequence[float]]],
        *,
        quantile_levels: Sequence[float] = (0.1, 0.5, 0.9),
    ) -> dict[str, QuantileForecast]:
        """Reconcile sample paths first, then derive coherent marginal quantiles.

        Input shape is samples × horizon × nodes. All nodes in a sample must
        share the same sample index so cross-sectional dependence is retained.
        """
        levels = tuple(sorted(float(value) for value in quantile_levels))
        if not levels or len(set(levels)) != len(levels):
            raise ValueError("quantile_levels must be non-empty and unique")
        if any(not isfinite(level) or not 0.0 < level < 1.0 for level in levels):
            raise ValueError("quantile levels must be finite and strictly between 0 and 1")
        paths = tuple(
            tuple(tuple(float(value) for value in step) for step in path) for path in base_samples
        )
        if not paths or not paths[0]:
            raise ValueError("base_samples must contain at least one non-empty path")
        horizon = len(paths[0])
        if any(len(path) != horizon for path in paths):
            raise ValueError("all sample paths must have the same horizon")
        reconciled_steps: list[list[tuple[float, ...]]] = []
        for step in range(horizon):
            reconciled_steps.append(
                list(self.reconcile_samples(tuple(path[step] for path in paths)))
            )
        by_node: dict[str, dict[float, tuple[float, ...]]] = {}
        for node_index, node_id in enumerate(self.node_ids):
            quantiles: dict[float, tuple[float, ...]] = {}
            for level in levels:
                values: list[float] = []
                for step in range(horizon):
                    ordered = sorted(sample[node_index] for sample in reconciled_steps[step])
                    position = (len(ordered) - 1) * level
                    lower = int(position)
                    upper = min(lower + 1, len(ordered) - 1)
                    fraction = position - lower
                    values.append(ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction)
                quantiles[level] = tuple(values)
            by_node[node_id] = quantiles
        return {
            node_id: QuantileForecast(series_id=node_id, quantiles=quantiles)
            for node_id, quantiles in by_node.items()
        }


def _solve(matrix: Sequence[Sequence[float]], rhs: Sequence[float]) -> tuple[float, ...]:
    """Solve a small dense linear system with partial pivoting."""
    size = len(rhs)
    if size == 0 or len(matrix) != size or any(len(row) != size for row in matrix):
        raise ValueError("linear system must be non-empty and square")
    augmented = [
        [float(value) for value in row] + [float(rhs[index])] for index, row in enumerate(matrix)
    ]
    scale = max((abs(value) for row in matrix for value in row), default=1.0)
    tolerance = max(scale, 1.0) * 1e-14
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= tolerance:
            raise ValueError("hierarchy matrix is rank deficient or covariance is singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor:
                augmented[row] = [
                    current - factor * pivot_value
                    for current, pivot_value in zip(augmented[row], augmented[column], strict=True)
                ]
    return tuple(augmented[index][-1] for index in range(size))


@dataclass(frozen=True, slots=True)
class PrequentialReconciliation:
    """Reconciliation output fitted strictly on residual origins before this one."""

    origin_index: int
    residual_count: int
    samples: tuple[tuple[float, ...], ...]


def prequential_reconcile(
    *,
    node_ids: tuple[str, ...],
    bottom_ids: tuple[str, ...],
    summing_matrix: tuple[tuple[float, ...], ...],
    residuals_by_origin: Sequence[Sequence[float]],
    base_samples_by_origin: Sequence[Sequence[Sequence[float]]],
    shrinkage: float = 0.2,
    ridge: float = 1e-8,
) -> tuple[PrequentialReconciliation, ...]:
    """Evaluate each origin using only strictly earlier completed residuals.

    The first two origins are warm-up only. At origin i, covariance is fitted
    from residuals_by_origin[:i]; the residual observed at i is never admitted.
    Callers must supply both sequences in chronological forecast-origin order.
    """
    residuals = tuple(tuple(float(value) for value in row) for row in residuals_by_origin)
    samples = tuple(
        tuple(tuple(float(value) for value in sample) for sample in origin)
        for origin in base_samples_by_origin
    )
    if len(residuals) != len(samples):
        raise ValueError("residual and base-sample origins must have equal lengths")
    if len(residuals) < 3:
        raise ValueError("at least three origins are required for two warm-up residuals")
    results: list[PrequentialReconciliation] = []
    for origin_index in range(2, len(residuals)):
        reconciler = MinTReconciler(
            node_ids=node_ids,
            bottom_ids=bottom_ids,
            summing_matrix=summing_matrix,
            shrinkage=shrinkage,
            ridge=ridge,
        ).fit(residuals[:origin_index])
        results.append(
            PrequentialReconciliation(
                origin_index=origin_index,
                residual_count=origin_index,
                samples=reconciler.reconcile_samples(samples[origin_index]),
            )
        )
    return tuple(results)

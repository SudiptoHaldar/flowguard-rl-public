/// Comparison-matrix arithmetic (req_003 v3.05 D10) — pure, no widgets.
///
/// The metric, the ramp buckets and — most importantly — the **cell states** live here, so the
/// rules that keep the matrix honest are testable without a widget tree.
///
/// The rule behind most of this file: **a missing or incomparable measurement must never render
/// as 0%**. In this metric 0% means *at the optimum*, so blank-as-zero would be the most
/// damaging misreading available.
library;

import '../api/models.dart';

/// What a cell is, before anything is drawn.
enum CellState {
  /// Regret 0 — at the scenario optimum. A real, frequent state, not a ramp endpoint.
  optimal,

  /// Regret measured against an enumerated (proven) optimum.
  measured,

  /// Regret measured against a best-observed optimum — a weaker claim, marked as such.
  fallback,

  /// The population exists but has no optimum to compare against.
  notComparable,

  /// No result for this scenario × strategy at all.
  notRun,
}

/// Upper bounds of the ramp buckets, in percent. Five buckets, matching the validated ramp.
const List<double> rampBounds = [10, 25, 50, 100, double.infinity];

/// Above this the cell paints at the ramp's top — but always still prints its own value.
const double clampCeiling = 100;

/// Regret as a percentage of the scenario optimum — the D1 metric.
///
/// Null when there is nothing to compare against. Callers must render that as "not comparable",
/// never as zero.
double? regretPercent(ComparisonCell cell) {
  final optimum = cell.optimum;
  final regret = cell.regretMedian;
  if (optimum == null || regret == null || optimum == 0) return null;
  return regret / optimum * 100;
}

/// Improvement over the run's own first trial, as a percentage — the alternate metric.
///
/// Kept available (v2.06 D1 framing) but not the default: measured on the shipped corpus it
/// saturates near 100% for every strategy, so it barely separates them.
double improvementPercent(ComparisonCell cell) => cell.improvementMedian * 100;

/// Classifies a cell, including its absence.
CellState classify(ComparisonCell? cell) {
  if (cell == null) return CellState.notRun;
  final percent = regretPercent(cell);
  if (percent == null) return CellState.notComparable;
  if (percent <= 0) return CellState.optimal;
  return cell.optimumMethod == 'enumerated'
      ? CellState.measured
      : CellState.fallback;
}

/// Which ramp step a regret percentage falls in.
int rampIndex(double percent) {
  for (var i = 0; i < rampBounds.length; i++) {
    if (percent <= rampBounds[i]) return i;
  }
  return rampBounds.length - 1;
}

/// Whether the value sits above the ramp ceiling and is therefore painted at the top.
bool isClamped(double percent) => percent > clampCeiling;

/// One Circuit(Load) problem — a matrix row.
typedef ScenarioKey = ({String circuit, double load});

/// One strategy population — a matrix column.
typedef StrategyKey = ({String strategy, String? version});

/// Rows in a fixed order: circuit, then load ascending.
///
/// The ordering is load-bearing, not cosmetic: adjacent rows are the same circuit at different
/// loads, so scaling behaviour reads down the column by eye — which is why v3.05 defers a
/// dedicated small-multiples view (D9).
List<ScenarioKey> scenarioRows(List<ComparisonCell> cells) {
  final keys = <ScenarioKey>{
    for (final cell in cells) (circuit: cell.circuitName, load: cell.totalLoad),
  }.toList();
  keys.sort((a, b) {
    final byCircuit = a.circuit.compareTo(b.circuit);
    return byCircuit != 0 ? byCircuit : a.load.compareTo(b.load);
  });
  return keys;
}

/// Columns, excluding the degenerate baseline — it gets its own section (D3).
///
/// Keyed by strategy **and version**: `random_simplex` v1 and v2 are different algorithms and
/// are never pooled into one column.
List<StrategyKey> strategyColumns(List<ComparisonCell> cells) {
  final keys = <StrategyKey>{
    for (final cell in cells)
      if (!cell.excludedFromAggregates)
        (strategy: cell.strategy, version: cell.strategyVersion),
  }.toList();
  keys.sort((a, b) {
    final byName = a.strategy.compareTo(b.strategy);
    return byName != 0
        ? byName
        : (a.version ?? '').compareTo(b.version ?? '');
  });
  return keys;
}

/// The cells excluded from aggregates — shown separately, as raw cost (D3).
List<ComparisonCell> degenerateCells(List<ComparisonCell> cells) =>
    [for (final cell in cells) if (cell.excludedFromAggregates) cell]..sort((a, b) {
        final byCircuit = a.circuitName.compareTo(b.circuitName);
        return byCircuit != 0 ? byCircuit : a.totalLoad.compareTo(b.totalLoad);
      });

/// Looks up one cell of the grid; null means the combination was never run.
ComparisonCell? cellAt(
  List<ComparisonCell> cells,
  ScenarioKey row,
  StrategyKey column,
) {
  for (final cell in cells) {
    if (cell.circuitName == row.circuit &&
        cell.totalLoad == row.load &&
        cell.strategy == column.strategy &&
        cell.strategyVersion == column.version) {
      return cell;
    }
  }
  return null;
}

/// The grouping-key partitions present in a payload.
///
/// The view shows one population at a time and says which — an unlabelled matrix spanning two
/// observation modes invites the reader to pool them by eye.
({Set<String> observationModes, Set<String> allocationModes, Set<bool> coldStarts})
    facetsIn(List<ComparisonCell> cells) => (
          observationModes: {for (final c in cells) c.observationMode},
          allocationModes: {for (final c in cells) c.allocationMode},
          coldStarts: {for (final c in cells) c.coldStart},
        );

/// Names the grouping keys a set of cells spans, or null when it is a single population.
String? mixedFacetWarning(List<ComparisonCell> cells) {
  final facets = facetsIn(cells);
  final spans = <String>[
    if (facets.observationModes.length > 1)
      'observation modes (${facets.observationModes.join(', ')})',
    if (facets.allocationModes.length > 1)
      'allocation modes (${facets.allocationModes.join(', ')})',
    if (facets.coldStarts.length > 1) 'cold- and warm-started runs',
  ];
  return spans.isEmpty
      ? null
      : 'This view spans ${spans.join(' and ')} — filter to one population before comparing.';
}

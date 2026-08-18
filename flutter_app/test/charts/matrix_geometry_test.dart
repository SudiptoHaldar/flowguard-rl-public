/// Matrix arithmetic, tested without a widget tree.
///
/// The rule most of these guard: a missing or incomparable measurement must never become 0%,
/// because 0% in this metric means *at the optimum*.
library;

import 'dart:convert';

import 'package:flowguard_dashboard/api/models.dart';
import 'package:flowguard_dashboard/charts/matrix_geometry.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers.dart';

List<ComparisonCell> loadCells(String name) =>
    ComparisonResponse.fromJson(jsonDecode(fixture(name)) as Map<String, dynamic>)
        .cells;

ComparisonCell find(
  List<ComparisonCell> cells,
  String circuit,
  double load,
  String strategy,
) =>
    cells.firstWhere((c) =>
        c.circuitName == circuit &&
        c.totalLoad == load &&
        c.strategy == strategy);

ComparisonCell synthetic({
  double? optimum = 100,
  double? regret = 25,
  String method = 'enumerated',
  String strategy = 'hill_climb',
  bool excluded = false,
}) =>
    ComparisonCell(
      circuitName: 'C9',
      totalLoad: 100,
      strategy: strategy,
      strategyVersion: 'v1',
      allocationMode: 'integer',
      observationMode: 'opaque',
      coldStart: true,
      runs: 1,
      bestCostMedian: 125,
      bestCostMin: 125,
      bestCostMax: 125,
      improvementMedian: 0.5,
      convergenceStepMedian: 3,
      optimum: optimum,
      optimumMethod: method,
      regretMedian: regret,
      safetyFractionMedian: 0,
      excludedFromAggregates: excluded,
    );

void main() {
  group('regretPercent — against the real corpus', () {
    final cells = loadCells('comparison.json');

    test('hill_climb is 0% in every scenario', () {
      final rows = scenarioRows(cells);
      expect(rows.length, 8);
      for (final row in rows) {
        final cell = find(cells, row.circuit, row.load, 'hill_climb');
        expect(regretPercent(cell), 0.0, reason: '${row.circuit}@${row.load}');
      }
    });

    test('release_sweep on C3@60 is 200%', () {
      expect(regretPercent(find(cells, 'C3', 60, 'release_sweep')),
          closeTo(200.0, 0.01));
    });

    test('random_simplex on C4@10000 is 21.72%', () {
      expect(regretPercent(find(cells, 'C4', 10000, 'random_simplex')),
          closeTo(21.72, 0.01));
    });
  });

  group('classify — absence is a state, never zero', () {
    test('a missing cell is notRun, not optimal', () {
      expect(classify(null), CellState.notRun);
    });

    test('a null optimum is notComparable, not 0%', () {
      final cell = synthetic(optimum: null, regret: null);
      expect(regretPercent(cell), isNull);
      expect(classify(cell), CellState.notComparable);
    });

    test('a zero optimum cannot divide, so it is notComparable', () {
      expect(classify(synthetic(optimum: 0)), CellState.notComparable);
    });

    test('zero regret is optimal', () {
      expect(classify(synthetic(regret: 0)), CellState.optimal);
    });

    test('a best_observed optimum is a weaker claim and is marked', () {
      expect(classify(synthetic(method: 'best_observed')), CellState.fallback);
      expect(classify(synthetic(method: 'enumerated')), CellState.measured);
    });
  });

  group('ramp bucketing', () {
    test('boundaries fall in the expected step', () {
      expect(rampIndex(0.01), 0);
      expect(rampIndex(10), 0);
      expect(rampIndex(10.01), 1);
      expect(rampIndex(25), 1);
      expect(rampIndex(50), 2);
      expect(rampIndex(100), 3);
      expect(rampIndex(200), 4);
    });

    test('the clamp starts above the ceiling, not at it', () {
      expect(isClamped(100), isFalse);
      expect(isClamped(100.01), isTrue);
      expect(isClamped(200), isTrue);
    });

    test('there are exactly as many buckets as validated ramp steps', () {
      expect(rampBounds.length, 5);
    });
  });

  group('grid layout', () {
    final cells = loadCells('comparison.json');

    test('rows are circuit then ascending load', () {
      final rows = scenarioRows(cells);
      final c2 = rows.where((r) => r.circuit == 'C2').map((r) => r.load).toList();
      expect(c2, [60, 1440, 20000]);
    });

    test('columns exclude the degenerate baseline', () {
      final columns = strategyColumns(cells).map((c) => c.strategy).toList();
      expect(columns, isNot(contains('equal_split')));
      expect(columns.length, 3);
    });

    test('degenerateCells returns exactly the excluded ones', () {
      final degenerate = degenerateCells(cells);
      expect(degenerate, isNotEmpty);
      expect(degenerate.every((c) => c.strategy == 'equal_split'), isTrue);
    });

    test('columns keep strategy versions apart', () {
      final mixed = [
        synthetic(strategy: 'random_simplex'),
        ComparisonCell(
          circuitName: 'C9',
          totalLoad: 100,
          strategy: 'random_simplex',
          strategyVersion: 'v2', // a different algorithm, never pooled
          allocationMode: 'integer',
          observationMode: 'opaque',
          coldStart: true,
          runs: 1,
          bestCostMedian: 1,
          bestCostMin: 1,
          bestCostMax: 1,
          improvementMedian: 0,
          convergenceStepMedian: 0,
          optimum: 1,
          optimumMethod: 'enumerated',
          regretMedian: 0,
          safetyFractionMedian: 0,
          excludedFromAggregates: false,
        ),
      ];
      expect(strategyColumns(mixed).length, 2);
    });

    test('cellAt returns null for a combination never run', () {
      final cells = loadCells('comparison_fallback.json');
      final missing = cellAt(
        cells,
        (circuit: 'C2', load: 1440),
        (strategy: 'release_sweep', version: 'v1'),
      );
      expect(missing, isNull);
      expect(classify(missing), CellState.notRun);
    });
  });

  group('facets', () {
    test('a single population raises no warning', () {
      expect(mixedFacetWarning(loadCells('comparison.json')), isNull);
    });

    test('spanning observation modes names them', () {
      final mixed = [
        synthetic(),
        ComparisonCell(
          circuitName: 'C9',
          totalLoad: 100,
          strategy: 'hill_climb',
          strategyVersion: 'v1',
          allocationMode: 'integer',
          observationMode: 'enhanced',
          coldStart: true,
          runs: 1,
          bestCostMedian: 1,
          bestCostMin: 1,
          bestCostMax: 1,
          improvementMedian: 0,
          convergenceStepMedian: 0,
          optimum: 1,
          optimumMethod: 'enumerated',
          regretMedian: 0,
          safetyFractionMedian: 0,
          excludedFromAggregates: false,
        ),
      ];
      final warning = mixedFacetWarning(mixed);
      expect(warning, contains('observation modes'));
      expect(warning, contains('enhanced'));
    });
  });

  group('improvement — the alternate metric', () {
    final cells = loadCells('comparison.json');

    test('ranks the strategies differently from regret — and misleadingly', () {
      // C2@60: release_sweep shows the bigger improvement, yet it ends twice as far from the
      // optimum as random_simplex. Improvement is relative to each run's own first trial, so a
      // run that started worse can look better while finishing worse. This is why regret is the
      // matrix's default metric.
      final sweep = find(cells, 'C2', 60, 'release_sweep');
      final random = find(cells, 'C2', 60, 'random_simplex');

      expect(improvementPercent(sweep), greaterThan(improvementPercent(random)));
      expect(regretPercent(sweep)!, greaterThan(regretPercent(random)!));
    });

    test('is compressed into a high band, where regret spans 0-200%', () {
      final values = [
        for (final row in scenarioRows(cells))
          for (final strategy in ['hill_climb', 'random_simplex', 'release_sweep'])
            improvementPercent(find(cells, row.circuit, row.load, strategy)),
      ];
      // Measured on this corpus: 48.63% .. 100.00%. Every strategy improves enormously from a
      // dreadful first trial, so the metric crowds them together where regret spreads them out.
      expect(values.reduce((a, b) => a < b ? a : b), closeTo(48.63, 0.01));
      expect(values.reduce((a, b) => a > b ? a : b), closeTo(100.0, 0.01));
    });

    test('agrees on the winner but not on the ranking beneath it', () {
      // Worth being precise: on this corpus both metrics pick hill_climb in all 8 scenarios.
      // The disagreement is about the *losers*, which is exactly where a comparison view is
      // read — "who should I use instead" is a question about the ranking, not the winner.
      for (final row in scenarioRows(cells)) {
        final group = [
          for (final s in ['hill_climb', 'random_simplex', 'release_sweep'])
            find(cells, row.circuit, row.load, s),
        ];
        final byImprovement =
            group.reduce((a, b) => improvementPercent(a) >= improvementPercent(b) ? a : b);
        final byRegret =
            group.reduce((a, b) => regretPercent(a)! <= regretPercent(b)! ? a : b);
        expect(byImprovement.strategy, byRegret.strategy,
            reason: '${row.circuit}@${row.load} winner');
      }
    });
  });
}

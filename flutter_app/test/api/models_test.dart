/// Model round-trips against **real captured API responses**.
///
/// The fixtures are bodies from a live server, so if the API's shape changes these tests fail
/// rather than a screen quietly rendering nothing.
library;

import 'dart:convert';

import 'package:flowguard_dashboard/api/models.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers.dart';

void main() {
  group('expected — every fixture parses', () {
    test('scenarios', () {
      final list = (jsonDecode(fixture('scenarios.json')) as List)
          .map((e) => ScenarioRef.fromJson(e as Map<String, dynamic>))
          .toList();
      expect(list, isNotEmpty);
      expect(list.first.circuitName, isNotEmpty);
      expect(list.first.runCount, greaterThan(0));
    });

    test('runs page', () {
      final page = RunPage.fromJson(
          jsonDecode(fixture('runs.json')) as Map<String, dynamic>);
      expect(page.items, isNotEmpty);
      expect(page.total, greaterThanOrEqualTo(page.items.length));
      expect(page.items.first.externalNodeNames, isNotEmpty);
    });

    test('run header', () {
      final run = RunSummary.fromJson(
          jsonDecode(fixture('run.json')) as Map<String, dynamic>);
      expect(run.runId, 1091);
      expect(run.circuitName, 'C4');
      expect(run.strategy, 'hill_climb');
      expect(run.bestCost, closeTo(299.1856, 1e-6));
    });

    test('series carries the envelope down to the known optimum', () {
      final series = RunSeries.fromJson(
          jsonDecode(fixture('series.json')) as Map<String, dynamic>);
      expect(series.points, isNotEmpty);
      expect(series.totalPoints, greaterThanOrEqualTo(series.points.length));
      // The C4 DAG optimum established by the v2.06 harness.
      expect(series.points.last.bestSoFar, closeTo(299.1856, 1e-6));
      // The envelope is non-increasing by construction.
      for (var i = 1; i < series.points.length; i++) {
        expect(series.points[i].bestSoFar,
            lessThanOrEqualTo(series.points[i - 1].bestSoFar));
      }
    });

    test('allocations', () {
      final series = AllocationSeries.fromJson(
          jsonDecode(fixture('allocations.json')) as Map<String, dynamic>);
      expect(series.nodeNames, isNotEmpty);
      // Every point's load vector is positional against nodeNames.
      for (final point in series.points) {
        expect(point.loads.length, series.nodeNames.length);
      }
    });

    test('benchmarks', () {
      final list = (jsonDecode(fixture('benchmarks.json')) as List)
          .map((e) => BenchmarkHeader.fromJson(e as Map<String, dynamic>))
          .toList();
      expect(list, isNotEmpty);
      expect(list.first.catalogName, isNotEmpty);
    });

    test('comparison', () {
      final grid = ComparisonResponse.fromJson(
          jsonDecode(fixture('comparison.json')) as Map<String, dynamic>);
      expect(grid.available, isTrue);
      expect(grid.benchmark, isNotNull);
      expect(grid.cells, isNotEmpty);
      expect(
        grid.cells.map((c) => c.optimumMethod).toSet(),
        everyElement(isIn(['enumerated', 'best_observed', 'unknown'])),
      );
    });
  });

  group('edge', () {
    test('a completed run with no trials has null costs', () {
      final run = RunSummary.fromJson({
        'run_id': 5,
        'circuit_name': 'C2',
        'total_load': 60.0,
        'strategy': 'hill_climb',
        'strategy_version': null,
        'seed': null,
        'budget': null,
        'observation_mode': 'opaque',
        'allocation_mode': 'integer',
        'cold_start': true,
        'termination_reason': null,
        'external_node_names': ['N1', 'N2'],
        'trials_used': 0,
        'first_cost': null,
        'best_cost': null,
        'improvement': 0.0,
        'created_at': '2026-08-17T12:00:00+00:00',
        'completed_at': null,
      });
      expect(run.firstCost, isNull);
      expect(run.bestCost, isNull);
      expect(run.completedAt, isNull);
      expect(run.trialsUsed, 0);
    });

    test('whole numbers arriving as int still parse as double', () {
      // JSON has no float/int distinction: a cost of exactly 4 arrives as `4`, not `4.0`.
      final point = SeriesPoint.fromJson({
        'step_index': 0,
        'total_cost': 4,
        'best_so_far': 4,
        'is_best': true,
      });
      expect(point.totalCost, 4.0);
      expect(point.bestSoFar, 4.0);
    });

    test('an empty comparison corpus parses as unavailable, not an error', () {
      final grid = ComparisonResponse.fromJson(
          {'available': false, 'benchmark': null, 'cells': <dynamic>[]});
      expect(grid.available, isFalse);
      expect(grid.benchmark, isNull);
      expect(grid.cells, isEmpty);
    });
  });

  group('failure', () {
    test('a missing required key throws rather than silently defaulting', () {
      expect(
        () => SeriesPoint.fromJson({'step_index': 0, 'total_cost': 1.0}),
        throwsA(isA<TypeError>()),
      );
    });
  });
}

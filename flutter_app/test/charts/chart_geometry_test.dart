/// Chart arithmetic, tested without a widget tree — this is where the mistakes would live.
library;

import 'dart:convert';

import 'package:flowguard_dashboard/api/models.dart';
import 'package:flowguard_dashboard/charts/chart_geometry.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers.dart';

RunSeries loadSeries(String name) =>
    RunSeries.fromJson(jsonDecode(fixture(name)) as Map<String, dynamic>);

SeriesPoint point(int step, double cost, double best, {bool isBest = false}) =>
    SeriesPoint(
        stepIndex: step, totalCost: cost, bestSoFar: best, isBest: isBest);

void main() {
  group('the transform', () {
    test('log and linear round-trip', () {
      expect(fromAxis(toAxis(1000, AxisScale.log, 1e-9), AxisScale.log),
          closeTo(1000, 1e-6));
      expect(fromAxis(toAxis(299.1856, AxisScale.linear, 1), AxisScale.linear),
          closeTo(299.1856, 1e-9));
    });

    test('a zero cost stays finite on the log axis', () {
      // Without the clamp this is -Infinity and the whole chart blanks.
      final value = toAxis(0, AxisScale.log, 0.5);
      expect(value.isFinite, isTrue);
      expect(value, closeTo(-0.301, 0.001)); // log10(0.5)
    });

    test('spans fifteen orders of magnitude without losing the small end', () {
      final floor = axisFloor([5.15e17, 299.1856]);
      final high = toAxis(5.15e17, AxisScale.log, floor);
      final low = toAxis(299.1856, AxisScale.log, floor);
      expect(high - low, closeTo(15.24, 0.05));
    });
  });

  group('axisFloor', () {
    test('picks the smallest positive cost, ignoring zeros', () {
      expect(axisFloor([0, 5.0, 100.0, 0]), 5.0);
    });

    test('falls back when nothing is positive', () {
      expect(axisFloor([0, 0]), 1e-9);
      expect(axisFloor(const []), 1e-9);
    });

    test('needsClamping only fires on log with a non-positive cost', () {
      expect(needsClamping([0, 1], AxisScale.log), isTrue);
      expect(needsClamping([1, 2], AxisScale.log), isFalse);
      expect(needsClamping([0, 1], AxisScale.linear), isFalse);
    });
  });

  group('revealUpTo', () {
    final points = [point(0, 9, 9), point(3, 8, 8), point(7, 7, 7)];

    test('returns exactly the prefix at or below the step', () {
      expect(revealUpTo(points, (p) => p.stepIndex, 0).length, 1);
      expect(revealUpTo(points, (p) => p.stepIndex, 3).length, 2);
      expect(revealUpTo(points, (p) => p.stepIndex, 6).length, 2);
      expect(revealUpTo(points, (p) => p.stepIndex, 7).length, 3);
    });

    test('a step beyond the end reveals everything', () {
      expect(revealUpTo(points, (p) => p.stepIndex, 9999).length, 3);
    });
  });

  group('axisBounds', () {
    test('includes the reference values so a line is never off-screen', () {
      // The optimum sits below every observed cost; without `extra` it would be clipped.
      final bounds = axisBounds([500.0, 400.0], AxisScale.linear, 1, extra: [100.0]);
      expect(bounds.min, lessThan(100));
      expect(bounds.max, greaterThan(500));
    });

    test('a single distinct value still yields a non-zero height', () {
      final bounds = axisBounds([42.0], AxisScale.linear, 1);
      expect(bounds.max, greaterThan(bounds.min));
    });

    test('empty input is safe', () {
      final bounds = axisBounds(const [], AxisScale.log, 1);
      expect(bounds.max, greaterThan(bounds.min));
    });
  });

  group('barRole', () {
    test('decodes a bar index back to its run and mark', () {
      // Two bars per run, cloud first: run 0 owns 0/1, run 1 owns 2/3.
      expect(barRole(0), (runIndex: 0, isEnvelope: false));
      expect(barRole(1), (runIndex: 0, isEnvelope: true));
      expect(barRole(2), (runIndex: 1, isEnvelope: false));
      expect(barRole(5), (runIndex: 2, isEnvelope: true));
    });

    test('names the two marks distinctly', () {
      // The tooltip shows both at the same trial; unnamed, they are two bare numbers.
      expect(barLabel(0), 'trial cost');
      expect(barLabel(1), 'best so far');
      expect(barLabel(2), 'trial cost');
      expect(barLabel(0), isNot(barLabel(1)));
    });
  });

  group('neverImproved', () {
    test('true for a single-trial run (equal_split)', () {
      expect(neverImproved([point(0, 1e19, 1e19, isBest: true)]), isTrue);
    });

    test('false for a run that improved', () {
      expect(neverImproved(loadSeries('series.json').points), isFalse);
    });
  });

  group('allocation alignment', () {
    test('the real fixtures line up step for step', () {
      // The invariant v3.01 D6 designed for, checked against captured API data.
      final series = loadSeries('series.json');
      final allocations = AllocationSeries.fromJson(
          jsonDecode(fixture('allocations.json')) as Map<String, dynamic>);
      expect(allocationsAlignWith(series, allocations), isTrue);
    });

    test('a mismatched length is detected', () {
      final series = loadSeries('series.json');
      final short = AllocationSeries(
        runId: 1091,
        nodeNames: const ['N1'],
        points: const [AllocationPoint(stepIndex: 0, loads: [1])],
        totalPoints: 1,
        downsampled: false,
      );
      expect(allocationsAlignWith(series, short), isFalse);
    });

    test('allocationAt returns the latest point at or before the step', () {
      const allocations = AllocationSeries(
        runId: 1,
        nodeNames: ['N1'],
        points: [
          AllocationPoint(stepIndex: 0, loads: [1]),
          AllocationPoint(stepIndex: 5, loads: [2]),
        ],
        totalPoints: 2,
        downsampled: false,
      );
      expect(allocationAt(allocations, 4)!.loads, [1]);
      expect(allocationAt(allocations, 5)!.loads, [2]);
      expect(allocationAt(allocations, 99)!.loads, [2]);
    });
  });

  group('mixedPopulationWarning', () {
    RunSummary run({String mode = 'opaque', String alloc = 'integer'}) => RunSummary(
          runId: 1,
          circuitName: 'C4',
          totalLoad: 10000,
          strategy: 'hill_climb',
          strategyVersion: 'v1',
          seed: 0,
          budget: 160,
          observationMode: mode,
          allocationMode: alloc,
          coldStart: true,
          terminationReason: null,
          externalNodeNames: const ['N1'],
          trialsUsed: 1,
          firstCost: 1,
          bestCost: 1,
          improvement: 0,
          createdAt: DateTime(2026),
          completedAt: null,
        );

    test('silent when the runs are comparable', () {
      expect(mixedPopulationWarning([run(), run()]), isNull);
      expect(mixedPopulationWarning([run()]), isNull);
    });

    test('names observation_mode when the overlay spans modes', () {
      final warning = mixedPopulationWarning([run(), run(mode: 'enhanced')]);
      expect(warning, contains('observation modes'));
      expect(warning, contains('enhanced'));
    });

    test('names allocation_mode too', () {
      final warning = mixedPopulationWarning([run(), run(alloc: 'continuous')]);
      expect(warning, contains('allocation modes'));
    });
  });
}

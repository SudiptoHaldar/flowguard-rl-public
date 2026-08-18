/// Per-node allocation arithmetic, tested without a widget tree.
library;

import 'dart:convert';

import 'package:flowguard_dashboard/api/models.dart';
import 'package:flowguard_dashboard/charts/allocation_geometry.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers.dart';

AllocationSeries load(String name) =>
    AllocationSeries.fromJson(jsonDecode(fixture(name)) as Map<String, dynamic>);

const _n1 = ExternalNode(name: 'N1', loadFactor: 13, loadSafetyCap: 18);

void main() {
  group('markState — three distinct outcomes', () {
    test('matching capacities may be drawn', () {
      expect(markState(load('allocations.json').capacities), MarkState.shown);
    });

    test('drift withholds the marks', () {
      expect(load('allocations_drift.json').capacities!.matchesRun, isFalse);
      expect(markState(load('allocations_drift.json').capacities),
          MarkState.driftSuppressed);
    });

    test('a missing circuit is its own state, not drift', () {
      expect(markState(null), MarkState.circuitMissing);
    });
  });

  group('nodeFor', () {
    test('returns the node only when the marks may be drawn', () {
      final ok = load('allocations.json');
      expect(nodeFor(ok.capacities, 0)!.name, 'N1');
      expect(nodeFor(ok.capacities, 0)!.loadFactor, 13);

      // Drifted: even though a node sits at index 0, it must not be used.
      expect(nodeFor(load('allocations_drift.json').capacities, 0), isNull);
      expect(nodeFor(null, 0), isNull);
    });

    test('is null past the end rather than throwing', () {
      expect(nodeFor(load('allocations.json').capacities, 99), isNull);
    });
  });

  group('panelBounds', () {
    test('always contains the node\'s marks, even when loads are far below', () {
      // A node idling near zero must still show where its limits are.
      final bounds = panelBounds([0.0, 1.0, 2.0], _n1);
      expect(bounds.min, lessThanOrEqualTo(0));
      expect(bounds.max, greaterThanOrEqualTo(18));
    });

    test('without a node it just fits the loads', () {
      final bounds = panelBounds([5.0, 10.0], null);
      expect(bounds.max, lessThan(18));
    });

    test('a flat-zero node still yields a drawable range', () {
      final bounds = panelBounds([0.0, 0.0], null);
      expect(bounds.max, greaterThan(bounds.min));
    });
  });

  group('nodeSeries', () {
    test('extracts one column and honours the scrubber', () {
      final series = load('allocations.json');
      final all = nodeSeries(series, 0, 1 << 30);
      expect(all.length, series.points.length);

      final firstStep = series.points.first.stepIndex;
      expect(nodeSeries(series, 0, firstStep).length, 1);
    });

    test('reads the right column', () {
      final series = load('allocations.json');
      final n3 = nodeSeries(series, 2, 1 << 30);
      expect(n3.first.y, series.points.first.loads[2]);
    });
  });

  group('crossings', () {
    test('reports factor and safety-cap crossings separately', () {
      expect(crossings([(x: 0, y: 12)], _n1),
          (overFactor: false, overSafetyCap: false));
      expect(crossings([(x: 0, y: 15)], _n1),
          (overFactor: true, overSafetyCap: false));
      expect(crossings([(x: 0, y: 19)], _n1),
          (overFactor: true, overSafetyCap: true));
    });

    test('is silent without capacities — it never guesses a limit', () {
      expect(crossings([(x: 0, y: 999)], null),
          (overFactor: false, overSafetyCap: false));
    });
  });

  group('ties', () {
    test('the real corpus carries a flat optimum the series could not reveal', () {
      final ties = load('allocations_ties.json');
      // 14 distinct allocations at the best cost, from a series of only 12 points —
      // the count cannot come from the client.
      expect(ties.best!.allocations.length, 14);
      expect(ties.best!.allocations.length, greaterThan(ties.points.length));
      expect(ties.best!.isTied, isTrue);
      expect(tieLabel(ties.best!), '14 allocations reached this cost');
    });

    test('a unique best reads in the singular', () {
      final single = load('allocations.json');
      expect(single.best!.allocations.length, 1);
      expect(single.best!.isTied, isFalse);
      expect(tieLabel(single.best!), 'one allocation reached this cost');
      // Run 1091's optimum, sitting on N1's and N3's factors.
      expect(single.best!.allocations.first, [13.0, 6.0, 17.0]);
    });
  });
}

/// The per-node allocation screen, through the real router, client and providers.
library;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers.dart';

Map<String, String> routes({String allocations = 'allocations.json'}) => {
      '/allocations': fixture(allocations),
      '/series': fixture('series.json'),
      '/runs': fixture('runs.json'),
    };

void main() {
  group('expected', () {
    testWidgets('one panel per node, each with its capacity marks', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/allocations');

      expect(find.text('Run 1091 — allocations'), findsOneWidget);
      // Three external nodes -> three panels.
      expect(find.byType(LineChart), findsNWidgets(3));
      expect(find.textContaining('factor 13 · safety cap 18'), findsOneWidget);
      expect(find.textContaining('factor 7 · safety cap 10'), findsOneWidget);
      expect(find.textContaining('factor 17 · safety cap 20'), findsOneWidget);
    });

    testWidgets('each panel carries exactly two horizontal marks', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/allocations');

      final charts = tester.widgetList<LineChart>(find.byType(LineChart)).toList();
      for (final chart in charts) {
        expect(chart.data.extraLinesData.horizontalLines.length, 2);
      }
      // N1's factor and cap, in order.
      final n1 = charts.first.data.extraLinesData.horizontalLines;
      expect(n1[0].y, 13);
      expect(n1[1].y, 18);
    });

    testWidgets('every panel\'s range contains its own marks', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/allocations');

      for (final chart in tester.widgetList<LineChart>(find.byType(LineChart))) {
        for (final line in chart.data.extraLinesData.horizontalLines) {
          expect(line.y, greaterThanOrEqualTo(chart.data.minY));
          expect(line.y, lessThanOrEqualTo(chart.data.maxY));
        }
      }
    });

    testWidgets('the best allocation is shown against its limits', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/allocations');

      expect(find.textContaining('An allocation that reached 299.1856'), findsOneWidget);
      expect(find.text('one allocation reached this cost'), findsOneWidget);
      // (13, 6, 17): N1 and N3 sit exactly on their factors, N2 stays under.
      expect(find.text('13.00'), findsOneWidget);
      expect(find.textContaining('exactly at its factor of 13'), findsOneWidget);
      expect(find.textContaining('under its factor of 7'), findsOneWidget);
    });
  });

  group('ties', () {
    testWidgets('names the count and steps through the alternatives', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes(allocations: 'allocations_ties.json')),
          location: '/runs/1067/allocations');

      expect(find.text('14 allocations reached this cost'), findsOneWidget);
      expect(find.textContaining('A flat optimum'), findsOneWidget);
      expect(find.text('1 / 14'), findsOneWidget);

      await tester.tap(find.byIcon(Icons.chevron_right));
      await tester.pumpAndSettle();
      expect(find.text('2 / 14'), findsOneWidget);
    });
  });

  group('drift', () {
    testWidgets('withholds the marks and says what changed', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes(allocations: 'allocations_drift.json')),
          location: '/runs/1091/allocations');

      expect(find.textContaining('Capacity marks are withheld'), findsOneWidget);
      // The run's list and the circuit's current list are both named.
      expect(find.textContaining('this run used [N1, N2, N3]'), findsOneWidget);
      expect(find.textContaining('circuit now has [N1, N2, N3, N4]'), findsOneWidget);

      // Not a single mark is drawn.
      for (final chart in tester.widgetList<LineChart>(find.byType(LineChart))) {
        expect(chart.data.extraLinesData.horizontalLines, isEmpty);
      }
    });
  });
}

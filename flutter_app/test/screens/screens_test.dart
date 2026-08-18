/// Screen tests: expected, empty and error for each screen, plus not-chartable on run detail.
///
/// Each pumps the real router and the real client with only HTTP faked, so routing, providers,
/// parsing and rendering are exercised together — and none of it needs a backend.
library;

import 'package:flowguard_dashboard/screens/app_scaffold.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers.dart';

void main() {
  group('scenarios screen', () {
    testWidgets('expected: lists scenarios from the API', (tester) async {
      await pumpApp(tester,
          client: fakeClient({'/scenarios': fixture('scenarios.json')}));
      // The subtitle, not the title: "Scenarios" is also an app-bar nav button.
      expect(find.text('Circuit(Load) problems with completed runs'),
          findsOneWidget);
      expect(find.text('C4'), findsWidgets);
      expect(find.byType(DataTable), findsOneWidget);
    });

    testWidgets('empty: names the command that produces a run', (tester) async {
      await pumpApp(tester, client: fakeClient({'/scenarios': '[]'}));
      expect(find.textContaining('No completed runs yet'), findsOneWidget);
      expect(find.textContaining('flowguard.rl optimize'), findsOneWidget);
    });

    testWidgets('error: an unreachable API says so and offers retry',
        (tester) async {
      await pumpApp(tester, client: unreachableClient());
      // Two widgets legitimately report it: the failure view and the app-bar status chip,
      // which runs its own health probe. Assert on the hint, which only the failure view has.
      expect(find.textContaining('API unreachable'), findsWidgets);
      expect(find.textContaining('Is the backend running on port 8100?'),
          findsOneWidget);
      expect(find.text('Retry'), findsOneWidget);
    });
  });

  group('runs screen', () {
    testWidgets('expected: shows the grouping keys, not just ids',
        (tester) async {
      await pumpApp(tester,
          client: fakeClient({'/runs': fixture('runs.json')}),
          location: '/runs');
      expect(find.text('Runs'), findsOneWidget);
      // The labels every later comparison depends on must be visible.
      expect(find.textContaining('integer'), findsWidgets);
      expect(find.textContaining('opaque'), findsWidgets);
      expect(find.textContaining('of'), findsWidgets); // "Showing N of M"
    });

    testWidgets('empty: points at the CLI for non-completed runs',
        (tester) async {
      await pumpApp(
        tester,
        client: fakeClient({
          '/runs': '{"items": [], "total": 0, "limit": 50, "offset": 0}'
        }),
        location: '/runs',
      );
      expect(find.textContaining('No completed runs'), findsOneWidget);
      expect(find.textContaining('flowguard.rl runs'), findsOneWidget);
    });

    testWidgets('error: a dead database reads as unavailable, not "not found"',
        (tester) async {
      await pumpApp(
        tester,
        client: failingClient(
            503, '{"status": "unavailable", "detail": "OperationalError"}'),
        location: '/runs',
      );
      expect(find.textContaining('database is unavailable'), findsOneWidget);
    });
  });

  group('run detail screen', () {
    testWidgets('expected: header stats and the known optimum', (tester) async {
      await pumpApp(tester,
          client: fakeClient({'/series': fixture('series.json')}),
          location: '/runs/1091');
      expect(find.text('Run 1091'), findsOneWidget);
      expect(find.text('Trials used'), findsOneWidget);
      // The number the API, the harness and the query layer all report.
      expect(find.textContaining('299.1856'), findsWidgets);
      expect(find.textContaining('of 160 trials'), findsOneWidget);
    });

    testWidgets(
        'not-chartable: a failed run says what happened and where to look',
        (tester) async {
      await pumpApp(
        tester,
        client: failingClient(404,
            '{"detail": {"reason": "run_not_chartable", "run_id": 42, "status": "failed"}}'),
        location: '/runs/42',
      );
      // This is the state most likely to be collapsed into a generic failure.
      expect(find.textContaining('did not complete'), findsOneWidget);
      expect(find.textContaining('failed'), findsWidgets);
      expect(find.textContaining('show <id> --trace'), findsOneWidget);
    });

    testWidgets('error: an unknown run is distinct from a failed one',
        (tester) async {
      await pumpApp(
        tester,
        client: failingClient(
            404, '{"detail": {"reason": "unknown_run", "run_id": 999}}'),
        location: '/runs/999',
      );
      expect(find.text('No such run.'), findsOneWidget);
      expect(find.textContaining('did not complete'), findsNothing);
    });
  });

  group('comparison screen', () {
    testWidgets('expected: the matrix plus the provenance strip', (tester) async {
      // The v3.05 matrix replaced the v3.03 table here; charts/comparison_matrix_test.dart
      // owns the grid's behaviour, so this keeps only the screen-level assertions.
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient({'/comparison': fixture('comparison.json')}),
          location: '/comparison');
      // The subtitle, not the title: "Comparison" is also an app-bar nav button.
      expect(find.text('Algorithms across circuits and loads'), findsOneWidget);
      expect(find.textContaining('Catalog default'), findsOneWidget);
      expect(find.textContaining('optimum_method'), findsOneWidget);
      // Two tables now: the matrix, and the equal_split section beneath it.
      expect(find.byType(DataTable), findsNWidgets(2));
    });

    testWidgets('empty: available:false is a state, not an error',
        (tester) async {
      await pumpApp(
        tester,
        client: fakeClient({
          '/comparison': '{"available": false, "benchmark": null, "cells": []}'
        }),
        location: '/comparison',
      );
      expect(find.textContaining('No benchmark has been run yet'), findsOneWidget);
      expect(find.textContaining('flowguard.rl benchmark'), findsOneWidget);
    });
  });

  group('routing', () {
    testWidgets('a deep link loads the run directly', (tester) async {
      await pumpApp(tester,
          client: fakeClient({'/series': fixture('series.json')}),
          location: '/runs/1091');
      expect(find.text('Run 1091'), findsOneWidget);
    });

    testWidgets('an unknown route shows not-found rather than crashing',
        (tester) async {
      await pumpApp(tester,
          client: fakeClient(const {}), location: '/no-such-screen');
      expect(find.text('Not found'), findsOneWidget);
    });

    testWidgets('a malformed run id shows not-found', (tester) async {
      await pumpApp(tester,
          client: fakeClient(const {}), location: '/runs/not-a-number');
      expect(find.text('Not found'), findsOneWidget);
    });
  });

  group('formatLoad', () {
    test('groups thousands, because 20000 is easy to misread', () {
      expect(formatLoad(10000), '10,000');
      expect(formatLoad(20000), '20,000');
      expect(formatLoad(1440), '1,440');
      expect(formatLoad(60), '60');
      expect(formatLoad(0), '0');
    });

    test('keeps a fraction rather than rounding it into looking exact', () {
      expect(formatLoad(1234.5), '1,234.50');
      expect(formatLoad(-1234.5), '-1,234.50');
    });
  });
}

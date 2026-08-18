/// The comparison matrix, rendered through the real router, client and providers.
library;

import 'package:flowguard_dashboard/charts/comparison_matrix.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers.dart';

Map<String, String> comparisonRoutes({String fixtureName = 'comparison.json'}) => {
      '/comparison': fixture(fixtureName),
      '/runs': fixture('runs.json'),
    };

void main() {
  group('expected', () {
    testWidgets('renders the grid with hill_climb optimal in every row',
        (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(comparisonRoutes()), location: '/comparison');

      expect(find.byType(ComparisonMatrix), findsOneWidget);
      // 8 scenarios, each with hill_climb at the optimum.
      expect(find.text('0.00%'), findsNWidgets(8));
      // The optimal state carries a glyph as well as a colour.
      expect(find.byIcon(Icons.check), findsWidgets);
      // Twice: once as a matrix row, once in the equal_split section below it.
      expect(find.text('C4 @ 10000'), findsNWidgets(2));
    });

    testWidgets('prints the exact value even when clamped', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(comparisonRoutes()), location: '/comparison');

      // release_sweep on C3@60 is 200% — above the ramp ceiling, still shown exactly.
      expect(find.text('200.00%'), findsOneWidget);
      expect(find.textContaining('paint at the top of the ramp'), findsOneWidget);
    });

    testWidgets('the legend explains the ramp and the optimal state', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(comparisonRoutes()), location: '/comparison');

      expect(find.byType(RegretLegend), findsOneWidget);
      expect(find.text('at optimum'), findsOneWidget);
      expect(find.text('≤10%'), findsOneWidget);
    });

    testWidgets('provenance names the catalog and benchmark', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(comparisonRoutes()), location: '/comparison');

      expect(find.textContaining('Catalog default v1'), findsOneWidget);
      expect(find.textContaining('benchmark 14'), findsOneWidget);
      expect(find.textContaining('optimum_method'), findsOneWidget);
    });
  });

  group('equal_split', () {
    testWidgets('appears as raw cost outside the grid, with its reason',
        (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(comparisonRoutes()), location: '/comparison');

      expect(find.textContaining('equal_split — outside the comparison'), findsOneWidget);
      expect(find.textContaining('Disposes the whole load in one cycle'), findsOneWidget);
      // Its raw cost for C4@10000, not a percentage.
      expect(find.text('1.6810e+19'), findsOneWidget);
      // And it is not a matrix column.
      expect(find.widgetWithText(DataTable, 'equal_split'), findsNothing);
    });
  });

  group('honest absence', () {
    testWidgets('a fallback optimum is marked and explained', (tester) async {
      useTallSurface(tester);
      await pumpApp(
        tester,
        client: fakeClient(comparisonRoutes(fixtureName: 'comparison_fallback.json')),
        location: '/comparison',
      );
      // The fallback glyph appears for the C3@60 cells.
      expect(find.byIcon(Icons.help_outline), findsWidgets);
    });

    testWidgets('a combination never run reads as "not run", never 0%',
        (tester) async {
      useTallSurface(tester);
      await pumpApp(
        tester,
        client: fakeClient(comparisonRoutes(fixtureName: 'comparison_fallback.json')),
        location: '/comparison',
      );
      // The fixture drops release_sweep at C2@1440 entirely.
      expect(find.text('—'), findsOneWidget);
      // Five scenarios in that fixture, so exactly five optimal cells — the hole is not one.
      expect(find.text('0.00%'), findsNWidgets(5));
    });

    testWidgets('an empty corpus keeps the v3.03 empty state', (tester) async {
      useTallSurface(tester);
      await pumpApp(
        tester,
        client: fakeClient({
          '/comparison': '{"available": false, "benchmark": null, "cells": []}',
        }),
        location: '/comparison',
      );
      expect(find.textContaining('No benchmark has been run yet'), findsOneWidget);
      expect(find.textContaining('flowguard.rl benchmark'), findsOneWidget);
    });
  });

  group('facets', () {
    testWidgets('states which population is on screen', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(comparisonRoutes()), location: '/comparison');

      expect(find.textContaining('Showing: integer · opaque · cold-started'),
          findsOneWidget);
      // The shipped corpus has only one population, and the view says so.
      expect(find.textContaining('only this population'), findsOneWidget);
    });
  });

  group('navigation', () {
    testWidgets('tapping a cell opens that population\'s runs', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(comparisonRoutes()), location: '/comparison');

      // The first optimal cell belongs to C2@60 / hill_climb.
      await tester.tap(find.text('0.00%').first);
      await tester.pumpAndSettle();

      // A cell has no run id, so it lands on the filtered run list rather than a run.
      expect(find.text('Runs'), findsOneWidget);
      expect(find.textContaining('C2 at L=60 · hill_climb'), findsOneWidget);
    });
  });
}

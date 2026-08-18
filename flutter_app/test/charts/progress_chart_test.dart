/// The progress view, end to end through the real router, client and providers.
///
/// Only the HTTP transport is faked, so these run with no backend. Assertions target the data
/// and text the widget was given rather than painted pixels — a chart test that inspects pixels
/// tests the rendering engine, not this code.
library;

import 'dart:math' as math;

import 'package:fl_chart/fl_chart.dart';
import 'package:flowguard_dashboard/charts/progress_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers.dart';

/// Route order matters: `fakeClient` matches by substring, and '/runs' would also match
/// '/runs/1091/series'. More specific keys first.
Map<String, String> runDetailRoutes({String series = 'series.json'}) => {
      '/series': fixture(series),
      '/allocations': fixture('allocations.json'),
      '/runs': fixture('runs.json'),
    };

void main() {
  group('expected', () {
    testWidgets('renders the chart with the run header and trial count',
        (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(runDetailRoutes()), location: '/runs/1091');

      expect(find.text('Run 1091'), findsOneWidget);
      expect(find.byType(LineChart), findsOneWidget);
      expect(find.textContaining('of 160 trials'), findsOneWidget);
      expect(find.textContaining('every improving trial is kept'), findsOneWidget);
    });

    testWidgets('shows the optimum with its method, and best-of-random',
        (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(runDetailRoutes()), location: '/runs/1091');

      // The optimum reference — provenance is never separated from the number.
      expect(find.textContaining('299.1856'), findsWidgets);
      expect(find.textContaining('enumerated'), findsWidgets);
      // Catalog provenance for the reference figures.
      expect(find.textContaining('catalog default v1'), findsOneWidget);
    });

    testWidgets('the chart is given both marks per series', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(runDetailRoutes()), location: '/runs/1091');

      final chart = tester.widget<LineChart>(find.byType(LineChart));
      // Two bars per run: the trial cloud (dots, no line) and the envelope (line, no dots).
      expect(chart.data.lineBarsData.length, 2);
      expect(chart.data.lineBarsData[0].barWidth, 0);
      expect(chart.data.lineBarsData[0].dotData.show, isTrue);
      expect(chart.data.lineBarsData[1].barWidth, greaterThan(0));
      // Optimum + best-of-random.
      expect(chart.data.extraLinesData.horizontalLines.length, 2);
    });

    testWidgets('improving trials get the larger green dot', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(runDetailRoutes()), location: '/runs/1091');

      final chart = tester.widget<LineChart>(find.byType(LineChart));
      final cloud = chart.data.lineBarsData[0];
      final painters = [
        for (var i = 0; i < cloud.spots.length; i++)
          cloud.dotData.getDotPainter(cloud.spots[i], 0, cloud, i)
              as FlDotCirclePainter,
      ];
      final improved = painters.where((p) => p.radius == 5).toList();
      final ordinary = painters.where((p) => p.radius == 2.5).toList();

      // Run 1091's 18 retained trials include its improvements; both kinds are present.
      expect(improved, isNotEmpty);
      expect(ordinary, isNotEmpty);
      // Size and a ring do the work; the colour is emphasis on top of them.
      expect(improved.first.strokeWidth, greaterThan(0));
      expect(improved.first.color, isNot(ordinary.first.color));
    });

    testWidgets('the chart says in words what the green dots mean', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(runDetailRoutes()), location: '/runs/1091');
      // Meaning must never rest on colour alone.
      expect(find.textContaining('green dots mark the trials that improved'),
          findsOneWidget);
    });

    testWidgets('the envelope ends at the known optimum', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(runDetailRoutes()), location: '/runs/1091');

      final chart = tester.widget<LineChart>(find.byType(LineChart));
      final envelope = chart.data.lineBarsData[1].spots;
      // Plotted as log10 — invert to compare against the real cost.
      final lastCost = pow10(envelope.last.y);
      expect(lastCost, closeTo(299.1856, 0.01));
    });

    testWidgets('allocation bars show the run\'s nodes', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(runDetailRoutes()), location: '/runs/1091');

      expect(find.textContaining('Allocation at trial'), findsOneWidget);
      expect(find.text('N1'), findsOneWidget);
      expect(find.text('N3'), findsOneWidget);
    });
  });

  group('axis', () {
    testWidgets('toggling to linear keeps the chart and the envelope',
        (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(runDetailRoutes()), location: '/runs/1091');

      await tester.tap(find.text('linear'));
      await tester.pumpAndSettle();

      final chart = tester.widget<LineChart>(find.byType(LineChart));
      final envelope = chart.data.lineBarsData[1].spots;
      // Linear: the plotted value IS the cost, no inversion needed.
      expect(envelope.last.y, closeTo(299.1856, 0.01));
    });
  });

  group('replay', () {
    testWidgets('the scrubber reveals a prefix of the trials', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(runDetailRoutes()), location: '/runs/1091');

      final before =
          tester.widget<LineChart>(find.byType(LineChart)).data.lineBarsData[0].spots.length;

      // Drag the slider back toward the start.
      await tester.drag(find.byType(Slider), const Offset(-400, 0));
      await tester.pumpAndSettle();

      final after =
          tester.widget<LineChart>(find.byType(LineChart)).data.lineBarsData[0].spots.length;
      expect(after, lessThan(before));
      expect(after, greaterThan(0));
    });
  });

  group('edge', () {
    testWidgets('a scenario with no benchmark draws no reference lines',
        (tester) async {
      useTallSurface(tester);
      await pumpApp(
        tester,
        client: fakeClient(runDetailRoutes(series: 'series_no_reference.json')),
        location: '/runs/359',
      );

      expect(find.textContaining('No benchmark covers this scenario'), findsOneWidget);
      final chart = tester.widget<LineChart>(find.byType(LineChart));
      expect(chart.data.extraLinesData.horizontalLines, isEmpty);
    });

    testWidgets('mismatched allocations are withheld, not shown against the wrong trial',
        (tester) async {
      // series_no_reference has 7 points; allocations.json has 18 — deliberately unaligned.
      useTallSurface(tester);
      await pumpApp(
        tester,
        client: fakeClient(runDetailRoutes(series: 'series_no_reference.json')),
        location: '/runs/359',
      );
      expect(find.textContaining('do not line up'), findsOneWidget);
    });
  });

  group('legend', () {
    testWidgets('is absent for a single series', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(runDetailRoutes()), location: '/runs/1091');
      expect(find.byType(SeriesLegend), findsNothing);
    });
  });
}

/// 10^value — the inverse of the chart's log transform.
double pow10(double value) => math.pow(10, value).toDouble();

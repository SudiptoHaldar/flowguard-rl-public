/// The progress chart (req_003 v3.04): cost vs trial, with the best-so-far envelope.
///
/// One `LineChart` carries both marks per run — a bar with `barWidth: 0` and visible dots *is*
/// the trial cloud, and a second bar with dots off is the envelope. No chart compositing.
///
/// **fl_chart has no log scale**, so every value here passes through
/// [chart_geometry.toAxis] and axis labels/tooltips invert it with `fromAxis`. Reference lines
/// go through the same transform — a line drawn from an untransformed value would land
/// somewhere plausible and wrong.
library;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../api/models.dart';
import '../theme.dart';
import 'chart_geometry.dart';

class ProgressChart extends StatelessWidget {
  const ProgressChart({
    super.key,
    required this.series,
    required this.scale,
    required this.step,
  });

  /// One entry per overlaid run, in palette order. Capped at [maxOverlaySeries].
  final List<RunSeries> series;
  final AxisScale scale;

  /// Scrubber position; trials with a greater `stepIndex` are not yet revealed.
  final int step;

  /// Reference lines come from the focused (first) run — the overlay shares its scenario.
  ScenarioReference? get _reference => series.isEmpty ? null : series.first.reference;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final costs = series.expand((s) => s.points.map((p) => p.totalCost)).toList();
    if (costs.isEmpty) {
      return const Center(child: Text('No trials to plot.'));
    }
    final floor = axisFloor(costs);
    final reference = _reference;
    final bounds = axisBounds(
      costs,
      scale,
      floor,
      extra: [
        if (reference?.optimum != null) reference!.optimum!,
        if (reference?.bestOfRandom != null) reference!.bestOfRandom!,
      ],
    );

    return LineChart(
      LineChartData(
        minX: 0,
        maxX: lastStep(series).toDouble() + 1,
        minY: bounds.min,
        maxY: bounds.max,
        lineBarsData: [
          for (var i = 0; i < series.length; i++)
            ..._barsFor(i, floor, theme.colorScheme),
        ],
        extraLinesData: _referenceLines(context, floor),
        gridData: FlGridData(
          show: true,
          drawVerticalLine: false,
          getDrawingHorizontalLine: (_) =>
              FlLine(color: theme.colorScheme.outlineVariant, strokeWidth: 0.5),
        ),
        borderData: FlBorderData(show: false),
        titlesData: _titles(context),
        lineTouchData: _touch(context),
      ),
    );
  }

  /// Two bars per run: the revealed trial cloud, then its envelope.
  ///
  /// **Always two, even when nothing is revealed yet** — [barRole] decodes a bar index back to
  /// its run, and skipping empty bars would shift every later run's index.
  List<LineChartBarData> _barsFor(int index, double floor, ColorScheme scheme) {
    final brightness = scheme.brightness;
    final style = seriesPalette[index % seriesPalette.length];
    final colour = style.color(brightness);
    final improved = improvementColor(brightness);
    final revealed = revealUpTo(series[index].points, (p) => p.stepIndex, step);

    return [
      // The cloud the envelope descends through: dots only, no connecting line.
      LineChartBarData(
        spots: [
          for (final point in revealed)
            FlSpot(point.stepIndex.toDouble(), toAxis(point.totalCost, scale, floor)),
        ],
        barWidth: 0,
        color: colour.withValues(alpha: 0.45),
        dotData: FlDotData(
          show: true,
          getDotPainter: (spot, percent, bar, i) {
            // Trials that moved the best-so-far are the moments the run actually progressed,
            // so they are twice the size and ringed against the surface — visible whatever the
            // series hue is and whatever they overlap.
            if (i < revealed.length && revealed[i].isBest) {
              return FlDotCirclePainter(
                radius: 5,
                color: improved,
                strokeWidth: 1.5,
                strokeColor: scheme.surface,
              );
            }
            return _markerPainter(style, colour.withValues(alpha: 0.45));
          },
        ),
      ),
      // The envelope — the line the eye should follow.
      LineChartBarData(
        spots: [
          for (final point in revealed)
            FlSpot(point.stepIndex.toDouble(), toAxis(point.bestSoFar, scale, floor)),
        ],
        color: colour,
        barWidth: 2,
        dashArray: style.dashArray,
        isStepLineChart: true,
        dotData: FlDotData(
          show: revealed.length == 1, // a one-trial run must still be visible
          getDotPainter: (spot, percent, bar, i) => _markerPainter(style, colour),
        ),
      ),
    ];
  }

  FlDotPainter _markerPainter(SeriesStyle style, Color colour) => switch (style.marker) {
        SeriesMarker.circle =>
          FlDotCirclePainter(radius: 2.5, color: colour, strokeWidth: 0),
        SeriesMarker.square => FlDotSquarePainter(
            size: 4.5,
            color: colour,
            strokeWidth: 0,
          ),
        SeriesMarker.triangle => FlDotCrossPainter(size: 5, color: colour, width: 1.5),
      };

  /// Optimum and best-of-random, drawn in chrome ink — annotation, never a palette colour,
  /// so a reference line can never read as another algorithm.
  ExtraLinesData _referenceLines(BuildContext context, double floor) {
    final reference = _reference;
    if (reference == null) return const ExtraLinesData();
    final scheme = Theme.of(context).colorScheme;
    return ExtraLinesData(
      horizontalLines: [
        if (reference.optimum != null)
          HorizontalLine(
            y: toAxis(reference.optimum!, scale, floor),
            color: scheme.outline,
            strokeWidth: 1.5,
            dashArray: const [6, 4],
            label: HorizontalLineLabel(
              show: true,
              alignment: Alignment.topRight,
              style: TextStyle(fontSize: 10, color: scheme.onSurfaceVariant),
              labelResolver: (_) =>
                  'optimum ${formatAxisCost(reference.optimum!)} (${reference.optimumMethod})',
            ),
          ),
        if (reference.bestOfRandom != null)
          HorizontalLine(
            y: toAxis(reference.bestOfRandom!, scale, floor),
            color: scheme.outlineVariant,
            strokeWidth: 1,
            dashArray: const [2, 5],
            label: HorizontalLineLabel(
              show: true,
              alignment: Alignment.bottomRight,
              style: TextStyle(fontSize: 10, color: scheme.onSurfaceVariant),
              labelResolver: (_) => 'best-of-random '
                  '${formatAxisCost(reference.bestOfRandom!)}'
                  '${reference.bestOfRandomStrategyVersion == null ? '' : ' (v${reference.bestOfRandomStrategyVersion})'}',
            ),
          ),
      ],
    );
  }

  FlTitlesData _titles(BuildContext context) {
    final labelStyle = Theme.of(context).textTheme.labelSmall;
    return FlTitlesData(
      topTitles: const AxisTitles(),
      rightTitles: const AxisTitles(),
      leftTitles: AxisTitles(
        axisNameWidget: Text('cost', style: labelStyle),
        sideTitles: SideTitles(
          showTitles: true,
          reservedSize: 56,
          // Labels always show the real cost — never the log value.
          getTitlesWidget: (value, meta) => Text(
            formatAxisCost(fromAxis(value, scale)),
            style: labelStyle,
          ),
        ),
      ),
      bottomTitles: AxisTitles(
        axisNameWidget: Text('trial', style: labelStyle),
        sideTitles: SideTitles(
          showTitles: true,
          reservedSize: 28,
          getTitlesWidget: (value, meta) =>
              Text(value.toInt().toString(), style: labelStyle),
        ),
      ),
    );
  }

  LineTouchData _touch(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return LineTouchData(
      touchTooltipData: LineTouchTooltipData(
        getTooltipColor: (_) => scheme.inverseSurface,
        tooltipBorder: BorderSide(color: scheme.outline.withValues(alpha: 0.6)),
        tooltipBorderRadius: BorderRadius.circular(6),
        tooltipPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        // The default 120 is too narrow for "best so far  1.2e+13" and wraps it mid-pair.
        maxContentWidth: 240,
        getTooltipItems: (spots) => [
          for (var i = 0; i < spots.length; i++)
            _tooltipItem(spots[i], scheme, showTrial: i == 0),
        ],
      ),
    );
  }

  /// One tooltip row, styled so the two marks read as different things at a glance.
  ///
  /// fl_chart fills the tooltip once, not per row, so the separation is carried by a rule, by
  /// ink strength and by weight: the envelope — the line the eye follows — is full-strength and
  /// bold, the raw trial is muted context beside it.
  ///
  /// Text wears text tokens, never the series colour; the mark on the chart carries identity,
  /// and a coloured number on a dark tooltip would only weaken contrast.
  LineTooltipItem _tooltipItem(
    LineBarSpot spot,
    ColorScheme scheme, {
    required bool showTrial,
  }) {
    final role = barRole(spot.barIndex);
    // Real units — the log transform never reaches the reader.
    final cost = formatAxisCost(fromAxis(spot.y, scale));
    final ink = scheme.onInverseSurface;
    final muted = ink.withValues(alpha: 0.68);

    final runPrefix = series.length > 1 && role.runIndex < series.length
        ? 'run ${series[role.runIndex].run.runId} · '
        : '';

    return LineTooltipItem(
      '',
      TextStyle(color: muted, fontSize: 11),
      textAlign: TextAlign.left,
      children: [
        if (showTrial)
          TextSpan(
            text: 'trial ${spot.x.toInt()}\n',
            style: TextStyle(
              color: muted,
              fontSize: 10,
              letterSpacing: 0.6,
              height: 1.5,
            ),
          ),
        // The rule sits above the envelope row, dividing it from the trial above.
        if (role.isEnvelope)
          TextSpan(
            text: '${'─' * 16}\n',
            style: TextStyle(
              color: ink.withValues(alpha: 0.28),
              fontSize: 9,
              height: 1.1,
            ),
          ),
        TextSpan(
          text: '$runPrefix${barLabel(spot.barIndex)}  ',
          style: TextStyle(color: muted, fontSize: 10, height: 1.5),
        ),
        TextSpan(
          text: cost,
          style: TextStyle(
            color: role.isEnvelope ? ink : muted,
            fontSize: role.isEnvelope ? 13 : 11,
            fontWeight: role.isEnvelope ? FontWeight.w700 : FontWeight.w400,
            height: 1.5,
          ),
        ),
      ],
    );
  }
}

/// Legend for the overlaid series. Present whenever there is more than one, and it carries the
/// full grouping key — an unlabelled overlay invites the viewer to pool it by eye.
class SeriesLegend extends StatelessWidget {
  const SeriesLegend({super.key, required this.series});

  final List<RunSeries> series;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Wrap(
      spacing: 16,
      runSpacing: 6,
      children: [
        for (var i = 0; i < series.length; i++)
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 14,
                height: 3,
                decoration: BoxDecoration(
                  color: seriesPalette[i % seriesPalette.length]
                      .color(theme.brightness),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              const SizedBox(width: 6),
              // Text wears text tokens, never the series colour; the swatch carries identity.
              Text(
                'run ${series[i].run.runId} · ${series[i].run.groupingLabel}',
                style: theme.textTheme.labelSmall,
              ),
            ],
          ),
      ],
    );
  }
}

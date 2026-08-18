/// Per-node allocation panels (req_003 v3.06 D2) — small multiples, one per external node.
///
/// The form is chosen for the capacity marks: each node has its own `load_factor` and
/// `load_safety_cap`, and only a per-node panel can carry them. A stacked area would read the
/// split well but has nowhere to put a per-node limit.
///
/// **Panels share the x-axis and the scrubber, but each has its own y-axis.** C3 spans N4's
/// factor of 2 against N3's factor of 20, so a shared scale would flatten the small nodes into
/// the baseline. This is not in tension with the comparison matrix's single global scale: there
/// every cell measured the same quantity, here each panel measures a different node against its
/// own capacity.
library;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../api/models.dart';
import '../theme.dart';
import 'allocation_geometry.dart';

class AllocationPanels extends StatelessWidget {
  const AllocationPanels({
    super.key,
    required this.series,
    required this.step,
  });

  final AllocationSeries series;
  final int step;

  @override
  Widget build(BuildContext context) {
    final marks = markState(series.capacities);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (marks != MarkState.shown) _MarksWithheld(state: marks, series: series),
        for (var i = 0; i < series.nodeNames.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: 20),
            child: _NodePanel(
              series: series,
              index: i,
              step: step,
              node: nodeFor(series.capacities, i),
            ),
          ),
      ],
    );
  }
}

class _NodePanel extends StatelessWidget {
  const _NodePanel({
    required this.series,
    required this.index,
    required this.step,
    required this.node,
  });

  final AllocationSeries series;
  final int index;
  final int step;
  final ExternalNode? node;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    // The RUN's node list names the axis — never the circuit's current one.
    final name = series.nodeNames[index];
    final points = nodeSeries(series, index, step);
    final bounds = panelBounds(points.map((p) => p.y), node);
    final crossed = crossings(points, node);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(name, style: theme.textTheme.titleSmall),
            const SizedBox(width: 8),
            if (node != null)
              Text(
                'factor ${node!.loadFactor.toStringAsFixed(0)} · '
                'safety cap ${node!.loadSafetyCap.toStringAsFixed(0)}',
                style: theme.textTheme.labelSmall,
              ),
            const Spacer(),
            // Stated in words too, so a crossing is never carried by a line's position alone.
            if (crossed.overSafetyCap)
              Text('crosses its safety cap',
                  style: theme.textTheme.labelSmall
                      ?.copyWith(color: scheme.error))
            else if (crossed.overFactor)
              Text('crosses its load factor', style: theme.textTheme.labelSmall),
          ],
        ),
        const SizedBox(height: 6),
        SizedBox(
          height: 140,
          child: points.isEmpty
              ? Center(
                  child: Text('no trials revealed yet',
                      style: theme.textTheme.labelSmall),
                )
              : LineChart(
                  LineChartData(
                    minX: 0,
                    maxX: lastAllocationStep(series).toDouble() + 1,
                    minY: bounds.min,
                    maxY: bounds.max,
                    lineBarsData: [
                      LineChartBarData(
                        spots: [
                          for (final point in points) FlSpot(point.x, point.y),
                        ],
                        color: seriesPalette.first.color(theme.brightness),
                        barWidth: 2,
                        isStepLineChart: true,
                        // A single-trial run must still show something.
                        dotData: FlDotData(show: points.length == 1),
                      ),
                    ],
                    extraLinesData: _marks(scheme),
                    gridData: FlGridData(
                      show: true,
                      drawVerticalLine: false,
                      getDrawingHorizontalLine: (_) => FlLine(
                          color: scheme.outlineVariant, strokeWidth: 0.5),
                    ),
                    borderData: FlBorderData(show: false),
                    titlesData: _titles(theme),
                    lineTouchData: _touch(scheme, name),
                  ),
                ),
        ),
      ],
    );
  }

  /// Capacity marks in **chrome ink**, never the series palette — a limit line must not read
  /// as another series.
  ExtraLinesData _marks(ColorScheme scheme) {
    if (node == null) return const ExtraLinesData();
    return ExtraLinesData(
      horizontalLines: [
        HorizontalLine(
          y: node!.loadFactor,
          color: scheme.outline,
          strokeWidth: 1.5,
          dashArray: const [6, 4],
          label: HorizontalLineLabel(
            show: true,
            alignment: Alignment.topRight,
            style: TextStyle(fontSize: 9, color: scheme.onSurfaceVariant),
            labelResolver: (_) => 'factor',
          ),
        ),
        HorizontalLine(
          y: node!.loadSafetyCap,
          color: scheme.error.withValues(alpha: 0.75),
          strokeWidth: 1.5,
          dashArray: const [2, 4],
          label: HorizontalLineLabel(
            show: true,
            alignment: Alignment.bottomRight,
            style: TextStyle(fontSize: 9, color: scheme.error),
            labelResolver: (_) => 'safety cap',
          ),
        ),
      ],
    );
  }

  FlTitlesData _titles(ThemeData theme) => FlTitlesData(
        topTitles: const AxisTitles(),
        rightTitles: const AxisTitles(),
        leftTitles: AxisTitles(
          sideTitles: SideTitles(
            showTitles: true,
            reservedSize: 36,
            getTitlesWidget: (value, meta) => Text(
              value.toStringAsFixed(0),
              style: theme.textTheme.labelSmall,
            ),
          ),
        ),
        bottomTitles: AxisTitles(
          sideTitles: SideTitles(
            showTitles: true,
            reservedSize: 24,
            getTitlesWidget: (value, meta) => Text(
              value.toInt().toString(),
              style: theme.textTheme.labelSmall,
            ),
          ),
        ),
      );

  LineTouchData _touch(ColorScheme scheme, String name) => LineTouchData(
        touchTooltipData: LineTouchTooltipData(
          getTooltipColor: (_) => scheme.inverseSurface,
          getTooltipItems: (spots) => [
            for (final spot in spots)
              LineTooltipItem(
                'trial ${spot.x.toInt()}\n$name  ${spot.y.toStringAsFixed(2)}',
                TextStyle(color: scheme.onInverseSurface, fontSize: 11),
              ),
          ],
        ),
      );
}

/// Says why the marks are absent — the two reasons are different and both matter.
class _MarksWithheld extends StatelessWidget {
  const _MarksWithheld({required this.state, required this.series});

  final MarkState state;
  final AllocationSeries series;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final current = series.capacities?.nodes.map((n) => n.name).join(', ');
    final message = state == MarkState.circuitMissing
        ? 'Capacity marks are unavailable: circuit "${series.nodeNames.join(', ')}" '
            'no longer exists, so there is nothing to compare against.'
        : 'Capacity marks are withheld: this run used [${series.nodeNames.join(', ')}], '
            'but the circuit now has [$current]. Drawing limits from a definition the run '
            'never saw would be worse than showing none.';

    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Icon(Icons.info_outline, size: 18, color: theme.colorScheme.outline),
          const SizedBox(width: 8),
          Expanded(child: Text(message, style: theme.textTheme.bodySmall)),
        ],
      ),
    );
  }
}

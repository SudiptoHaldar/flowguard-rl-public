/// The scenario × strategy comparison matrix (req_003 v3.05).
///
/// Built from widgets rather than a charting library: at 8 × 3 this is a grid of coloured cells
/// with printed values, and Flutter is good at grids.
///
/// Every rule that keeps it honest is visible in one place here — the value is always printed
/// (colour cannot be read precisely), zero regret is distinguished rather than palest, a
/// fallback optimum is marked, and an absent measurement says so instead of showing 0%.
library;

import 'package:flutter/material.dart';

import '../api/models.dart';
import '../screens/app_scaffold.dart';
import '../theme.dart';
import 'matrix_geometry.dart';

class ComparisonMatrix extends StatelessWidget {
  const ComparisonMatrix({
    super.key,
    required this.cells,
    required this.onCellTap,
  });

  /// Cells for a single population; `equal_split` is filtered out by [strategyColumns].
  final List<ComparisonCell> cells;

  /// A cell carries no run id — it is an aggregate over a population — so the callback receives
  /// the population's coordinates and the caller routes to the filtered run list.
  final void Function(ScenarioKey row, StrategyKey column) onCellTap;

  @override
  Widget build(BuildContext context) {
    final rows = scenarioRows(cells);
    final columns = strategyColumns(cells);
    if (rows.isEmpty || columns.isEmpty) {
      return const SizedBox.shrink();
    }
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        columnSpacing: 12,
        headingRowHeight: 44,
        dataRowMinHeight: 46,
        dataRowMaxHeight: 58,
        columns: [
          const DataColumn(label: Text('Scenario')),
          for (final column in columns)
            DataColumn(
              label: Text(
                column.version == null
                    ? column.strategy
                    : '${column.strategy} ${column.version}',
              ),
            ),
        ],
        rows: [
          for (final row in rows)
            DataRow(
              cells: [
                DataCell(Text('${row.circuit} @ ${row.load.toStringAsFixed(0)}')),
                for (final column in columns)
                  DataCell(
                    _MatrixCell(
                      cell: cellAt(cells, row, column),
                      onTap: () => onCellTap(row, column),
                    ),
                  ),
              ],
            ),
        ],
      ),
    );
  }
}

class _MatrixCell extends StatelessWidget {
  const _MatrixCell({required this.cell, required this.onTap});

  final ComparisonCell? cell;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = classify(cell);

    // Absent or incomparable measurements are stated, never painted as zero: 0% in this metric
    // means "at the optimum", which is the opposite of "we don't know".
    if (state == CellState.notRun) {
      return _Plain(label: '—', tooltip: 'not run');
    }
    if (state == CellState.notComparable) {
      return const _Plain(label: 'n/a', tooltip: 'no optimum recorded for this scenario');
    }

    final percent = regretPercent(cell!)!;
    final brightness = theme.brightness;
    final optimal = state == CellState.optimal;
    final step = rampIndex(percent);
    final fill = optimal ? optimalFill(brightness) : regretRamp(brightness)[step];
    final ink = regretInk(fill);

    return Tooltip(
      richMessage: TextSpan(text: _tooltip(cell!, percent, state)),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(6),
        child: Container(
          width: 104,
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
          decoration: BoxDecoration(
            color: fill,
            borderRadius: BorderRadius.circular(6),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // Colour never carries the meaning alone: optimal gets a glyph, a fallback
              // optimum gets a mark, and the number is printed either way.
              if (optimal) ...[
                Icon(Icons.check, size: 14, color: ink),
                const SizedBox(width: 4),
              ] else if (state == CellState.fallback) ...[
                Icon(Icons.help_outline, size: 13, color: ink),
                const SizedBox(width: 4),
              ],
              Flexible(
                child: Text(
                  '${percent.toStringAsFixed(2)}%',
                  style: theme.textTheme.labelMedium?.copyWith(
                    color: ink,
                    fontWeight: optimal ? FontWeight.w700 : FontWeight.w500,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _tooltip(ComparisonCell cell, double percent, CellState state) => [
        '${cell.strategy}${cell.strategyVersion == null ? '' : ' ${cell.strategyVersion}'}'
            ' · ${cell.circuitName} @ ${cell.totalLoad.toStringAsFixed(0)}',
        'median cost ${formatCost(cell.bestCostMedian)}',
        // Dispersion only where it exists: a deterministic strategy runs once, and a
        // zero-width band would be a fabricated measurement.
        if (cell.runs > 1)
          'across ${cell.runs} seeds · min ${formatCost(cell.bestCostMin)}'
              ' · max ${formatCost(cell.bestCostMax)}'
        else
          'single deterministic run',
        'optimum ${formatCost(cell.optimum)} (${cell.optimumMethod})',
        if (state == CellState.optimal) 'at the optimum',
        if (state == CellState.fallback)
          'measured against a best-observed optimum — a weaker claim than an enumerated one',
        if (isClamped(percent))
          'above the ${clampCeiling.toInt()}% ramp ceiling; the value is exact',
      ].join('\n');
}

class _Plain extends StatelessWidget {
  const _Plain({required this.label, required this.tooltip});

  final String label;
  final String tooltip;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Tooltip(
      message: tooltip,
      child: Container(
        width: 104,
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: theme.colorScheme.outlineVariant),
        ),
        child: Text(
          label,
          style: theme.textTheme.labelMedium
              ?.copyWith(color: theme.colorScheme.outline),
        ),
      ),
    );
  }
}

/// Legend for the ramp: what the colours mean, and that the top is clamped.
class RegretLegend extends StatelessWidget {
  const RegretLegend({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final ramp = regretRamp(theme.brightness);
    final labels = ['≤10%', '≤25%', '≤50%', '≤100%', '>100%'];

    return Wrap(
      spacing: 12,
      runSpacing: 8,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        Text('regret vs optimum', style: theme.textTheme.labelSmall),
        _Swatch(
          color: optimalFill(theme.brightness),
          label: 'at optimum',
          icon: Icons.check,
        ),
        for (var i = 0; i < ramp.length; i++)
          _Swatch(color: ramp[i], label: labels[i]),
        Text(
          'values above ${clampCeiling.toInt()}% paint at the top of the ramp '
          'but still show their exact figure',
          style: theme.textTheme.labelSmall,
        ),
      ],
    );
  }
}

class _Swatch extends StatelessWidget {
  const _Swatch({required this.color, required this.label, this.icon});

  final Color color;
  final String label;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 18,
          height: 14,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: color,
            borderRadius: BorderRadius.circular(3),
          ),
          child: icon == null
              ? null
              : Icon(icon, size: 10, color: regretInk(color)),
        ),
        const SizedBox(width: 4),
        // Text wears text tokens; the swatch beside it carries the colour.
        Text(label, style: theme.textTheme.labelSmall),
      ],
    );
  }
}

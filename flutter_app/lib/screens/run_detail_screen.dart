/// One run's progress toward the optimum (req_003 v3.04) — the project's first chart.
///
/// The cost curve, its replay scrubber, the allocation at the current trial, an optional
/// overlay of other runs of the same Circuit(Load), and — collapsed beneath it all — the v3.03
/// trial table. The table survives because when a chart looks wrong, it is how you tell whether
/// the data or the drawing is at fault.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../api/models.dart';
import '../charts/chart_geometry.dart';
import '../charts/progress_chart.dart';
import '../state/providers.dart';
import '../widgets/allocation_bars.dart';
import '../widgets/async_view.dart';
import '../widgets/overlay_picker.dart';
import '../widgets/replay_controls.dart';
import 'app_scaffold.dart';

/// Trials shown from each end of the series in the table.
const int _edgeRows = 5;

/// Scrubber sentinel meaning "reveal everything".
const int _showAll = 1 << 30;

class RunDetailScreen extends ConsumerStatefulWidget {
  const RunDetailScreen({super.key, required this.runId});

  final int runId;

  @override
  ConsumerState<RunDetailScreen> createState() => _RunDetailScreenState();
}

class _RunDetailScreenState extends ConsumerState<RunDetailScreen> {
  // Local rather than Riverpod: this is view state that must reset when the route changes,
  // and a global provider would carry a stale scrubber position onto the next run.
  int _step = _showAll;
  AxisScale _scale = AxisScale.log;
  bool _tableExpanded = false;
  final List<int> _overlaid = [];

  void _toggleOverlay(int runId) => setState(() {
        _overlaid.contains(runId) ? _overlaid.remove(runId) : _overlaid.add(runId);
      });

  @override
  Widget build(BuildContext context) {
    final series = ref.watch(runSeriesProvider(widget.runId));
    return AppScaffold(
      title: 'Run ${widget.runId}',
      subtitle: 'Progress toward the optimum',
      child: AsyncView<RunSeries>(
        value: series,
        isEmpty: (data) => data.points.isEmpty,
        empty: const EmptyState(
          icon: Icons.timeline,
          title: 'This run recorded no trials.',
        ),
        onRetry: () => ref.invalidate(runSeriesProvider(widget.runId)),
        builder: _buildLoaded,
      ),
    );
  }

  Widget _buildLoaded(RunSeries focused) {
    // Overlaid runs load independently; any still loading simply is not drawn yet.
    final overlays = <RunSeries>[
      for (final id in _overlaid)
        ...?ref.watch(runSeriesProvider(id)).whenOrNull(data: (data) => [data]),
    ];
    final all = [focused, ...overlays];
    final last = lastStep(all);
    final step = _step == _showAll ? last : _step;
    final warning = mixedPopulationWarning(all.map((s) => s.run).toList());

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _RunHeaderCard(run: focused.run, reference: focused.reference),
        const SizedBox(height: 16),
        _ChartCard(
          series: all,
          scale: _scale,
          step: step,
          last: last,
          warning: warning,
          onScaleChanged: (scale) => setState(() => _scale = scale),
          onStepChanged: (value) => setState(() => _step = value),
        ),
        const SizedBox(height: 16),
        _AllocationCard(runId: widget.runId, series: focused, step: step),
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => context.go('/runs/${widget.runId}/allocations'),
            icon: const Icon(Icons.bar_chart),
            label: const Text('Per-node allocation panels'),
          ),
        ),
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: OverlayPicker(
              focused: focused.run,
              overlaid: _overlaid,
              onToggle: _toggleOverlay,
            ),
          ),
        ),
        const SizedBox(height: 16),
        _TrialTableCard(
          series: focused,
          expanded: _tableExpanded,
          onToggle: () => setState(() => _tableExpanded = !_tableExpanded),
        ),
      ],
    );
  }
}

class _ChartCard extends StatelessWidget {
  const _ChartCard({
    required this.series,
    required this.scale,
    required this.step,
    required this.last,
    required this.warning,
    required this.onScaleChanged,
    required this.onStepChanged,
  });

  final List<RunSeries> series;
  final AxisScale scale;
  final int step;
  final int last;
  final String? warning;
  final ValueChanged<AxisScale> onScaleChanged;
  final ValueChanged<int> onStepChanged;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final focused = series.first;
    final costs = series.expand((s) => s.points.map((p) => p.totalCost));
    final clamped = needsClamping(costs, scale);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text('Cost by trial', style: theme.textTheme.titleMedium),
                ),
                SegmentedButton<AxisScale>(
                  segments: const [
                    ButtonSegment(value: AxisScale.log, label: Text('log')),
                    ButtonSegment(value: AxisScale.linear, label: Text('linear')),
                  ],
                  selected: {scale},
                  onSelectionChanged: (values) => onScaleChanged(values.first),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              'Showing ${focused.points.length} of ${focused.totalPoints} trials'
              '${focused.downsampled ? ' — downsampled, but every improving trial is kept' : ''}'
              '${clamped ? ' · zero costs clamped to fit the log axis' : ''}',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 2),
            // Stated in words as well as drawn: the larger green dots carry meaning, so that
            // meaning must not rest on colour alone.
            Text(
              'Large green dots mark the trials that improved the best-so-far; '
              'the step line is the best cost at each point.',
              style: theme.textTheme.bodySmall,
            ),
            if (focused.reference == null) ...[
              const SizedBox(height: 4),
              Text(
                'No benchmark covers this scenario, so no reference lines are drawn.',
                style: theme.textTheme.bodySmall,
              ),
            ],
            if (neverImproved(focused.points)) ...[
              const SizedBox(height: 4),
              Text(
                'No improvement recorded — the best cost is the first trial.',
                style: theme.textTheme.bodySmall,
              ),
            ],
            if (warning != null) MixedPopulationNotice(message: warning!),
            const SizedBox(height: 16),
            SizedBox(
              height: 320,
              child: ProgressChart(series: series, scale: scale, step: step),
            ),
            const SizedBox(height: 8),
            if (series.length > 1) SeriesLegend(series: series),
            ReplayControls(
              lastStep: last,
              step: step,
              onStepChanged: onStepChanged,
            ),
          ],
        ),
      ),
    );
  }
}

class _AllocationCard extends ConsumerWidget {
  const _AllocationCard({
    required this.runId,
    required this.series,
    required this.step,
  });

  final int runId;
  final RunSeries series;
  final int step;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final allocations = ref.watch(allocationsProvider(runId));
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: AsyncView<AllocationSeries>(
          value: allocations,
          isEmpty: (data) => data.points.isEmpty,
          empty: const EmptyState(
            icon: Icons.bar_chart,
            title: 'No allocations recorded for this run.',
          ),
          onRetry: () => ref.invalidate(allocationsProvider(runId)),
          builder: (data) => AllocationBars(
            allocations: data,
            step: step,
            // Verified, not assumed: v3.01 D6 thins both series with the same keep set.
            aligned: allocationsAlignWith(series, data),
          ),
        ),
      ),
    );
  }
}

class _RunHeaderCard extends StatelessWidget {
  const _RunHeaderCard({required this.run, required this.reference});

  final RunSummary run;
  final ScenarioReference? reference;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${run.circuitName} at L=${run.totalLoad.toStringAsFixed(0)}',
                style: theme.textTheme.titleLarge),
            const SizedBox(height: 4),
            Text(run.groupingLabel, style: theme.textTheme.bodySmall),
            if (reference != null)
              Text(
                'reference: catalog ${reference!.catalogName} '
                'v${reference!.catalogVersion} (benchmark ${reference!.benchmarkId})',
                style: theme.textTheme.bodySmall,
              ),
            const Divider(height: 24),
            Wrap(
              spacing: 32,
              runSpacing: 12,
              children: [
                _Stat(label: 'Trials used', value: '${run.trialsUsed}'),
                _Stat(label: 'Budget', value: run.budget?.toString() ?? '—'),
                _Stat(label: 'First cost', value: formatCost(run.firstCost)),
                _Stat(label: 'Best cost', value: formatCost(run.bestCost)),
                _Stat(
                  label: 'Improvement',
                  value: '${(run.improvement * 100).toStringAsFixed(2)}%',
                ),
                if (reference?.optimum != null)
                  _Stat(
                    label: 'Optimum (${reference!.optimumMethod})',
                    value: formatCost(reference!.optimum),
                  ),
                _Stat(label: 'Seed', value: run.seed?.toString() ?? '—'),
                _Stat(label: 'Terminated', value: run.terminationReason ?? '—'),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(label, style: theme.textTheme.labelSmall),
        Text(value, style: theme.textTheme.titleMedium),
      ],
    );
  }
}

class _TrialTableCard extends StatelessWidget {
  const _TrialTableCard({
    required this.series,
    required this.expanded,
    required this.onToggle,
  });

  final RunSeries series;
  final bool expanded;
  final VoidCallback onToggle;

  List<SeriesPoint?> get _rows {
    final points = series.points;
    if (points.length <= _edgeRows * 2) return points;
    return [
      ...points.take(_edgeRows),
      null, // elision marker
      ...points.skip(points.length - _edgeRows),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Column(
        children: [
          ListTile(
            title: Text('Trial table', style: theme.textTheme.titleMedium),
            subtitle: const Text('the numbers behind the chart'),
            trailing: Icon(expanded ? Icons.expand_less : Icons.expand_more),
            onTap: onToggle,
          ),
          if (expanded)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: DataTable(
                  columns: const [
                    DataColumn(label: Text('Step'), numeric: true),
                    DataColumn(label: Text('Cost'), numeric: true),
                    DataColumn(label: Text('Best so far'), numeric: true),
                    DataColumn(label: Text('Improved')),
                  ],
                  rows: [
                    for (final point in _rows)
                      if (point == null)
                        const DataRow(cells: [
                          DataCell(Text('…')),
                          DataCell(Text('…')),
                          DataCell(Text('…')),
                          DataCell(Text('')),
                        ])
                      else
                        DataRow(cells: [
                          DataCell(Text('${point.stepIndex}')),
                          DataCell(Text(formatCost(point.totalCost))),
                          DataCell(Text(formatCost(point.bestSoFar))),
                          DataCell(point.isBest
                              ? const Icon(Icons.arrow_downward, size: 16)
                              : const Text('')),
                        ]),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

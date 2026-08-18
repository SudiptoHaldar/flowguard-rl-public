/// Per-node allocation view for one run (req_003 v3.06).
///
/// Where the load went, and against what it was pushing. The cost curve says a run improved;
/// this says what the optimizer actually changed, and whether it was pressing against capacity.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../api/models.dart';
import '../charts/allocation_geometry.dart';
import '../charts/allocation_panels.dart';
import '../state/providers.dart';
import '../widgets/async_view.dart';
import '../widgets/replay_controls.dart';
import 'app_scaffold.dart';

/// Scrubber sentinel meaning "reveal everything".
const int _showAll = 1 << 30;

class AllocationScreen extends ConsumerStatefulWidget {
  const AllocationScreen({super.key, required this.runId});

  final int runId;

  @override
  ConsumerState<AllocationScreen> createState() => _AllocationScreenState();
}

class _AllocationScreenState extends ConsumerState<AllocationScreen> {
  int _step = _showAll;
  int _tieIndex = 0;

  @override
  Widget build(BuildContext context) {
    final allocations = ref.watch(allocationsProvider(widget.runId));
    return AppScaffold(
      title: 'Run ${widget.runId} — allocations',
      subtitle: 'Where the load went, and against what',
      child: AsyncView<AllocationSeries>(
        value: allocations,
        isEmpty: (data) => data.points.isEmpty,
        empty: const EmptyState(
          icon: Icons.bar_chart,
          title: 'This run recorded no allocations.',
        ),
        onRetry: () => ref.invalidate(allocationsProvider(widget.runId)),
        builder: _buildLoaded,
      ),
    );
  }

  Widget _buildLoaded(AllocationSeries series) {
    final last = lastAllocationStep(series);
    final step = _step == _showAll ? last : _step;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (series.best != null)
          _BestAllocationCard(
            series: series,
            best: series.best!,
            index: _tieIndex,
            onIndexChanged: (value) => setState(() => _tieIndex = value),
          ),
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Load per node over the run',
                    style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 4),
                Text(
                  'Showing ${series.points.length} of ${series.totalPoints} trials'
                  '${series.downsampled ? ' — downsampled with the same keep set as the cost curve' : ''}'
                  '. Each panel has its own scale, because nodes differ in capacity.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 16),
                AllocationPanels(series: series, step: step),
                ReplayControls(
                  lastStep: last,
                  step: step,
                  onStepChanged: (value) => setState(() => _step = value),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => context.go('/runs/${widget.runId}/topology'),
            icon: const Icon(Icons.hub_outlined),
            label: const Text('Where the load flows (topology)'),
          ),
        ),
      ],
    );
  }
}

/// The best allocation — and, when the optimum is flat, the others that reached it.
class _BestAllocationCard extends StatelessWidget {
  const _BestAllocationCard({
    required this.series,
    required this.best,
    required this.index,
    required this.onIndexChanged,
  });

  final AllocationSeries series;
  final BestAllocations best;
  final int index;
  final ValueChanged<int> onIndexChanged;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final safeIndex = index.clamp(0, best.allocations.length - 1);
    final allocation = best.allocations[safeIndex];
    final marksUsable = markState(series.capacities) == MarkState.shown;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    // Never "the optimal allocation": with ties there is no single one.
                    'An allocation that reached ${best.cost.toStringAsFixed(4)}',
                    style: theme.textTheme.titleMedium,
                  ),
                ),
                if (best.isTied) ...[
                  IconButton(
                    tooltip: 'Previous tied allocation',
                    onPressed: safeIndex == 0
                        ? null
                        : () => onIndexChanged(safeIndex - 1),
                    icon: const Icon(Icons.chevron_left),
                  ),
                  Text('${safeIndex + 1} / ${best.allocations.length}',
                      style: theme.textTheme.labelMedium),
                  IconButton(
                    tooltip: 'Next tied allocation',
                    onPressed: safeIndex >= best.allocations.length - 1
                        ? null
                        : () => onIndexChanged(safeIndex + 1),
                    icon: const Icon(Icons.chevron_right),
                  ),
                ],
              ],
            ),
            Text(
              tieLabel(best),
              style: theme.textTheme.bodySmall,
            ),
            if (best.isTied)
              Text(
                'A flat optimum: the search had real freedom in where to put the load.',
                style: theme.textTheme.bodySmall,
              ),
            const SizedBox(height: 12),
            for (var i = 0; i < allocation.length; i++)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  children: [
                    SizedBox(
                      width: 48,
                      child: Text(
                        i < series.nodeNames.length ? series.nodeNames[i] : 'n$i',
                        style: theme.textTheme.labelMedium,
                      ),
                    ),
                    SizedBox(
                      width: 72,
                      child: Text(allocation[i].toStringAsFixed(2),
                          style: theme.textTheme.labelMedium),
                    ),
                    if (marksUsable && i < series.capacities!.nodes.length)
                      Text(
                        _against(allocation[i], series.capacities!.nodes[i]),
                        style: theme.textTheme.labelSmall,
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }

  /// Describes the load against the node's limits. A statement about the loads — the *cost* of
  /// a crossing belongs to the circuit engine, which this layer never re-derives.
  String _against(double load, ExternalNode node) {
    if (load > node.loadSafetyCap) {
      return 'above its safety cap of ${node.loadSafetyCap.toStringAsFixed(0)}';
    }
    if (load > node.loadFactor) {
      return 'above its factor of ${node.loadFactor.toStringAsFixed(0)}';
    }
    if (load == node.loadFactor) {
      return 'exactly at its factor of ${node.loadFactor.toStringAsFixed(0)}';
    }
    return 'under its factor of ${node.loadFactor.toStringAsFixed(0)}';
  }
}

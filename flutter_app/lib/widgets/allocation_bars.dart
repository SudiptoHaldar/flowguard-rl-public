/// Per-node allocation at the scrubber position (req_003 v3.04 D7).
///
/// The other half of "how it approaches": the cost curve says the search improved, this says
/// what the optimizer actually changed.
///
/// Single-run by design — with an overlay active these follow the focused series. Showing
/// several runs' allocations at once is v3.06's problem. Capacity marks (`load_factor`,
/// `load_safety_cap`) also belong there: they need circuit definitions, which this view does
/// not read.
library;

import 'package:flutter/material.dart';

import '../api/models.dart';
import '../charts/allocation_geometry.dart';
import '../charts/chart_geometry.dart';

class AllocationBars extends StatelessWidget {
  const AllocationBars({
    super.key,
    required this.allocations,
    required this.step,
    required this.aligned,
  });

  final AllocationSeries allocations;
  final int step;

  /// Whether the allocation series shares the cost series' keep set. False means the bars
  /// cannot be trusted to describe the displayed step, and the widget says so rather than
  /// drawing a confident wrong answer.
  final bool aligned;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (!aligned) {
      return _Note(
        text: 'Allocation steps do not line up with the trial series, so the bars '
            'are hidden rather than shown against the wrong trial.',
        colour: theme.colorScheme.error,
      );
    }
    final point = allocationAt(allocations, step);
    if (point == null) {
      return _Note(
        text: 'No allocation recorded at or before trial $step.',
        colour: theme.colorScheme.outline,
      );
    }
    final total = point.loads.fold<double>(0, (sum, load) => sum + load);
    // Capacity marks (v3.06 D1) share the bars' scale, so the peak must account for them —
    // otherwise a node under its factor would render a full bar and look saturated.
    final nodes = markState(allocations.capacities) == MarkState.shown
        ? allocations.capacities!.nodes
        : const <ExternalNode>[];
    final peak = [
      ...point.loads,
      for (final node in nodes) node.loadSafetyCap,
    ].fold<double>(0, (max, value) => value > max ? value : max);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Allocation at trial ${point.stepIndex}',
            style: theme.textTheme.titleSmall),
        Text('released ${total.toStringAsFixed(2)} across ${point.loads.length} nodes',
            style: theme.textTheme.labelSmall),
        const SizedBox(height: 12),
        for (var i = 0; i < point.loads.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(
              children: [
                SizedBox(
                  width: 48,
                  child: Text(
                    i < allocations.nodeNames.length
                        ? allocations.nodeNames[i]
                        : 'n$i',
                    style: theme.textTheme.labelMedium,
                  ),
                ),
                Expanded(
                  child: _BarWithMarks(
                    load: point.loads[i],
                    peak: peak,
                    node: i < nodes.length ? nodes[i] : null,
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  width: 64,
                  child: Text(
                    point.loads[i].toStringAsFixed(2),
                    textAlign: TextAlign.right,
                    style: theme.textTheme.labelMedium,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// One node's bar with its capacity marks overlaid (v3.06 D1 — the gap v3.04 D7 left).
///
/// The marks are chrome ink, never the series palette, so a limit can never read as data.
class _BarWithMarks extends StatelessWidget {
  const _BarWithMarks({
    required this.load,
    required this.peak,
    required this.node,
  });

  final double load;
  final double peak;
  final ExternalNode? node;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        double offset(double value) => peak == 0 ? 0 : (value / peak) * width;
        return SizedBox(
          height: 14,
          child: Stack(
            children: [
              Align(
                alignment: Alignment.centerLeft,
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: LinearProgressIndicator(
                    value: peak == 0 ? 0 : load / peak,
                    minHeight: 10,
                    backgroundColor: theme.colorScheme.surfaceContainerHighest,
                  ),
                ),
              ),
              if (node != null) ...[
                _Mark(
                  left: offset(node!.loadFactor),
                  colour: theme.colorScheme.outline,
                  tooltip: 'load factor ${node!.loadFactor.toStringAsFixed(0)}',
                ),
                _Mark(
                  left: offset(node!.loadSafetyCap),
                  colour: theme.colorScheme.error,
                  tooltip: 'safety cap ${node!.loadSafetyCap.toStringAsFixed(0)}',
                ),
              ],
            ],
          ),
        );
      },
    );
  }
}

class _Mark extends StatelessWidget {
  const _Mark({required this.left, required this.colour, required this.tooltip});

  final double left;
  final Color colour;
  final String tooltip;

  @override
  Widget build(BuildContext context) => Positioned(
        left: left,
        top: 0,
        bottom: 0,
        child: Tooltip(
          message: tooltip,
          child: Container(width: 2, color: colour),
        ),
      );
}

class _Note extends StatelessWidget {
  const _Note({required this.text, required this.colour});

  final String text;
  final Color colour;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: Text(
          text,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: colour),
        ),
      );
}

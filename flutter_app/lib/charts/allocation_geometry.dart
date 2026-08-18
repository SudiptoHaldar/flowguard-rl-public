/// Per-node allocation arithmetic (req_003 v3.06 D10) — pure, no widgets.
///
/// Loads are plotted **linearly**. The log transform in [chart_geometry] exists because costs
/// span fifteen orders of magnitude; loads span single digits to tens, where a log axis would
/// be unreadable and would buy nothing.
library;

import '../api/models.dart';
import 'chart_geometry.dart';

/// Whether capacity marks may be drawn, and why not when they may not.
///
/// The two "no" cases are deliberately distinct: a changed circuit and a missing one mean
/// different things to a reader, and collapsing them would hide which happened.
enum MarkState {
  /// The circuit's external nodes match the run's, so the marks describe this run.
  shown,

  /// The circuit has changed since the run — marks withheld rather than drawn from a
  /// definition the run never saw.
  driftSuppressed,

  /// The circuit no longer exists, so there is nothing to compare against at all.
  circuitMissing,
}

MarkState markState(NodeCapacities? capacities) {
  if (capacities == null) return MarkState.circuitMissing;
  return capacities.matchesRun ? MarkState.shown : MarkState.driftSuppressed;
}

/// The capacities for panel [index], or null when marks must not be drawn.
///
/// Indexes into the **circuit's** node list only when it matches the run's — otherwise the
/// capacities could land on the wrong panel.
ExternalNode? nodeFor(NodeCapacities? capacities, int index) {
  if (markState(capacities) != MarkState.shown) return null;
  final nodes = capacities!.nodes;
  return index < nodes.length ? nodes[index] : null;
}

/// One node's loads across the revealed part of the run.
List<({double x, double y})> nodeSeries(
  AllocationSeries series,
  int index,
  int step,
) =>
    [
      for (final point in revealUpTo(series.points, (p) => p.stepIndex, step))
        if (index < point.loads.length)
          (x: point.stepIndex.toDouble(), y: point.loads[index]),
    ];

/// Y-bounds for one panel, **always containing that node's marks**.
///
/// A capacity line drawn outside the visible range is indistinguishable from no line, which
/// would quietly turn "this node never approached its limit" into "this node has no limit".
({double min, double max}) panelBounds(
  Iterable<double> loads,
  ExternalNode? node,
) =>
    axisBounds(
      loads,
      AxisScale.linear,
      1,
      extra: node == null ? const [] : [node.loadFactor, node.loadSafetyCap],
    );

/// The largest step index across the series — the scrubber's upper bound.
int lastAllocationStep(AllocationSeries series) {
  var last = 0;
  for (final point in series.points) {
    if (point.stepIndex > last) last = point.stepIndex;
  }
  return last;
}

/// Whether a node's load ever crossed its factor / safety cap in the revealed range.
///
/// Reported as a fact about the loads. The **cost** of a crossing is the circuit engine's, and
/// this layer never re-derives cost.
({bool overFactor, bool overSafetyCap}) crossings(
  List<({double x, double y})> series,
  ExternalNode? node,
) {
  if (node == null) return (overFactor: false, overSafetyCap: false);
  var overFactor = false;
  var overCap = false;
  for (final point in series) {
    if (point.y > node.loadFactor) overFactor = true;
    if (point.y > node.loadSafetyCap) overCap = true;
  }
  return (overFactor: overFactor, overSafetyCap: overCap);
}

/// Human phrasing for a tie count.
///
/// Never "the optimal allocation": ties are a property of the cost surface, and a flat optimum
/// means the search had genuine freedom in where to put the load.
String tieLabel(BestAllocations best) => best.isTied
    ? '${best.allocations.length} allocations reached this cost'
    : 'one allocation reached this cost';

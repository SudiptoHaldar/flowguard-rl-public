/// The circuit as a DAG, with carried load on every node (req_003 v3.07).
///
/// graphview supplies the **layout algorithm and nothing else**. Its `GraphView` widget went
/// blank three times in the browser — laying out at full height while painting no nodes and no
/// edges, once wrapped in a `Row`, once in a `Stack` — and no widget test could see it, because
/// the node widgets existed and reported sensible rectangles throughout. Positions are plain
/// data, so they are computed here and drawn with ordinary Flutter widgets and a `CustomPaint`,
/// which demonstrably paint.
///
/// graphview is imported **with a prefix**: it exports top-level `Node` and `Edge`, which sit
/// alongside our own `TopologyNode` / `TopologyEdge` in this file. Unprefixed, the two
/// vocabularies read as one and a mix-up would be silent.
library;

import 'package:flutter/material.dart';
import 'package:graphview/GraphView.dart' as gv;

import '../api/models.dart';
import 'topology_geometry.dart';

/// A node card's size at zoom 1.
///
/// Height is fixed as well as width, because Sugiyama needs both *before* it runs — the
/// `GraphView` widget used to supply them by measuring its children, and nothing measures them
/// now. Uniform cards also align, which a graph of ragged boxes does not.
const double kNodeCardWidth = 158;
const double kNodeCardHeight = 124;

/// A node's placed rectangle, in graph coordinates.
class PlacedNode {
  const PlacedNode({required this.node, required this.rect});

  final TopologyNode node;
  final Rect rect;
}

/// One edge, placed: where its line runs and where its label sits.
class PlacedEdge {
  const PlacedEdge({required this.edge, required this.from, required this.to});

  final TopologyEdge edge;

  /// Leaves the source's right side and arrives at the target's left: the layout runs
  /// left-to-right, so these are the sides that face each other.
  final Offset from;
  final Offset to;

  Offset get center => (from + to) / 2;

  /// The share of the **source's** load that travels this edge — not a share of the total.
  String get label => '${(edge.weight * 100).round()}%';
}

/// Everything the diagram needs in order to draw itself.
class TopologyLayout {
  const TopologyLayout({
    required this.size,
    required this.nodes,
    required this.edges,
  });

  final Size size;
  final List<PlacedNode> nodes;
  final List<PlacedEdge> edges;
}

/// Runs Sugiyama over the circuit and returns placed nodes and edges.
///
/// Pure: no widgets, no context, no rendering. That is what makes the diagram testable at the
/// geometry level rather than only through a widget tree that cannot tell drawn from undrawn.
TopologyLayout layoutTopology(CircuitTopology topology) {
  final graph = gv.Graph();
  final byName = <String, gv.Node>{
    // Node.Id, never the deprecated Node(data): identity must be the name, not a hashCode.
    for (final node in topology.nodes) node.name: gv.Node.Id(node.name),
  };
  for (final node in byName.values) {
    node.size = const Size(kNodeCardWidth, kNodeCardHeight);
  }
  graph.addNodes(byName.values.toList());
  for (final edge in topology.edges) {
    final source = byName[edge.source];
    final target = byName[edge.target];
    if (source != null && target != null) graph.addEdge(source, target);
  }

  final size = gv.SugiyamaAlgorithm(
    gv.SugiyamaConfiguration()
      ..orientation = gv.SugiyamaConfiguration.ORIENTATION_LEFT_RIGHT
      ..levelSeparation = 90
      ..nodeSeparation = 20,
  ).run(graph, 0, 0);

  final nodes = <PlacedNode>[];
  for (final node in topology.nodes) {
    final laid = byName[node.name];
    if (laid == null) continue;
    nodes.add(PlacedNode(node: node, rect: laid.position & laid.size));
  }

  final edges = <PlacedEdge>[];
  for (final edge in topology.edges) {
    final source = byName[edge.source];
    final target = byName[edge.target];
    if (source == null || target == null) continue;
    edges.add(PlacedEdge(
      edge: edge,
      from: Offset(source.position.dx + source.size.width,
          source.position.dy + source.size.height / 2),
      to: Offset(
          target.position.dx, target.position.dy + target.size.height / 2),
    ));
  }

  return TopologyLayout(size: size, nodes: nodes, edges: edges);
}

class TopologyView extends StatelessWidget {
  const TopologyView({
    super.key,
    required this.topology,
    required this.loads,
    this.zoom = 1,
  });

  /// Scales the whole rendered graph — nodes, gaps, edges and labels together.
  final double zoom;

  final CircuitTopology topology;

  /// Carried load per node name. Empty when the overlay is withheld (drift).
  final Map<String, double> loads;

  @override
  Widget build(BuildContext context) {
    // A flat circuit has no flow to draw, but it does have nodes — and their loads, factors and
    // caps are the whole reason to open this page. Laying them out as a graph would produce one
    // tall column of unconnected cards; a wrap reads as what it is, a set of terminal nodes.
    if (topology.isFlat) return _FlatNodes(topology: topology, loads: loads);

    final layout = layoutTopology(topology);
    final gutter = kNodeCardWidth + 24;

    return Stack(
      children: [
        Padding(
          padding: EdgeInsets.only(left: gutter),
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(vertical: 8),
            // Align's factors report the child's size × zoom and the Transform draws it at
            // that size, so zooming out returns real vertical space rather than shrinking the
            // picture inside a box that stays exactly as tall.
            child: Align(
              alignment: Alignment.topLeft,
              widthFactor: zoom,
              heightFactor: zoom,
              child: Transform.scale(
                scale: zoom,
                alignment: Alignment.topLeft,
                child: SizedBox(
                  width: layout.size.width,
                  height: layout.size.height,
                  child: Stack(
                    children: [
                      // Lines first: the cards sit on top of them, never underneath.
                      CustomPaint(
                        size: layout.size,
                        painter: TopologyEdgePainter(
                          edges: layout.edges,
                          // graphview's own default was black — invisible on the dark
                          // surface. outline is defined per mode and legible in both.
                          color: Theme.of(context).colorScheme.outline,
                        ),
                      ),
                      for (final placed in layout.nodes)
                        Positioned(
                          left: placed.rect.left,
                          top: placed.rect.top,
                          width: placed.rect.width,
                          height: placed.rect.height,
                          child: _NodeCard(
                            node: placed.node,
                            load: loads[placed.node.name],
                          ),
                        ),
                      for (final placed in layout.edges)
                        Positioned(
                          left: placed.center.dx - 22,
                          top: placed.center.dy - 10,
                          child: _EdgeLabelChip(text: placed.label),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
        Positioned(
          left: 0,
          top: 0,
          bottom: 0,
          width: kNodeCardWidth,
          // The card keeps its natural size at every zoom: it is not part of the graph, and a
          // trial's own total is the last thing that should become unreadable.
          child: Center(
            child: _SourceCard(topology: topology, loads: loads),
          ),
        ),
      ],
    );
  }
}

/// A flat circuit's nodes: the same cards, wrapped, with no arrows and no source card.
///
/// The source card is omitted deliberately. On a flat circuit every node carries exactly what
/// it was given, so "assigned this trial" is just the sum of the cards next to it — and the
/// screen already states that in words.
class _FlatNodes extends StatelessWidget {
  const _FlatNodes({required this.topology, required this.loads});

  final CircuitTopology topology;
  final Map<String, double> loads;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 12,
      runSpacing: 12,
      children: [
        for (final node in topology.nodes)
          SizedBox(
            width: kNodeCardWidth,
            height: kNodeCardHeight,
            child: _NodeCard(node: node, load: loads[node.name]),
          ),
      ],
    );
  }
}

/// Draws the connecting lines and their arrowheads.
///
/// Public so a test can read the colour back: "the edges are not black" is exactly the kind of
/// claim that has to be checked rather than assumed here.
class TopologyEdgePainter extends CustomPainter {
  const TopologyEdgePainter({required this.edges, required this.color});

  final List<PlacedEdge> edges;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final line = Paint()
      ..color = color
      ..strokeWidth = 1.5
      ..style = PaintingStyle.stroke;
    final head = Paint()
      ..color = color
      ..style = PaintingStyle.fill;

    for (final edge in edges) {
      canvas.drawLine(edge.from, edge.to, line);

      // A filled triangle at the target end. Direction is not decoration on a DAG: which way
      // the load flows is the thing the picture exists to show.
      final direction = edge.to - edge.from;
      final length = direction.distance;
      if (length < 1) continue;
      final unit = direction / length;
      final normal = Offset(-unit.dy, unit.dx);
      final base = edge.to - unit * 9;
      canvas.drawPath(
        Path()
          ..moveTo(edge.to.dx, edge.to.dy)
          ..lineTo(base.dx + normal.dx * 4, base.dy + normal.dy * 4)
          ..lineTo(base.dx - normal.dx * 4, base.dy - normal.dy * 4)
          ..close(),
        head,
      );
    }
  }

  @override
  bool shouldRepaint(TopologyEdgePainter old) =>
      old.color != color || old.edges != edges;
}

/// The weight, drawn on its own arrow.
///
/// A chip rather than bare text: the label sits on top of the connecting line, and unbacked
/// text over a line is harder to read than either alone.
class _EdgeLabelChip extends StatelessWidget {
  const _EdgeLabelChip({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: theme.colorScheme.outlineVariant),
      ),
      child: Text(text, style: theme.textTheme.labelSmall),
    );
  }
}

/// What this trial put into the circuit: the sum of the external nodes' loads.
///
/// The subject is the **per-trial** total, which moves with the scrubber — not the scenario's
/// requested load, which is a constant and would say nothing about the trial on screen. The
/// requested figure is on the tooltip only, because the two routinely differ by orders of
/// magnitude and a reader who assumes they are the same number would misread every trial.
class _SourceCard extends StatelessWidget {
  const _SourceCard({required this.topology, required this.loads});

  final CircuitTopology topology;
  final Map<String, double> loads;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final assigned = assignedTotal(topology, loads);
    final share = assignedShare(topology, loads);

    return Tooltip(
      message: assigned == null
          ? 'Loads are withheld for this run.'
          : '${assigned.toStringAsFixed(2)} assigned, against a requested '
              '${topology.totalLoad.toStringAsFixed(2)}'
              '${share == null ? '' : ' (${_percent(share)})'}',
      child: Container(
        width: kNodeCardWidth,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: theme.colorScheme.surfaceContainerHigh,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: theme.colorScheme.outlineVariant),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Assigned this trial', style: theme.textTheme.labelSmall),
            Text(
              // Blank, never 0, when no trial is revealed at this position — before the run's
              // first recorded trial, or when drift withholds the loads. "Nothing yet" and
              // "this trial assigned nothing" are different claims and must not share a glyph.
              assigned == null ? '—' : assigned.toStringAsFixed(2),
              style: theme.textTheme.headlineSmall,
            ),
            const SizedBox(height: 6),
            Text(
              assigned == null
                  ? 'no trial recorded here yet'
                  : 'sum of the ${topology.nodes.where((n) => n.isExternal).length} '
                      'external nodes',
              style: theme.textTheme.labelSmall,
            ),
          ],
        ),
      ),
    );
  }

  String _percent(double share) {
    final percent = share * 100;
    return '${percent < 1 ? percent.toStringAsFixed(2) : percent.toStringAsFixed(1)}%';
  }
}

class _NodeCard extends StatelessWidget {
  const _NodeCard({required this.node, required this.load});

  final TopologyNode node;
  final double? load;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final status = classifyNode(load, node);
    final accent = nodeStatusColor(status);

    return Container(
      // Wide enough for the longest name + "external" on one line; the kind is Flexible
      // anyway so an unusually long node name shortens the kind rather than overflowing.
      width: kNodeCardWidth,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: accent, width: 2),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Flexible(
                child: Text(
                  node.name,
                  style: theme.textTheme.titleSmall,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  node.isExternal ? 'external' : 'internal',
                  style: theme.textTheme.labelSmall,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            load == null ? '—' : load!.toStringAsFixed(2),
            style: theme.textTheme.titleMedium,
          ),
          Text(
            'factor ${node.loadFactor.toStringAsFixed(0)} · '
            'cap ${node.loadSafetyCap.toStringAsFixed(0)}',
            style: theme.textTheme.labelSmall,
          ),
          const SizedBox(height: 4),
          // Icon + label always accompany the colour: a status must never rest on hue.
          Row(
            children: [
              Icon(nodeStatusIcon(status), size: 13, color: accent),
              const SizedBox(width: 4),
              Flexible(
                child: Text(
                  statusLabel(status),
                  style: theme.textTheme.labelSmall,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// The edge weights, listed beside the diagram.
///
/// Redundant with the on-arrow labels by design: those shrink with the zoom, and at 50% they
/// are decorative. This list stays readable at every zoom and survives a dense graph where
/// chips would overlap.
class EdgeWeightList extends StatelessWidget {
  const EdgeWeightList({super.key, required this.topology});

  final CircuitTopology topology;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          // Says what the percentage is a share *of*. It is not a share of the total load:
          // a node's outgoing weights need not sum to 1, and reading them as a split would
          // be wrong the moment one does not.
          "Each arrow carries that percentage of its source node's load.",
          style: theme.textTheme.labelSmall,
        ),
        const SizedBox(height: 2),
        Wrap(
          spacing: 16,
          runSpacing: 4,
          children: [
            for (final edge in topology.edges)
              Text(
                '${edge.source} → ${edge.target}  '
                '${(edge.weight * 100).round()}%',
                style: theme.textTheme.labelSmall,
              ),
          ],
        ),
      ],
    );
  }
}

/// Legend for the node states — the vocabulary the cards use.
class NodeStatusLegend extends StatelessWidget {
  const NodeStatusLegend({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    const shown = [
      NodeStatus.underFactor,
      NodeStatus.atFactor,
      NodeStatus.overFactor,
      NodeStatus.atSafetyCap,
      NodeStatus.overSafetyCap,
    ];
    return Wrap(
      spacing: 14,
      runSpacing: 6,
      children: [
        for (final status in shown)
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(nodeStatusIcon(status),
                  size: 13, color: nodeStatusColor(status)),
              const SizedBox(width: 4),
              Text(statusLabel(status), style: theme.textTheme.labelSmall),
            ],
          ),
      ],
    );
  }
}

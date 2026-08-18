/// Where the load flows (req_003 v3.07).
///
/// The allocation panels say what each *external* node was given. This says what that becomes
/// once it propagates: on C4 the binding constraint is not an external node at all but N5, the
/// merge of N1 and N2, sitting exactly on its safety cap.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../api/models.dart';
import '../charts/topology_geometry.dart';
import '../charts/topology_view.dart';
import '../state/providers.dart';
import '../widgets/async_view.dart';
import '../widgets/replay_controls.dart';
import 'app_scaffold.dart';

/// Scrubber sentinel meaning "reveal everything".
const int _showAll = 1 << 30;

class TopologyScreen extends ConsumerStatefulWidget {
  const TopologyScreen({super.key, required this.runId});

  final int runId;

  @override
  ConsumerState<TopologyScreen> createState() => _TopologyScreenState();
}

/// Zoom steps. Discrete rather than continuous: three or four sizes cover the shipped circuits,
/// and a slider invites fiddling with a picture that has one useful size per window.
const List<double> _zoomSteps = [0.5, 0.65, 0.8, 1.0, 1.25];

class _TopologyScreenState extends ConsumerState<TopologyScreen> {
  int _step = _showAll;
  int _zoomIndex = _zoomSteps.indexOf(1.0);

  @override
  Widget build(BuildContext context) {
    final topology = ref.watch(topologyProvider(widget.runId));
    // The run's own identity. Watched separately from the topology so a slow or failed run
    // fetch degrades the heading rather than blanking the diagram.
    final run = ref.watch(runProvider(widget.runId)).value;
    return AppScaffold(
      title: 'Run ${widget.runId} — topology',
      subtitle: 'Where the load flows',
      child: AsyncView<CircuitTopology?>(
        value: topology,
        // The circuit being gone is the only "nothing here" case; flat is a real state.
        isEmpty: (data) => data == null,
        empty: const EmptyState(
          icon: Icons.hub_outlined,
          title: 'This run\'s circuit no longer exists.',
          hint: 'The structure cannot be reconstructed from the run alone.',
        ),
        onRetry: () => ref.invalidate(topologyProvider(widget.runId)),
        builder: (data) => _buildLoaded(data!, run),
      ),
    );
  }

  Widget _buildLoaded(CircuitTopology topology, RunSummary? run) {
    final state = topologyState(topology);
    final last = lastTopologyStep(topology);
    final step = _step == _showAll ? last : _step;
    final loads = loadsAt(topology, step);

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _SummaryCard(topology: topology, state: state, loads: loads),
        const SizedBox(height: 16),
        Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _diagramTitle(topology, run),
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  if (state == TopologyState.flat) ...[
                    const SizedBox(height: 4),
                    // Still named as a state — it is a fact about the circuit, not an absence
                    // of one — but the nodes are drawn either way. A reader who came here to
                    // see where the load sits should not be sent to another page for it.
                    Text(
                      'Every node is terminal: there are no edges, so nothing propagates and '
                      'each node carries exactly what it was given.',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                  const SizedBox(height: 8),
                  const NodeStatusLegend(),
                  if (!topology.isFlat) ...[
                    const SizedBox(height: 8),
                    EdgeWeightList(topology: topology),
                  ],
                  const SizedBox(height: 8),
                  if (!topology.isFlat)
                    _ZoomControls(
                    zoom: _zoomSteps[_zoomIndex],
                    onOut: _zoomIndex == 0
                        ? null
                        : () => setState(() => _zoomIndex -= 1),
                    onIn: _zoomIndex == _zoomSteps.length - 1
                        ? null
                        : () => setState(() => _zoomIndex += 1),
                    onReset: _zoomSteps[_zoomIndex] == 1.0
                        ? null
                        : () => setState(
                            () => _zoomIndex = _zoomSteps.indexOf(1.0)),
                    ),
                  const SizedBox(height: 12),
                  // No fixed height: the diagram takes the height its layout needs and the
                  // page scrolls. Any box here is a guess, and a wrong guess clips the very
                  // node the screen exists to show.
                  TopologyView(
                    topology: topology,
                    loads: loads,
                    zoom: _zoomSteps[_zoomIndex],
                  ),
                  if (state != TopologyState.driftSuppressed)
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
            onPressed: () => context.go('/runs/${widget.runId}/allocations'),
            icon: const Icon(Icons.bar_chart),
            label: const Text('Per-node allocation panels'),
          ),
        ),
      ],
    );
  }
}

/// What the diagram is showing, and — when loads are present — what binds.
class _SummaryCard extends StatelessWidget {
  const _SummaryCard({
    required this.topology,
    required this.state,
    required this.loads,
  });

  final CircuitTopology topology;
  final TopologyState state;
  final Map<String, double> loads;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final atCap = nodesAtSafetyCap(topology, loads);
    final overCap = nodesOverSafetyCap(topology, loads);
    final externals = topology.nodes.where((n) => n.isExternal).length;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(topology.circuitName, style: theme.textTheme.titleLarge),
            Text(
              '${topology.nodes.length} nodes '
              '($externals external, ${topology.nodes.length - externals} internal) · '
              '${topology.edges.length} edges',
              style: theme.textTheme.bodySmall,
            ),
            if (state == TopologyState.driftSuppressed) ...[
              const SizedBox(height: 8),
              Text(
                'The circuit has changed since this run, so the per-node loads are withheld — '
                'propagating them through a graph the run never saw would be worse than '
                'showing none. The structure below is the circuit as it stands today.',
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.error),
              ),
            ],
            // The finding the whole view exists for: what actually binds is often internal.
            //
            // Both lines are always present, saying "none" when they are empty. Showing them
            // only when non-empty made the card change height as the scrubber moved, and the
            // diagram below jumped with it. "None" is also a real answer to the question.
            if (state != TopologyState.driftSuppressed) ...[
              const SizedBox(height: 8),
              _CapLine(label: 'Over safety cap', names: overCap),
              _CapLine(label: 'Exactly at safety cap', names: atCap),
            ],
          ],
        ),
      ),
    );
  }
}

/// The diagram's heading: the scenario, then the run's own identity.
///
/// The grouping keys belong on screen, not just in the run list. A deep link to a topology page
/// is otherwise anonymous — two runs of the same Circuit(Load) under different strategies or
/// modes look identical, and those are precisely the keys this project never pools.
///
/// Degrades to the scenario alone if the run summary has not arrived: a heading that waits for
/// a second request would be worse than one that fills in.
String _diagramTitle(CircuitTopology topology, RunSummary? run) {
  final scenario =
      '${topology.circuitName}(${formatLoad(topology.totalLoad)}) — load flow';
  if (run == null) return scenario;
  final provenance = [
    run.strategyVersion == null
        ? run.strategy
        : '${run.strategy} ${run.strategyVersion}',
    run.observationMode,
    run.allocationMode,
    'seed/budget: ${run.seed ?? '—'} / ${run.budget ?? '—'}',
  ].join(' | ');
  return '$scenario [$provenance]';
}

/// Zoom for the diagram, as buttons.
///
/// Buttons rather than pinch-or-wheel on the diagram itself: an `InteractiveViewer` reads a
/// scroll over the graph as a zoom, so a reader scrolling the *page* magnified the picture
/// instead of moving down it. Zooming out shrinks the node cards and the layout separations,
/// so the diagram gives back real vertical space rather than drawing smaller in the same box.
class _ZoomControls extends StatelessWidget {
  const _ZoomControls({
    required this.zoom,
    required this.onOut,
    required this.onIn,
    required this.onReset,
  });

  final double zoom;
  final VoidCallback? onOut;
  final VoidCallback? onIn;
  final VoidCallback? onReset;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        IconButton(
          tooltip: 'Zoom out',
          onPressed: onOut,
          icon: const Icon(Icons.zoom_out),
        ),
        IconButton(
          tooltip: 'Zoom in',
          onPressed: onIn,
          icon: const Icon(Icons.zoom_in),
        ),
        Text(
          '${(zoom * 100).round()}%',
          // Keyed because an edge weight renders as "80%" too, and a bare text finder cannot
          // tell the zoom readout from an arrow label.
          key: const Key('zoom-readout'),
          style: Theme.of(context).textTheme.labelMedium,
        ),
        const SizedBox(width: 8),
        TextButton(
          onPressed: onReset,
          child: const Text('Reset'),
        ),
      ],
    );
  }
}

/// One line, always exactly one line high.
///
/// Two things would otherwise change the summary card's height as the scrubber moves, and the
/// diagram below jumped with it: the line vanishing when the list is empty, and the list
/// wrapping when early trials put every node over its cap. So it always renders, says "none"
/// rather than nothing, and truncates — with the full list on the tooltip, and every node's own
/// state on its card regardless.
class _CapLine extends StatelessWidget {
  const _CapLine({required this.label, required this.names});

  final String label;
  final List<String> names;

  @override
  Widget build(BuildContext context) {
    final text = names.isEmpty ? 'none' : names.join(', ');
    return Tooltip(
      message: '$label: $text',
      child: Text(
        '$label: $text',
        style: Theme.of(context).textTheme.bodySmall,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
    );
  }
}

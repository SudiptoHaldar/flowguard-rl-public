/// Topology arithmetic and state (req_003 v3.07 D10) — pure, no widgets, no graphview.
///
/// Everything here is a fact about the data, not the drawing: whether the marks may be trusted,
/// whether there is a graph at all, and how a node's carried load sits against its own limits.
library;

import 'package:flutter/material.dart';

import '../api/models.dart';
import '../theme.dart';

/// Whether the circuit's shape can be shown, and with what.
enum TopologyState {
  /// A DAG with edges, and loads that belong to this run.
  loaded,

  /// The circuit has edges but has changed since the run — structure shown, loads withheld.
  driftSuppressed,

  /// No edges at all: every external node is terminal and nothing propagates.
  ///
  /// The **common** case — three of the four shipped circuits are flat — so it is a state to
  /// render, never a failure to load a graph.
  flat,

  /// The circuit no longer exists.
  missing,
}

TopologyState topologyState(CircuitTopology? topology) {
  if (topology == null) return TopologyState.missing;
  if (topology.edges.isEmpty) return TopologyState.flat;
  return topology.matchesRun
      ? TopologyState.loaded
      : TopologyState.driftSuppressed;
}

/// How a node's carried load sits against its own limits.
///
/// "At safety cap" is deliberately separate from "over factor": on C4 the binding constraint is
/// N5 landing *exactly* on 12.0, which would read as merely "high" if the two were merged.
enum NodeStatus { unknown, underFactor, atFactor, overFactor, atSafetyCap, overSafetyCap }

NodeStatus classifyNode(double? load, TopologyNode node) {
  if (load == null) return NodeStatus.unknown;
  if (load > node.loadSafetyCap) return NodeStatus.overSafetyCap;
  if (load == node.loadSafetyCap) return NodeStatus.atSafetyCap;
  if (load > node.loadFactor) return NodeStatus.overFactor;
  if (load == node.loadFactor) return NodeStatus.atFactor;
  return NodeStatus.underFactor;
}

/// Short label for a status. Paired with colour so the state never rests on hue.
String statusLabel(NodeStatus status) => switch (status) {
      NodeStatus.unknown => 'load unavailable',
      NodeStatus.underFactor => 'under factor',
      NodeStatus.atFactor => 'at factor',
      NodeStatus.overFactor => 'over factor',
      NodeStatus.atSafetyCap => 'at safety cap',
      NodeStatus.overSafetyCap => 'over safety cap',
    };

/// The carried loads at or before [step], keyed by node name.
///
/// Empty when the run's loads were withheld — callers then render structure only.
Map<String, double> loadsAt(CircuitTopology topology, int step) {
  CarriedStep? found;
  for (final entry in topology.carried) {
    if (entry.stepIndex <= step) {
      found = entry;
    } else {
      break;
    }
  }
  if (found == null) return const {};
  return {
    for (var i = 0; i < topology.nodes.length && i < found.loads.length; i++)
      topology.nodes[i].name: found.loads[i],
  };
}

/// The largest step index carried — the scrubber's upper bound.
int lastTopologyStep(CircuitTopology topology) {
  var last = 0;
  for (final entry in topology.carried) {
    if (entry.stepIndex > last) last = entry.stepIndex;
  }
  return last;
}

/// Nodes whose load has crossed their safety cap — the ones worth naming in a summary.
List<String> nodesOverSafetyCap(CircuitTopology topology, Map<String, double> loads) => [
      for (final node in topology.nodes)
        if (classifyNode(loads[node.name], node) == NodeStatus.overSafetyCap) node.name,
    ];

/// Nodes sitting exactly on their safety cap — binding constraints, not near-misses.
List<String> nodesAtSafetyCap(CircuitTopology topology, Map<String, double> loads) => [
      for (final node in topology.nodes)
        if (classifyNode(loads[node.name], node) == NodeStatus.atSafetyCap) node.name,
    ];

/// Icon for a node state. Paired with the colour on every card and in the legend, so the
/// state is never carried by hue alone.
IconData nodeStatusIcon(NodeStatus status) => switch (status) {
      NodeStatus.unknown => Icons.help_outline,
      NodeStatus.underFactor => Icons.check_circle_outline,
      NodeStatus.atFactor => Icons.adjust,
      NodeStatus.overFactor => Icons.trending_up,
      NodeStatus.atSafetyCap => Icons.warning_amber_outlined,
      NodeStatus.overSafetyCap => Icons.error_outline,
    };

/// Colour for a node state, from the reserved status palette.
///
/// Mode-invariant by design: every step clears 3:1 on the dark surface and stays legible on the
/// light one, so unlike the series palette there is nothing to re-step.
///
/// Every state gets its **own** colour. Two states sharing one — as under-factor and at-factor
/// briefly did — is a defect, not a shorthand: the icon differs but the colour is what reads
/// first at legend size.
Color nodeStatusColor(NodeStatus status) => switch (status) {
      NodeStatus.unknown => statusUnknown,
      NodeStatus.underFactor => statusGood,
      NodeStatus.atFactor => statusAtLimit,
      NodeStatus.overFactor => statusWarning,
      NodeStatus.atSafetyCap => statusSerious,
      NodeStatus.overSafetyCap => statusCritical,
    };

/// What the trial actually put into the circuit: the sum of the external nodes' loads.
///
/// Every external node's carried load *is* its allocation — nothing flows into it — so this is
/// the trial's assigned total. It is **not** [CircuitTopology.totalLoad]: only `equal_split`
/// allocates exactly the requested load. Returns null when the loads are withheld, so callers
/// show "—" rather than a total of zero.
double? assignedTotal(CircuitTopology topology, Map<String, double> loads) {
  if (loads.isEmpty) return null;
  var sum = 0.0;
  for (final node in topology.nodes) {
    if (node.isExternal) sum += loads[node.name] ?? 0;
  }
  return sum;
}

/// The share of the requested load this trial actually assigned, or null if unanswerable.
double? assignedShare(CircuitTopology topology, Map<String, double> loads) {
  final assigned = assignedTotal(topology, loads);
  if (assigned == null || topology.totalLoad <= 0) return null;
  return assigned / topology.totalLoad;
}

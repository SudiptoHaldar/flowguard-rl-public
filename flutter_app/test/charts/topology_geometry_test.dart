/// Topology state and node classification, tested without a widget tree.
library;

import 'dart:convert';

import 'package:flowguard_dashboard/api/models.dart';
import 'package:flowguard_dashboard/charts/topology_geometry.dart';
import 'package:flowguard_dashboard/charts/topology_view.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers.dart';

CircuitTopology load(String name) =>
    CircuitTopology.fromJson(jsonDecode(fixture(name)) as Map<String, dynamic>);

const _n5 = TopologyNode(
  name: 'N5',
  kind: 'internal',
  loadFactor: 10,
  loadSafetyCap: 12,
);

void main() {
  group('topologyState — four outcomes, kept apart', () {
    test('a DAG whose circuit still matches the run', () {
      expect(topologyState(load('topology_c4.json')), TopologyState.loaded);
    });

    test('an edgeless circuit is flat, not broken', () {
      // Three of the four shipped circuits are flat: the common case.
      expect(topologyState(load('topology_flat.json')), TopologyState.flat);
    });

    test('drift suppresses the loads, not the structure', () {
      final drifted = load('topology_drift.json');
      expect(topologyState(drifted), TopologyState.driftSuppressed);
      expect(drifted.nodes.length, 7);
      expect(drifted.edges.length, 6);
      expect(drifted.carried, isEmpty);
    });

    test('a missing circuit is its own state', () {
      expect(topologyState(null), TopologyState.missing);
    });
  });

  group('classifyNode', () {
    test('separates "at cap" from "over factor" — the binding constraint', () {
      // N5 carries exactly 12.0 at C4's optimum. Merged into "over factor" it would read as
      // merely high; it is in fact the constraint that shapes the whole allocation.
      expect(classifyNode(12.0, _n5), NodeStatus.atSafetyCap);
      expect(classifyNode(11.0, _n5), NodeStatus.overFactor);
      expect(classifyNode(12.5, _n5), NodeStatus.overSafetyCap);
      expect(classifyNode(10.0, _n5), NodeStatus.atFactor);
      expect(classifyNode(5.0, _n5), NodeStatus.underFactor);
    });

    test('an absent load is unknown, never "under factor"', () {
      expect(classifyNode(null, _n5), NodeStatus.unknown);
    });

    test('every status has a distinct label', () {
      final labels = NodeStatus.values.map(statusLabel).toSet();
      expect(labels.length, NodeStatus.values.length);
    });

    test('every status has a distinct colour and icon', () {
      // Regression: under-factor and at-factor both mapped to statusGood. The icons differed,
      // but at legend size the colour reads first, so the two states looked like one.
      final colours = NodeStatus.values.map(nodeStatusColor).toSet();
      expect(colours.length, NodeStatus.values.length);
      final icons = NodeStatus.values.map(nodeStatusIcon).toSet();
      expect(icons.length, NodeStatus.values.length);
    });
  });

  group('carried loads on the real C4 fixture', () {
    test('the propagation reaches the measured figures', () {
      final topology = load('topology_c4.json');
      final loads = loadsAt(topology, lastTopologyStep(topology));

      // Whatever the last retained trial is, the merges must be consistent with the weights.
      expect(loads['N4'], closeTo(loads['N1']! * 0.4, 1e-9));
      expect(loads['N5'],
          closeTo(loads['N1']! * 0.6 + loads['N2']! * 0.7, 1e-9));
      expect(loads['N7'], closeTo(loads['N3']! * 0.2, 1e-9));
    });

    test('internal nodes are the ones that bind', () {
      final topology = load('topology_c4.json');
      final loads = loadsAt(topology, lastTopologyStep(topology));
      final flagged = [
        ...nodesAtSafetyCap(topology, loads),
        ...nodesOverSafetyCap(topology, loads),
      ];
      // Whichever trial the fixture ends on, any capacity pressure is on internal nodes —
      // that is the finding this whole view exists to show.
      for (final name in flagged) {
        expect(topology.nodeNamed(name)!.isExternal, isFalse);
      }
    });

    test('a flat circuit carries exactly what it was given', () {
      final topology = load('topology_flat.json');
      final loads = loadsAt(topology, lastTopologyStep(topology));
      expect(loads.length, topology.nodes.length);
      expect(topology.isFlat, isTrue);
    });

    test('withheld loads yield an empty map, not zeros', () {
      // Zeros would render as "under factor" — a confident, wrong reading.
      expect(loadsAt(load('topology_drift.json'), 999), isEmpty);
    });
  });

  group('assigned total — what the trial actually put in', () {
    test('sums the externals, and it is not the requested load', () {
      final topology = load('topology_c4.json');
      final loads = loadsAt(topology, lastTopologyStep(topology));
      final assigned = assignedTotal(topology, loads)!;

      // Every external node's carried load is its allocation — nothing flows into it.
      expect(
        assigned,
        closeTo(loads['N1']! + loads['N2']! + loads['N3']!, 1e-9),
      );
      // C4's scenario asks for 10000 and the best trial assigns 35. The gap is the finding,
      // which is why the requested figure travels with the topology at all.
      expect(topology.totalLoad, 10000);
      expect(assigned, lessThan(topology.totalLoad));
      expect(assignedShare(topology, loads), closeTo(assigned / 10000, 1e-9));
    });

    test('withheld loads give null, never a total of zero', () {
      // A zero total would read as "this trial assigned nothing", which is a different claim
      // from "we cannot say".
      final drifted = load('topology_drift.json');
      expect(assignedTotal(drifted, loadsAt(drifted, 999)), isNull);
      expect(assignedShare(drifted, loadsAt(drifted, 999)), isNull);
    });

    test('internal nodes are excluded — they are derived, not assigned', () {
      final topology = load('topology_c4.json');
      final loads = loadsAt(topology, lastTopologyStep(topology));
      final everything = loads.values.fold(0.0, (a, b) => a + b);
      expect(assignedTotal(topology, loads)!, lessThan(everything));
    });
  });

  group('node kinds', () {
    test('C4 has three externals feeding four internals', () {
      final topology = load('topology_c4.json');
      expect(topology.nodes.where((n) => n.isExternal).length, 3);
      expect(topology.nodes.where((n) => !n.isExternal).length, 4);
      expect(topology.nodeNamed('N5')!.isExternal, isFalse);
      expect(topology.nodeNamed('N1')!.isExternal, isTrue);
    });
  });


  group('layoutTopology — the diagram as data', () {
    test('places every node and every edge', () {
      final layout = layoutTopology(load('topology_c4.json'));
      expect(layout.nodes, hasLength(7));
      expect(layout.edges, hasLength(6));
      expect(layout.size.width, greaterThan(0));
      expect(layout.size.height, greaterThan(0));
    });

    test('a one-trial run lays out exactly like a long one', () {
      // Run 1090 (equal_split, a single step) drew nothing in the browser while run 1088
      // (random_simplex, 126 steps) drew fine. The structure is identical, and now that is
      // something a test can state rather than something only a screenshot could reveal.
      final many = layoutTopology(load('topology_c4.json'));
      final one = layoutTopology(load('topology_single_step.json'));
      expect(one.size, many.size);
      expect(one.nodes.map((n) => n.rect), many.nodes.map((n) => n.rect));
      expect(one.edges.map((e) => e.from), many.edges.map((e) => e.from));
    });

    test('externals sit left of what they feed, and edges run rightwards', () {
      final layout = layoutTopology(load('topology_c4.json'));
      final byName = {for (final p in layout.nodes) p.node.name: p};
      for (final placed in layout.nodes.where((p) => p.node.isExternal)) {
        expect(placed.rect.left, lessThan(byName['N5']!.rect.left));
      }
      for (final edge in layout.edges) {
        // Left-to-right orientation: an edge that ran backwards would mean the source and
        // target had been swapped somewhere.
        expect(edge.from.dx, lessThan(edge.to.dx));
      }
    });

    test('no two node cards overlap', () {
      final layout = layoutTopology(load('topology_c4.json'));
      for (var i = 0; i < layout.nodes.length; i++) {
        for (var j = i + 1; j < layout.nodes.length; j++) {
          expect(layout.nodes[i].rect.overlaps(layout.nodes[j].rect), isFalse,
              reason: '${layout.nodes[i].node.name} overlaps '
                  '${layout.nodes[j].node.name}');
        }
      }
    });

    test('every label sits between the nodes it joins', () {
      for (final edge in layoutTopology(load('topology_c4.json')).edges) {
        expect(edge.center.dx, greaterThan(edge.from.dx));
        expect(edge.center.dx, lessThan(edge.to.dx));
      }
    });

    test('labels read as a percentage of the source', () {
      final labels = {
        for (final e in layoutTopology(load('topology_c4.json')).edges)
          '${e.edge.source}->${e.edge.target}': e.label,
      };
      expect(labels['N1->N4'], '40%');
      expect(labels['N3->N6'], '80%');
    });

    test('a flat circuit lays out without edges rather than failing', () {
      final layout = layoutTopology(load('topology_flat.json'));
      expect(layout.edges, isEmpty);
      expect(layout.nodes, isNotEmpty);
    });
  });
}

/// The topology screen, through the real router, client and providers.
library;

import 'package:flutter/material.dart';
import 'package:flowguard_dashboard/charts/topology_view.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers.dart';

// Order matters: the transport matches on a path substring, and `/runs/1091/topology`
// contains `runs/1091`, so the more specific paths must be listed first.
Map<String, String> routes({String topology = 'topology_c4.json'}) => {
      '/topology': fixture(topology),
      '/allocations': fixture('allocations.json'),
      '/series': fixture('series.json'),
      'runs/1091': fixture('run.json'),
      '/runs': fixture('runs.json'),
    };

/// The card for [name] — the nearest Column above its title text.
Finder _card(String name) =>
    find.ancestor(of: find.text(name), matching: find.byType(Column)).first;

Finder _cardText(String name, String text) =>
    find.descendant(of: _card(name), matching: find.text(text));

Finder _statusOf(String name) =>
    find.descendant(of: _card(name), matching: find.byType(Icon));

/// The zoom control's readout, by key: an edge weight can render as "80%" too.
String zoomReadout(WidgetTester tester) =>
    tester.widget<Text>(find.byKey(const Key('zoom-readout'))).data!;

void main() {
  group('the heading names the run, not just the circuit', () {
    testWidgets('carries the scenario and every grouping key', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');
      await tester.pumpAndSettle();

      // Two runs of the same Circuit(Load) under different strategies or modes are otherwise
      // indistinguishable on a deep link — and those are the keys this project never pools.
      expect(
        find.text('C4(10,000) — load flow '
            '[hill_climb 1 | opaque | integer | seed/budget: 0 / 160]'),
        findsOneWidget,
      );
    });
  });

  group('expected — a DAG', () {
    testWidgets('draws the graph with a card per node', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      expect(find.text('Run 1091 — topology'), findsOneWidget);
      expect(find.byType(TopologyView), findsOneWidget);
      expect(find.byType(CustomPaint), findsWidgets);
      // 7 nodes, and the header counts them.
      expect(find.textContaining('7 nodes'), findsOneWidget);
      expect(find.textContaining('3 external, 4 internal'), findsOneWidget);
      expect(find.textContaining('6 edges'), findsOneWidget);
    });

    testWidgets('lists the split weights', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      expect(find.byType(EdgeWeightList), findsOneWidget);
      expect(find.textContaining('N1 → N4  40%'), findsOneWidget);
      expect(find.textContaining('N2 → N5  70%'), findsOneWidget);
      // The percentage needs a denominator stated, or it reads as a share of the total.
      expect(find.textContaining("percentage of its source node's load"), findsOneWidget);
    });

    testWidgets('the legend names every state in words', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      expect(find.byType(NodeStatusLegend), findsOneWidget);
      // Colour is never the only channel — each state is spelled out.
      expect(find.text('at safety cap'), findsWidgets);
      expect(find.text('over safety cap'), findsWidgets);
      expect(find.text('under factor'), findsWidgets);
    });

    testWidgets('N5 sits exactly on its cap and N7 is over its own', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      // The finding this whole view exists for: at C4's best allocation the binding node is
      // N5 — a *merge*, not anything the optimizer allocates to directly — and the run
      // knowingly pays a penalty at N7.
      expect(_statusOf('N5'), findsOneWidget);
      expect(_cardText('N5', '12.00'), findsOneWidget);
      expect(_cardText('N5', 'at safety cap'), findsOneWidget);
      expect(_cardText('N7', '3.20'), findsOneWidget);
      expect(_cardText('N7', 'over safety cap'), findsOneWidget);
      // And it is spelled out in prose above the diagram, not left to the eye.
      expect(find.textContaining('Exactly at safety cap: N5'), findsOneWidget);
      expect(find.textContaining('Over safety cap: N7'), findsOneWidget);
    });

    testWidgets('an under-factor node reads as such, with its own icon', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      // N4 carries 5.20 against a factor of 4 and a cap of 7 — over factor, well under cap.
      expect(_cardText('N4', '5.20'), findsOneWidget);
      expect(_cardText('N4', 'over factor'), findsOneWidget);
      // N6 carries 14.60 against a factor of 15: genuinely slack.
      expect(_cardText('N6', 'under factor'), findsOneWidget);
    });
  });

  group('flat circuit', () {
    testWidgets('draws its nodes, and says why there are no arrows', (tester) async {
      useTallSurface(tester);
      await pumpApp(
        tester,
        client: fakeClient(routes(topology: 'topology_flat.json')),
        location: '/runs/1/topology',
      );
      await tester.pumpAndSettle();

      // The nodes and their limits are the reason to open this page. Flat circuits are three
      // of the four shipped ones, so sending that reader to another screen would fail the
      // common case, not an edge case.
      expect(find.byType(TopologyView), findsOneWidget);
      expect(find.text('N1'), findsOneWidget);
      expect(find.text('N2'), findsOneWidget);
      expect(find.textContaining('factor 10 · cap 16'), findsOneWidget);
      expect(find.textContaining('factor 5 · cap 8'), findsOneWidget);

      // Still named as a state — an absence of edges is a fact about the circuit.
      expect(find.textContaining('Every node is terminal'), findsOneWidget);
    });

    testWidgets('draws no arrows, weights or zoom for a graph it does not have',
        (tester) async {
      useTallSurface(tester);
      await pumpApp(
        tester,
        client: fakeClient(routes(topology: 'topology_flat.json')),
        location: '/runs/1/topology',
      );
      await tester.pumpAndSettle();

      final painters = tester
          .widgetList<CustomPaint>(find.descendant(
              of: find.byType(TopologyView), matching: find.byType(CustomPaint)))
          .map((w) => w.painter)
          .whereType<TopologyEdgePainter>();
      expect(painters, isEmpty);
      expect(find.byType(EdgeWeightList), findsNothing);
      // Nothing to pan or scale: the cards wrap to the panel's width.
      expect(find.byTooltip('Zoom out'), findsNothing);
    });
  });

  group('drift', () {
    testWidgets('keeps the structure and withholds the loads', (tester) async {
      useTallSurface(tester);
      await pumpApp(
        tester,
        client: fakeClient(routes(topology: 'topology_drift.json')),
        location: '/runs/1091/topology',
      );

      expect(find.textContaining('circuit has changed since this run'), findsOneWidget);
      // The diagram still stands — it is honestly the circuit's current shape.
      expect(find.byType(TopologyView), findsOneWidget);
      // With no loads, every node card shows a dash rather than a confident zero.
      expect(find.text('—'), findsWidgets);
    });
  });

  group('the source card', () {
    testWidgets("shows the trial's own assigned total", (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      expect(find.text('Assigned this trial'), findsOneWidget);
      // 13 + 6 + 16 at the last retained trial.
      expect(find.text('35.00'), findsOneWidget);
      expect(find.textContaining('sum of the 3 external nodes'), findsOneWidget);
      // The scenario's requested load is a constant and says nothing about this trial, so it
      // is not on the card — only on the tooltip, where it cannot be mistaken for the total.
      expect(find.text('10000.00'), findsNothing);
      expect(find.text('Requested'), findsNothing);
    });

    testWidgets('moves with the scrubber — that is the point', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      expect(find.text('35.00'), findsOneWidget);
      tester.widget<Slider>(find.byType(Slider)).onChanged!(0);
      await tester.pumpAndSettle();

      // Trial 0 is an equal split of 5000 — a different total, which is why a per-trial
      // figure was asked for and a constant would not have answered it.
      expect(find.text('35.00'), findsNothing);
      expect(find.text('5000.00'), findsOneWidget);
    });

    testWidgets('is blank before the run’s first recorded trial', (tester) async {
      useTallSurface(tester);
      await pumpApp(
        tester,
        client: fakeClient(routes(topology: 'topology_late_start.json')),
        location: '/runs/1091/topology',
      );

      // This run's first retained trial is step 5, so slider positions 0-4 precede every
      // trial there is. A number there would be describing a trial that has not happened.
      tester.widget<Slider>(find.byType(Slider)).onChanged!(0);
      await tester.pumpAndSettle();

      expect(find.text('—'), findsWidgets);
      expect(find.text('0.00'), findsNothing);
      expect(find.textContaining('no trial recorded here yet'), findsOneWidget);
      expect(find.textContaining('sum of the 3 external nodes'), findsNothing);

      // And it fills in the moment a trial exists.
      tester.widget<Slider>(find.byType(Slider)).onChanged!(5);
      await tester.pumpAndSettle();
      expect(find.textContaining('no trial recorded here yet'), findsNothing);
    });

    testWidgets('stays put when the diagram is panned', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      final before = tester.getRect(find.text('Assigned this trial'));
      await tester.drag(
          find.byType(SingleChildScrollView).last, const Offset(-200, 0));
      await tester.pumpAndSettle();
      // The card is outside the scroller: panning a wide circuit must not scroll the trial's
      // own total off the screen.
      expect(tester.getRect(find.text('Assigned this trial')), before);
    });

    testWidgets('withholds the total under drift rather than showing zero', (tester) async {
      useTallSurface(tester);
      await pumpApp(
        tester,
        client: fakeClient(routes(topology: 'topology_drift.json')),
        location: '/runs/1091/topology',
      );

      expect(find.text('Assigned this trial'), findsOneWidget);
      expect(find.text('0.00'), findsNothing);
    });
  });

  group('the summary card keeps a constant height', () {
    testWidgets('both cap lines are always present, saying "none" when empty',
        (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      // Everything below the summary card must not move when the scrubber does.
      final before = tester.getTopLeft(find.byType(NodeStatusLegend));
      expect(find.textContaining('Over safety cap: N7'), findsOneWidget);
      expect(find.textContaining('Exactly at safety cap: N5'), findsOneWidget);

      // Rewind to trial 0, where the search is far out and nothing sits *exactly* on a cap.
      final slider = tester.widget<Slider>(find.byType(Slider));
      slider.onChanged!(0);
      await tester.pumpAndSettle();

      // The line stays — it just answers "none". Dropping it changed the card's height and
      // the diagram below jumped every time the scrubber crossed a boundary.
      expect(find.textContaining('Exactly at safety cap: none'), findsOneWidget);
      expect(find.textContaining('Over safety cap: N1'), findsOneWidget);
      expect(tester.getTopLeft(find.byType(NodeStatusLegend)), before);
    });

    testWidgets('each cap line is pinned to one line', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      // The other way the card could change height: early trials put all seven nodes over
      // their caps, and a wrapped list is a taller card. Truncation keeps it one line; the
      // full list is on the tooltip, and each node states its own status on its card.
      for (final label in ['Over safety cap', 'Exactly at safety cap']) {
        final line = tester.widget<Text>(
            find.textContaining('$label: ', findRichText: false));
        expect(line.maxLines, 1);
        expect(line.overflow, TextOverflow.ellipsis);
      }
    });
  });

  group('the diagram does not fight the page', () {
    testWidgets('scrolls horizontally rather than zooming', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      // Regression: an InteractiveViewer treats a scroll over the diagram as a zoom, so a
      // reader scrolling the page magnified the graph instead of moving down it.
      expect(find.byType(InteractiveViewer), findsNothing);
      final scroller = find.descendant(
        of: find.byType(TopologyView),
        matching: find.byType(SingleChildScrollView),
      );
      expect(scroller, findsOneWidget);
      expect(tester.widget<SingleChildScrollView>(scroller).scrollDirection,
          Axis.horizontal);
    });

    testWidgets('takes its natural height — nothing is clipped', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      // All four ranks' worth of nodes are laid out, not just those a fixed box would fit.
      for (final name in ['N1', 'N2', 'N3', 'N4', 'N5', 'N6', 'N7']) {
        expect(find.text(name), findsOneWidget, reason: '$name should be laid out');
      }
      expect(tester.getSize(find.byType(TopologyView)).height, greaterThan(300));
    });
  });

  group('zoom', () {
    testWidgets('zooming out gives back real vertical space', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      expect(zoomReadout(tester), '100%');
      final before = tester.getSize(find.byType(TopologyView)).height;

      await tester.tap(find.byTooltip('Zoom out'));
      await tester.pumpAndSettle();

      // Not a Transform over the same box: the layout itself must shrink, which is the
      // complaint the control exists to answer.
      expect(zoomReadout(tester), '80%');
      expect(tester.getSize(find.byType(TopologyView)).height, lessThan(before));

      // And every node is still there — zooming out must not cost information.
      for (final name in ['N1', 'N2', 'N3', 'N4', 'N5', 'N6', 'N7']) {
        expect(find.text(name), findsOneWidget);
      }
    });

    testWidgets('packs the nodes closer, and keeps them inside the panel',
        (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      double gap() =>
          tester.getRect(find.text('N2')).top - tester.getRect(find.text('N1')).top;
      double overflow() =>
          tester.getRect(find.text('N7')).bottom -
          tester.getRect(find.byType(TopologyView)).bottom;

      final gapAt100 = gap();
      expect(overflow(), lessThan(0));

      await tester.tap(find.byTooltip('Zoom out'));
      await tester.pumpAndSettle();

      // Shrinking the cards alone was not enough: graphview kept its 140px node gap and
      // 248px level gap whatever the config said, so the panel shrank while the nodes stayed
      // where they were and spilled past its edge. The gap must shrink with the zoom.
      expect(gap(), lessThan(gapAt100));
      expect(overflow(), lessThan(0));

      await tester.tap(find.byTooltip('Zoom out'));
      await tester.pumpAndSettle();
      expect(gap(), lessThan(gapAt100 * 0.75));
      expect(overflow(), lessThan(0));
    });

    testWidgets('reset returns to 100% and is disabled there', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      expect(tester.widget<TextButton>(find.widgetWithText(TextButton, 'Reset'))
          .onPressed, isNull);
      await tester.tap(find.byTooltip('Zoom out'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(TextButton, 'Reset'));
      await tester.pumpAndSettle();
      expect(zoomReadout(tester), '100%');
    });
  });

  group('edges', () {
    testWidgets('every arrow is labelled with its weight as a percentage',
        (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');
      // Labels need graphview's laid-out node positions, so they arrive a frame late.
      await tester.pumpAndSettle();

      // C4's six weights: 0.4, 0.6, 0.7, 0.3, 0.8, 0.2.
      for (final pct in ['40%', '60%', '70%', '30%', '80%', '20%']) {
        // On the arrow itself. The list beside the diagram renders the same figure inside a
        // longer string ("N1 → N4  40%"), so it is not a second exact-text match.
        expect(
          find.descendant(
              of: find.byType(TopologyView), matching: find.text(pct)),
          findsOneWidget,
          reason: '$pct should be on its arrow',
        );
      }
    });

    testWidgets('each label sits between the nodes it joins', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');
      await tester.pumpAndSettle();

      // N1 → N4 carries 0.4. Its chip must fall in the gap between the two cards, not at the
      // origin — which is where it would land if positions were read before layout ran.
      final chip = tester.getRect(find.text('40%').last);
      final n1 = tester.getRect(find.text('N1'));
      final n4 = tester.getRect(find.text('N4'));
      expect(chip.left, greaterThan(n1.left));
      expect(chip.left, lessThan(n4.left));
    });

    testWidgets('are drawn in theme ink, not the default black', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');

      final painter = tester
          .widgetList<CustomPaint>(find.descendant(
              of: find.byType(TopologyView), matching: find.byType(CustomPaint)))
          .map((w) => w.painter)
          .whereType<TopologyEdgePainter>()
          .single;
      final scheme =
          Theme.of(tester.element(find.byType(TopologyView))).colorScheme;
      // graphview's default was black, all but invisible on the dark surface.
      expect(painter.color.toARGB32(), scheme.outline.toARGB32());
      expect(painter.color.toARGB32(), isNot(0xFF000000));
      expect(painter.edges, hasLength(6));
    });
  });

  group('navigation', () {
    testWidgets('links back to the allocation panels', (tester) async {
      useTallSurface(tester);
      await pumpApp(tester,
          client: fakeClient(routes()), location: '/runs/1091/topology');
      expect(find.text('Per-node allocation panels'), findsOneWidget);
    });
  });
}

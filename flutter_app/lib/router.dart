/// Routes for the chart app (req_003 v3.03 D3).
///
/// Paths mirror the API so the two are read together, which makes a run bookmarkable and
/// shareable — most of what deep linking buys on a web-first dashboard.
///
/// **URL strategy**: Flutter web's default hash strategy is kept, so a run is
/// `http://host:port/#/runs/1091`. Clean paths would need `usePathUrlStrategy()` from
/// `package:flutter_web_plugins`, which is web-only — importing it unconditionally breaks the
/// non-web targets, and it needs SPA rewrite support when served for real. Deep linking works
/// either way; this costs nothing.
library;

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import 'screens/allocation_screen.dart';
import 'screens/app_scaffold.dart';
import 'screens/comparison_screen.dart';
import 'screens/run_detail_screen.dart';
import 'screens/runs_screen.dart';
import 'screens/topology_screen.dart';
import 'screens/scenarios_screen.dart';
import 'widgets/async_view.dart';

/// [initialLocation] exists so tests can start at a deep link — the same entry point a pasted
/// URL uses, rather than a simulated navigation.
GoRouter buildRouter({String initialLocation = '/'}) => GoRouter(
      initialLocation: initialLocation,
      routes: [
        GoRoute(
          path: '/',
          builder: (context, state) => const ScenariosScreen(),
        ),
        GoRoute(
          path: '/runs',
          builder: (context, state) => const RunsScreen(),
        ),
        GoRoute(
          path: '/runs/:runId',
          builder: (context, state) {
            final raw = state.pathParameters['runId'];
            final runId = int.tryParse(raw ?? '');
            // A malformed id is a bad route, not a crash mid-build.
            if (runId == null) return NotFoundScreen(uri: state.uri);
            return RunDetailScreen(runId: runId);
          },
        ),
        GoRoute(
          path: '/runs/:runId/allocations',
          builder: (context, state) {
            final runId = int.tryParse(state.pathParameters['runId'] ?? '');
            if (runId == null) return NotFoundScreen(uri: state.uri);
            return AllocationScreen(runId: runId);
          },
        ),
        GoRoute(
          path: '/runs/:runId/topology',
          builder: (context, state) {
            final runId = int.tryParse(state.pathParameters['runId'] ?? '');
            if (runId == null) return NotFoundScreen(uri: state.uri);
            return TopologyScreen(runId: runId);
          },
        ),
        GoRoute(
          path: '/comparison',
          builder: (context, state) => const ComparisonScreen(),
        ),
      ],
      errorBuilder: (context, state) => NotFoundScreen(uri: state.uri),
    );

class NotFoundScreen extends StatelessWidget {
  const NotFoundScreen({super.key, required this.uri});

  final Uri uri;

  @override
  Widget build(BuildContext context) {
    return AppScaffold(
      title: 'Not found',
      child: EmptyState(
        icon: Icons.wrong_location_outlined,
        title: 'No screen for "$uri".',
        hint: 'Try the scenario list.',
        onRetry: () => GoRouter.of(context).go('/'),
      ),
    );
  }
}

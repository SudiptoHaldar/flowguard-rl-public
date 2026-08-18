/// Riverpod providers for the chart app (req_003 v3.03 D2).
///
/// No code generation: plain `Provider` / `FutureProvider` / `NotifierProvider`.
///
/// Note `NotifierProvider` rather than `StateProvider` for the selection — Riverpod 3 moved
/// `StateProvider` and `StateNotifierProvider` to `package:flutter_riverpod/legacy.dart`, and
/// this app stays on the current API.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';

/// The API client. Tests replace it with
/// `ProviderScope(overrides: [clientProvider.overrideWith((ref) => fake)])`.
final clientProvider = Provider<FlowGuardClient>((ref) => FlowGuardClient());

/// Which population the run list is showing.
///
/// [strategy] exists because a comparison-matrix cell carries **no run id** — it is an
/// aggregate over a population (one run for a deterministic strategy, five for
/// `random_simplex`). Tapping a cell therefore narrows this selection to that population and
/// shows its runs, rather than guessing which single run to open.
class Selection {
  const Selection({this.circuitName, this.totalLoad, this.strategy});

  final String? circuitName;
  final double? totalLoad;
  final String? strategy;

  bool get isEmpty => circuitName == null;

  String get label {
    if (circuitName == null) return 'All runs';
    final scenario = '$circuitName at L=${totalLoad?.toStringAsFixed(0) ?? '?'}';
    return strategy == null ? scenario : '$scenario · $strategy';
  }
}

class SelectionNotifier extends Notifier<Selection> {
  @override
  Selection build() => const Selection();

  void pick(String circuitName, double totalLoad, {String? strategy}) => state =
      Selection(circuitName: circuitName, totalLoad: totalLoad, strategy: strategy);

  void clear() => state = const Selection();
}

final selectionProvider =
    NotifierProvider<SelectionNotifier, Selection>(SelectionNotifier.new);

/// Scenario picker feed.
final scenariosProvider = FutureProvider<List<ScenarioRef>>(
  (ref) => ref.watch(clientProvider).scenarios(),
);

/// Run list for the current selection. Re-fetches when the selection changes.
final runsProvider = FutureProvider<RunPage>((ref) {
  final selection = ref.watch(selectionProvider);
  return ref.watch(clientProvider).runs(
        circuitName: selection.circuitName,
        totalLoad: selection.totalLoad,
        strategy: selection.strategy,
      );
});

/// One run's header.
final runProvider = FutureProvider.family<RunSummary, int>(
  (ref, runId) => ref.watch(clientProvider).run(runId),
);

/// One run's replay series. `maxPoints` is left to the server default.
final runSeriesProvider = FutureProvider.family<RunSeries, int>(
  (ref, runId) => ref.watch(clientProvider).series(runId),
);

/// One run's per-node allocations, thinned with the same keep set as its series.
final allocationsProvider = FutureProvider.family<AllocationSeries, int>(
  (ref, runId) => ref.watch(clientProvider).allocations(runId),
);

/// The run's circuit topology with per-step carried loads.
final topologyProvider = FutureProvider.family<CircuitTopology?, int>(
  (ref, runId) => ref.watch(clientProvider).topology(runId),
);

/// Completed runs for one Circuit(Load) — the overlay picker's candidates.
///
/// Keyed by a record so the family caches per scenario rather than per widget build.
final scenarioRunsProvider =
    FutureProvider.family<RunPage, ({String circuit, double load})>(
  (ref, key) => ref.watch(clientProvider).runs(
        circuitName: key.circuit,
        totalLoad: key.load,
      ),
);

/// The comparison grid for the newest benchmark invocation.
final comparisonProvider = FutureProvider<ComparisonResponse>(
  (ref) => ref.watch(clientProvider).comparison(),
);

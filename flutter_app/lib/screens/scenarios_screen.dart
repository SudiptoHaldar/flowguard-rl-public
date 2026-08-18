/// Scenario picker: every Circuit(Load) problem with at least one completed run.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../api/models.dart';
import '../state/providers.dart';
import '../widgets/async_view.dart';
import 'app_scaffold.dart';

class ScenariosScreen extends ConsumerWidget {
  const ScenariosScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scenarios = ref.watch(scenariosProvider);
    return AppScaffold(
      title: 'Scenarios',
      subtitle: 'Circuit(Load) problems with completed runs',
      child: AsyncView<List<ScenarioRef>>(
        value: scenarios,
        isEmpty: (data) => data.isEmpty,
        empty: const EmptyState(
          icon: Icons.inbox_outlined,
          title: 'No completed runs yet.',
          hint: 'Produce one with:  python -m flowguard.rl optimize C4 10000',
        ),
        onRetry: () => ref.invalidate(scenariosProvider),
        builder: (data) => DataTableCard(
          columns: const [
            DataColumn(label: Text('Circuit')),
            DataColumn(label: Text('Total load'), numeric: true),
            DataColumn(label: Text('Runs'), numeric: true),
            DataColumn(label: Text('Best cost'), numeric: true),
          ],
          rows: [
            for (final scenario in data)
              DataRow(
                onSelectChanged: (_) {
                  ref
                      .read(selectionProvider.notifier)
                      .pick(scenario.circuitName, scenario.totalLoad);
                  context.go('/runs');
                },
                cells: [
                  DataCell(Text(scenario.circuitName)),
                  DataCell(Text(scenario.totalLoad.toStringAsFixed(0))),
                  DataCell(Text('${scenario.runCount}')),
                  DataCell(Text(formatCost(scenario.bestCost))),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

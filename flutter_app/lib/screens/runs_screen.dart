/// Run list for the selected scenario.
///
/// The grouping keys (strategy + version, modes, cold/warm start) are columns rather than
/// hidden detail: they are what every comparison depends on, and a run list that hides them
/// invites exactly the pooling the server refuses to do.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../api/models.dart';
import '../state/providers.dart';
import '../widgets/async_view.dart';
import 'app_scaffold.dart';

class RunsScreen extends ConsumerWidget {
  const RunsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final runs = ref.watch(runsProvider);
    final selection = ref.watch(selectionProvider);
    return AppScaffold(
      title: 'Runs',
      subtitle: selection.label,
      child: AsyncView<RunPage>(
        value: runs,
        isEmpty: (page) => page.items.isEmpty,
        empty: EmptyState(
          icon: Icons.inbox_outlined,
          title: 'No completed runs for ${selection.label}.',
          hint: 'Failed and abandoned runs are never charted — '
              'find them with:  python -m flowguard.rl runs',
        ),
        onRetry: () => ref.invalidate(runsProvider),
        builder: (page) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
              child: Text(
                'Showing ${page.items.length} of ${page.total} completed runs',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
            Expanded(
              child: DataTableCard(
                columns: const [
                  DataColumn(label: Text('Run')),
                  DataColumn(label: Text('Strategy')),
                  DataColumn(label: Text('Seed'), numeric: true),
                  DataColumn(label: Text('Trials'), numeric: true),
                  DataColumn(label: Text('First cost'), numeric: true),
                  DataColumn(label: Text('Best cost'), numeric: true),
                  DataColumn(label: Text('Improvement'), numeric: true),
                  DataColumn(label: Text('Modes')),
                ],
                rows: [
                  for (final run in page.items)
                    DataRow(
                      onSelectChanged: (_) => context.go('/runs/${run.runId}'),
                      cells: [
                        DataCell(Text('${run.runId}')),
                        DataCell(Text(run.strategyVersion == null
                            ? run.strategy
                            : '${run.strategy} ${run.strategyVersion}')),
                        DataCell(Text(run.seed?.toString() ?? '—')),
                        DataCell(Text('${run.trialsUsed}')),
                        DataCell(Text(formatCost(run.firstCost))),
                        DataCell(Text(formatCost(run.bestCost))),
                        DataCell(Text(
                            '${(run.improvement * 100).toStringAsFixed(1)}%')),
                        DataCell(Text('${run.allocationMode} · '
                            '${run.observationMode} · '
                            '${run.coldStart ? 'cold' : 'warm'}')),
                      ],
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

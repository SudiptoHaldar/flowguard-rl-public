/// Algorithm comparison across circuits and loads (req_003 v3.05).
///
/// A scenario × strategy matrix coloured by regret against the scenario optimum, with the value
/// printed in every cell. Below it: the degenerate baseline as raw cost, and the provenance
/// that makes a reported number re-checkable.
///
/// The discipline this view inherits: incomparable populations are never pooled, so the
/// grouping keys are facets rather than hidden; and an absent measurement is stated rather than
/// drawn as zero, which in this metric would read as *optimal*.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../api/models.dart';
import '../charts/comparison_matrix.dart';
import '../charts/matrix_geometry.dart';
import '../state/providers.dart';
import '../widgets/async_view.dart';
import '../widgets/facet_controls.dart';
import 'app_scaffold.dart';

class ComparisonScreen extends ConsumerStatefulWidget {
  const ComparisonScreen({super.key});

  @override
  ConsumerState<ComparisonScreen> createState() => _ComparisonScreenState();
}

class _ComparisonScreenState extends ConsumerState<ComparisonScreen> {
  FacetSelection? _facets;

  @override
  Widget build(BuildContext context) {
    final comparison = ref.watch(comparisonProvider);
    return AppScaffold(
      title: 'Comparison',
      subtitle: 'Algorithms across circuits and loads',
      child: AsyncView<ComparisonResponse>(
        value: comparison,
        // `available: false` is an empty corpus, not a failure — a 200 with nothing in it.
        isEmpty: (data) => !data.available || data.cells.isEmpty,
        empty: const EmptyState(
          icon: Icons.grid_off,
          title: 'No benchmark has been run yet.',
          hint: 'Produce one with:  python -m flowguard.rl benchmark',
        ),
        onRetry: () => ref.invalidate(comparisonProvider),
        builder: _buildLoaded,
      ),
    );
  }

  Widget _buildLoaded(ComparisonResponse data) {
    final facets = _facets ?? FacetSelection.initial(data.cells)!;
    final population = [
      for (final cell in data.cells)
        if (facets.matches(cell)) cell,
    ];
    final degenerate = degenerateCells(population);

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (data.benchmark != null) _ProvenanceCard(header: data.benchmark!),
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: FacetControls(
              cells: data.cells,
              selection: facets,
              onChanged: (value) => setState(() => _facets = value),
            ),
          ),
        ),
        const SizedBox(height: 16),
        _MatrixCard(
          cells: population,
          onCellTap: (row, column) {
            // A cell is an aggregate with no run id, so narrow to its population and show
            // the runs behind it.
            ref
                .read(selectionProvider.notifier)
                .pick(row.circuit, row.load, strategy: column.strategy);
            context.go('/runs');
          },
        ),
        const SizedBox(height: 16),
        if (degenerate.isNotEmpty) _DegenerateCard(cells: degenerate),
      ],
    );
  }
}

class _MatrixCard extends StatelessWidget {
  const _MatrixCard({required this.cells, required this.onCellTap});

  final List<ComparisonCell> cells;
  final void Function(ScenarioKey, StrategyKey) onCellTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final warning = mixedFacetWarning(cells);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Regret against the scenario optimum',
                style: theme.textTheme.titleMedium),
            const SizedBox(height: 4),
            Text(
              'Lower is better; 0% means the strategy found the optimum. '
              'Rows are one circuit at ascending loads, so scaling reads down the column.',
              style: theme.textTheme.bodySmall,
            ),
            if (warning != null) ...[
              const SizedBox(height: 8),
              Text(warning, style: theme.textTheme.bodySmall),
            ],
            const SizedBox(height: 12),
            const RegretLegend(),
            const SizedBox(height: 16),
            ComparisonMatrix(cells: cells, onCellTap: onCellTap),
          ],
        ),
      ),
    );
  }
}

/// The degenerate baseline, shown as **raw cost**.
///
/// Its regret runs to 5.6e18 % — not a number anyone reads, and printing it as a percentage
/// would imply it belongs on the same axis as 25%. It is shown rather than hidden because it is
/// a real measurement of what happens with no search at all.
class _DegenerateCard extends StatelessWidget {
  const _DegenerateCard({required this.cells});

  final List<ComparisonCell> cells;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final name = cells.first.strategy;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('$name — outside the comparison',
                style: theme.textTheme.titleMedium),
            const SizedBox(height: 4),
            Text(
              'Disposes the whole load in one cycle with no search. Its costs are shown raw: '
              'as a regret percentage they reach ~1e18%, which would flatten every other cell '
              'on the colour scale. Excluded from all aggregates.',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: DataTable(
                columns: const [
                  DataColumn(label: Text('Scenario')),
                  DataColumn(label: Text('Cost'), numeric: true),
                  DataColumn(label: Text('Optimum'), numeric: true),
                ],
                rows: [
                  for (final cell in cells)
                    DataRow(cells: [
                      DataCell(Text(
                          '${cell.circuitName} @ ${cell.totalLoad.toStringAsFixed(0)}')),
                      DataCell(Text(formatCost(cell.bestCostMedian))),
                      DataCell(Text(formatCost(cell.optimum))),
                    ]),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// What makes a reported number re-checkable months later.
class _ProvenanceCard extends StatelessWidget {
  const _ProvenanceCard({required this.header});

  final BenchmarkHeader header;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      color: theme.colorScheme.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Wrap(
          spacing: 24,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text('Catalog ${header.catalogName} v${header.catalogVersion}',
                style: theme.textTheme.titleSmall),
            Text('benchmark ${header.benchmarkId}',
                style: theme.textTheme.bodySmall),
            Text('${header.nSeeds} seeds per stochastic strategy',
                style: theme.textTheme.bodySmall),
            Text('enumeration cap ${header.enumerationCap}',
                style: theme.textTheme.bodySmall),
            Text(
              'optimum_method: enumerated = proven; best_observed = the best anyone has '
              'recorded, and cells measured against it are marked',
              style: theme.textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}

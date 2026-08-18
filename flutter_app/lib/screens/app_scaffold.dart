/// Shared chrome for every screen: title, backend status chip, and top-level navigation.
library;

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../widgets/backend_status_chip.dart';

class AppScaffold extends StatelessWidget {
  const AppScaffold({
    super.key,
    required this.title,
    required this.child,
    this.subtitle,
    this.actions,
  });

  final String title;
  final String? subtitle;
  final Widget child;
  final List<Widget>? actions;

  @override
  Widget build(BuildContext context) {
    final canPop = GoRouter.of(context).canPop();
    return Scaffold(
      appBar: AppBar(
        leading: canPop
            ? IconButton(
                icon: const Icon(Icons.arrow_back),
                onPressed: () => GoRouter.of(context).pop(),
                tooltip: 'Back',
              )
            : null,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(title),
            if (subtitle != null)
              Text(subtitle!, style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
        actions: [
          ...?actions,
          TextButton.icon(
            onPressed: () => context.go('/'),
            icon: const Icon(Icons.list_alt),
            label: const Text('Scenarios'),
          ),
          TextButton.icon(
            onPressed: () => context.go('/comparison'),
            icon: const Icon(Icons.grid_on),
            label: const Text('Comparison'),
          ),
          const BackendStatusChip(),
        ],
      ),
      body: child,
    );
  }
}

/// A horizontally scrollable table — every screen in v3.03 renders one.
class DataTableCard extends StatelessWidget {
  const DataTableCard({super.key, required this.columns, required this.rows});

  final List<DataColumn> columns;
  final List<DataRow> rows;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Card(
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: DataTable(columns: columns, rows: rows),
        ),
      ),
    );
  }
}

/// Formats a cost that may span 1e0 to 1e20 (`equal_split` reaches the top of that range).
String formatCost(double? value) {
  if (value == null) return '—';
  if (value.abs() >= 1e6 || (value != 0 && value.abs() < 1e-3)) {
    return value.toStringAsExponential(4);
  }
  return value.toStringAsFixed(4);
}

/// A load, with thousands grouped: `10000.0` reads as `10,000`.
///
/// Scenario loads run from 60 to 20000, and an ungrouped `20000` beside a cost is easy to
/// misread by an order of magnitude. Fractional loads keep two decimals rather than being
/// rounded into looking exact.
String formatLoad(double value) {
  final whole = value.truncate();
  final grouped = whole
      .abs()
      .toString()
      .replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},');
  final sign = value < 0 ? '-' : '';
  if (value == whole) return '$sign$grouped';
  final fraction = (value.abs() - whole.abs()).toStringAsFixed(2).substring(1);
  return '$sign$grouped$fraction';
}

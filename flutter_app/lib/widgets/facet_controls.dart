/// Grouping-key facets for the comparison matrix (req_003 v3.05 D5).
///
/// The rest of the stack refuses to pool incomparable populations; this is where that refusal
/// becomes visible. The view shows **one population at a time and says which**, rather than
/// showing everything and leaving the reader to notice.
library;

import 'package:flutter/material.dart';

import '../api/models.dart';
import '../charts/matrix_geometry.dart';

/// The population currently on screen.
class FacetSelection {
  const FacetSelection({
    required this.observationMode,
    required this.allocationMode,
    required this.coldStart,
  });

  final String observationMode;
  final String allocationMode;
  final bool coldStart;

  bool matches(ComparisonCell cell) =>
      cell.observationMode == observationMode &&
      cell.allocationMode == allocationMode &&
      cell.coldStart == coldStart;

  String get label => '$allocationMode · $observationMode · '
      '${coldStart ? 'cold-started' : 'warm-started'}';

  /// The default population: the first of each facet in a stable order, so the view opens on
  /// one comparable set rather than on everything.
  static FacetSelection? initial(List<ComparisonCell> cells) {
    if (cells.isEmpty) return null;
    final facets = facetsIn(cells);
    return FacetSelection(
      observationMode: (facets.observationModes.toList()..sort()).first,
      allocationMode: (facets.allocationModes.toList()..sort()).first,
      coldStart: (facets.coldStarts.toList()..sort((a, b) => a == b ? 0 : (a ? -1 : 1)))
          .first,
    );
  }
}

class FacetControls extends StatelessWidget {
  const FacetControls({
    super.key,
    required this.cells,
    required this.selection,
    required this.onChanged,
  });

  final List<ComparisonCell> cells;
  final FacetSelection selection;
  final ValueChanged<FacetSelection> onChanged;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final facets = facetsIn(cells);
    final hasChoice = facets.observationModes.length > 1 ||
        facets.allocationModes.length > 1 ||
        facets.coldStarts.length > 1;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Showing: ${selection.label}',
          style: theme.textTheme.labelLarge,
        ),
        if (!hasChoice)
          Text(
            'The corpus contains only this population.',
            style: theme.textTheme.labelSmall,
          )
        else ...[
          const SizedBox(height: 8),
          Wrap(
            spacing: 16,
            runSpacing: 8,
            children: [
              if (facets.allocationModes.length > 1)
                _Choice<String>(
                  label: 'allocation',
                  values: facets.allocationModes.toList()..sort(),
                  value: selection.allocationMode,
                  display: (v) => v,
                  onChanged: (v) => onChanged(FacetSelection(
                    observationMode: selection.observationMode,
                    allocationMode: v,
                    coldStart: selection.coldStart,
                  )),
                ),
              if (facets.observationModes.length > 1)
                _Choice<String>(
                  label: 'observation',
                  values: facets.observationModes.toList()..sort(),
                  value: selection.observationMode,
                  display: (v) => v,
                  onChanged: (v) => onChanged(FacetSelection(
                    observationMode: v,
                    allocationMode: selection.allocationMode,
                    coldStart: selection.coldStart,
                  )),
                ),
              if (facets.coldStarts.length > 1)
                _Choice<bool>(
                  label: 'start',
                  values: facets.coldStarts.toList()
                    ..sort((a, b) => a == b ? 0 : (a ? -1 : 1)),
                  value: selection.coldStart,
                  display: (v) => v ? 'cold' : 'warm',
                  onChanged: (v) => onChanged(FacetSelection(
                    observationMode: selection.observationMode,
                    allocationMode: selection.allocationMode,
                    coldStart: v,
                  )),
                ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            'These are never pooled — an enhanced run beside an opaque one, or a warm start '
            'beside a cold one, would overstate what the strategy achieved.',
            style: theme.textTheme.labelSmall,
          ),
        ],
      ],
    );
  }
}

class _Choice<T> extends StatelessWidget {
  const _Choice({
    required this.label,
    required this.values,
    required this.value,
    required this.display,
    required this.onChanged,
  });

  final String label;
  final List<T> values;
  final T value;
  final String Function(T) display;
  final ValueChanged<T> onChanged;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text('$label ', style: Theme.of(context).textTheme.labelSmall),
        const SizedBox(width: 4),
        SegmentedButton<T>(
          segments: [
            for (final option in values)
              ButtonSegment(value: option, label: Text(display(option))),
          ],
          selected: {value},
          onSelectionChanged: (selected) => onChanged(selected.first),
          showSelectedIcon: false,
        ),
      ],
    );
  }
}

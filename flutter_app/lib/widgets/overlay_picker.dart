/// Chooses which runs of the same Circuit(Load) are overlaid (req_003 v3.04 D5).
///
/// Candidates come from the same scenario only. The cap is [maxOverlaySeries] — the validated
/// length of the categorical palette, not a round number — and it is stated in the UI rather
/// than silently dropping a run the user asked for.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/models.dart';
import '../state/providers.dart';
import '../theme.dart';

class OverlayPicker extends ConsumerWidget {
  const OverlayPicker({
    super.key,
    required this.focused,
    required this.overlaid,
    required this.onToggle,
  });

  final RunSummary focused;

  /// Run ids overlaid on top of [focused], in the order they were added.
  final List<int> overlaid;
  final ValueChanged<int> onToggle;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final candidates = ref.watch(scenarioRunsProvider(
      (circuit: focused.circuitName, load: focused.totalLoad),
    ));

    return candidates.when(
      loading: () => const SizedBox(height: 32),
      error: (error, stack) => Text(
        'Could not load other runs for this scenario.',
        style: theme.textTheme.bodySmall,
      ),
      data: (page) {
        final others = page.items.where((r) => r.runId != focused.runId).toList();
        if (others.isEmpty) {
          return Text(
            'No other completed runs for ${focused.circuitName} '
            'at L=${focused.totalLoad.toStringAsFixed(0)}.',
            style: theme.textTheme.bodySmall,
          );
        }
        // One slot is taken by the focused run itself.
        final full = overlaid.length >= maxOverlaySeries - 1;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text('Overlay', style: theme.textTheme.titleSmall),
                const SizedBox(width: 8),
                Text(
                  '${overlaid.length + 1} of $maxOverlaySeries series'
                  '${full ? ' — palette limit reached' : ''}',
                  style: theme.textTheme.labelSmall,
                ),
              ],
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final run in others)
                  FilterChip(
                    selected: overlaid.contains(run.runId),
                    // A disabled chip still shows why: the cap is the palette's validated
                    // length, so exceeding it would put two indistinguishable hues on screen.
                    onSelected: (!overlaid.contains(run.runId) && full)
                        ? null
                        : (_) => onToggle(run.runId),
                    label: Text('${run.runId} · ${run.groupingLabel}'),
                  ),
              ],
            ),
          ],
        );
      },
    );
  }
}

/// Shown when an overlay spans populations the rest of the stack refuses to compare.
class MixedPopulationNotice extends StatelessWidget {
  const MixedPopulationNotice({super.key, required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: theme.colorScheme.errorContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Icon(Icons.warning_amber_outlined,
              size: 18, color: theme.colorScheme.onErrorContainer),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.onErrorContainer),
            ),
          ),
        ],
      ),
    );
  }
}

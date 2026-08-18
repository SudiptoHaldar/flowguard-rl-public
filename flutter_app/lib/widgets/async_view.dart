/// The single place an [AsyncValue] becomes UI (req_003 v3.03 D6).
///
/// Loading, empty, error and not-chartable are four distinct states, and a spinner covering all
/// of them is the failure this widget exists to prevent. Centralising the switch means a screen
/// cannot quietly collapse them, and `AsyncValue` being a sealed class makes the switch
/// exhaustive — the analyzer refuses to let a state be forgotten.
///
/// [isEmpty] is required rather than optional on purpose: every screen has to *say* what empty
/// means for its data, instead of falling through to a data view rendering nothing.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';

class AsyncView<T> extends StatelessWidget {
  const AsyncView({
    super.key,
    required this.value,
    required this.isEmpty,
    required this.empty,
    required this.builder,
    this.onRetry,
  });

  final AsyncValue<T> value;
  final bool Function(T data) isEmpty;
  final Widget empty;
  final Widget Function(T data) builder;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) => switch (value) {
        AsyncLoading<T>() => const Center(child: CircularProgressIndicator()),
        AsyncError<T>(:final error) => FailureView(error: error, onRetry: onRetry),
        AsyncData<T>(:final value) =>
          isEmpty(value) ? empty : builder(value),
      };
}

/// Renders an [ApiFailure] as a message a person can act on.
class FailureView extends StatelessWidget {
  const FailureView({super.key, required this.error, this.onRetry});

  final Object error;
  final VoidCallback? onRetry;

  ({String title, String? hint, IconData icon}) get _content => switch (error) {
        // A partial run is not "not found" — say what it is, and where it CAN be inspected.
        // The dashboard deliberately never shows partial runs; the CLI is where they live.
        ApiNotFound(reason: 'run_not_chartable', :final status) => (
            title: 'This run did not complete (${status ?? 'unknown'}).',
            hint: 'Inspect it with:  python -m flowguard.rl show <id> --trace',
            icon: Icons.report_gmailerrorred_outlined,
          ),
        ApiNotFound(reason: 'unknown_run') => (
            title: 'No such run.',
            hint: 'It may have been deleted.',
            icon: Icons.search_off,
          ),
        ApiNotFound(reason: 'unknown_benchmark') => (
            title: 'No such benchmark.',
            hint: null,
            icon: Icons.search_off,
          ),
        ApiUnavailable() => (
            title: 'The database is unavailable.',
            hint: 'Check that PostgreSQL is running, then retry.',
            icon: Icons.storage,
          ),
        ApiUnreachable() => (
            title: 'API unreachable.',
            hint: 'Is the backend running on port 8100?',
            icon: Icons.cloud_off,
          ),
        ApiInvalid(:final message) => (
            title: 'The request was rejected.',
            hint: message,
            icon: Icons.rule,
          ),
        _ => (
            title: 'Something went wrong.',
            hint: '$error',
            icon: Icons.error_outline,
          ),
      };

  @override
  Widget build(BuildContext context) {
    final content = _content;
    return EmptyState(
      icon: content.icon,
      title: content.title,
      hint: content.hint,
      onRetry: onRetry,
    );
  }
}

/// Shared presentation for "nothing here" and "it went wrong" — never a blank pane, and never
/// a zero standing in for absent data.
class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    this.hint,
    this.onRetry,
  });

  final IconData icon;
  final String title;
  final String? hint;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 48, color: theme.colorScheme.outline),
            const SizedBox(height: 16),
            Text(title, style: theme.textTheme.titleMedium, textAlign: TextAlign.center),
            if (hint != null) ...[
              const SizedBox(height: 8),
              SelectableText(
                hint!,
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.outline),
                textAlign: TextAlign.center,
              ),
            ],
            if (onRetry != null) ...[
              const SizedBox(height: 16),
              FilledButton.tonalIcon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('Retry'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

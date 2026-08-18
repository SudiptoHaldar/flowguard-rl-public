import 'package:flowguard_dashboard/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  // --- edge: both themes are Material 3 and derive from the sage seed ---
  test('light theme is Material 3 with sage-seeded color scheme', () {
    final theme = lightTheme();
    expect(theme.useMaterial3, isTrue);
    expect(theme.colorScheme.brightness, Brightness.light);
    expect(theme.colorScheme.primary,
        ColorScheme.fromSeed(seedColor: sageSeed).primary);
  });

  test('dark theme is Material 3 with sage-seeded color scheme', () {
    final theme = darkTheme();
    expect(theme.useMaterial3, isTrue);
    expect(theme.colorScheme.brightness, Brightness.dark);
    expect(
        theme.colorScheme.primary,
        ColorScheme.fromSeed(seedColor: sageSeed, brightness: Brightness.dark)
            .primary);
  });
}

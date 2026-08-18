import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'router.dart';
import 'theme.dart';

void main() {
  runApp(const ProviderScope(child: FlowGuardApp()));
}

class FlowGuardApp extends StatefulWidget {
  const FlowGuardApp({super.key});

  @override
  State<FlowGuardApp> createState() => _FlowGuardAppState();
}

class _FlowGuardAppState extends State<FlowGuardApp> {
  // Built once: a GoRouter rebuilt on every frame would reset navigation state.
  late final _router = buildRouter();

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: 'FlowGuard Dashboard',
      // The dashboard is read over someone's shoulder as often as it is developed on, and the
      // banner covers the top-right of every screen. Nothing else about debug mode changes.
      debugShowCheckedModeBanner: false,
      theme: lightTheme(),
      darkTheme: darkTheme(),
      themeMode: ThemeMode.system,
      routerConfig: _router,
    );
  }
}

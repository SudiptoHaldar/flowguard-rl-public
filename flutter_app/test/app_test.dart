/// The real app widget — the one `main()` runs, which the screen tests bypass.
library;

import 'package:flowguard_dashboard/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('does not wear the debug banner', (tester) async {
    await tester.pumpWidget(const ProviderScope(child: FlowGuardApp()));

    // The screen tests build their own MaterialApp, so nothing else covers this: the banner
    // could come back unnoticed. It sits over the top-right of every screen in debug builds,
    // and this dashboard is read as often as it is developed on.
    final app = tester.widget<MaterialApp>(find.byType(MaterialApp));
    expect(app.debugShowCheckedModeBanner, isFalse);
  });
}

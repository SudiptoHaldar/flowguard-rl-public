/// Backend status chip — the three cases carried over from the retired dashboard screen.
library;

import 'package:flowguard_dashboard/widgets/backend_status_chip.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Future<void> pumpChip(WidgetTester tester, http.Client client) async {
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(appBar: AppBar(actions: [BackendStatusChip(client: client)])),
  ));
  await tester.pumpAndSettle();
}

void main() {
  // --- expected ---

  testWidgets('shows the version when the API answers', (tester) async {
    final client = MockClient((request) async =>
        http.Response('{"status": "ok", "version": "1.0.0"}', 200));
    await pumpChip(tester, client);
    expect(find.text('API v1.0.0 connected'), findsOneWidget);
  });

  // --- failure ---

  testWidgets('shows unreachable when the API is down', (tester) async {
    final client = MockClient((request) async => http.Response('', 500));
    await pumpChip(tester, client);
    expect(find.text('API unreachable'), findsOneWidget);
  });

  // --- edge ---

  testWidgets('retry recovers after the API comes back', (tester) async {
    var healthy = false;
    final client = MockClient((request) async => healthy
        ? http.Response('{"status": "ok", "version": "1.0.0"}', 200)
        : http.Response('', 500));

    await pumpChip(tester, client);
    expect(find.text('API unreachable'), findsOneWidget);

    healthy = true;
    await tester.tap(find.byType(ActionChip));
    await tester.pumpAndSettle();
    expect(find.text('API v1.0.0 connected'), findsOneWidget);
  });
}

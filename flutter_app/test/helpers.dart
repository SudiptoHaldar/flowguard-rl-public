/// Shared test scaffolding.
///
/// Screens are pumped through the **real** router and the **real** client, with only the HTTP
/// transport faked. That means a test exercises routing, provider wiring, JSON parsing and the
/// widget together — the composition is where mistakes actually live — while still needing no
/// backend and no database.
library;

import 'dart:io';

import 'package:flowguard_dashboard/api/client.dart';
import 'package:flowguard_dashboard/router.dart';
import 'package:flowguard_dashboard/state/providers.dart';
import 'package:flowguard_dashboard/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// Reads a captured API response. These are real bodies from a live server, so a server-side
/// shape change fails a model test rather than a screen.
String fixture(String name) =>
    File('test/fixtures/$name').readAsStringSync();

/// A client whose transport answers from [routes], keyed by a substring of the request path.
///
/// Anything unmatched returns 404 `unknown_run`, which keeps an unrelated call from silently
/// succeeding with the wrong body.
FlowGuardClient fakeClient(Map<String, String> routes, {int status = 200}) {
  return FlowGuardClient(
    baseUrl: 'http://test',
    client: MockClient((request) async {
      for (final entry in routes.entries) {
        if (request.url.path.contains(entry.key)) {
          return http.Response(entry.value, status,
              headers: {'content-type': 'application/json'});
        }
      }
      return http.Response(
        '{"detail": {"reason": "unknown_run", "run_id": 0}}',
        404,
        headers: {'content-type': 'application/json'},
      );
    }),
  );
}

/// A client whose every request fails with the given status and body.
FlowGuardClient failingClient(int status, String body) => FlowGuardClient(
      baseUrl: 'http://test',
      client: MockClient((request) async => http.Response(body, status,
          headers: {'content-type': 'application/json'})),
    );

/// A client whose transport never answers — the backend is not running.
FlowGuardClient unreachableClient() => FlowGuardClient(
      baseUrl: 'http://test',
      client: MockClient((request) async => throw const SocketException('down')),
    );

/// Gives the test a tall viewport for the rest of the case.
///
/// The default 800x600 surface is shorter than the run-detail page, and a `ListView` only
/// builds what is visible — so widgets below the fold are absent from the tree and a finder
/// reports "not found" for something that is merely off-screen.
void useTallSurface(WidgetTester tester, {Size size = const Size(1400, 2600)}) {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

/// Pumps the real app at [location] with [client] injected.
Future<void> pumpApp(
  WidgetTester tester, {
  required FlowGuardClient client,
  String location = '/',
}) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [clientProvider.overrideWith((ref) => client)],
      child: MaterialApp.router(
        theme: lightTheme(),
        // The real router, started at [location] — the same entry point a pasted deep link
        // uses, so routing is exercised rather than bypassed.
        routerConfig: buildRouter(initialLocation: location),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

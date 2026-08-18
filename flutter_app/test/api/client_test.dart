/// The client's job is to turn status codes into typed failures, so no widget parses HTTP.
library;

import 'package:flowguard_dashboard/api/client.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers.dart';

void main() {
  group('expected', () {
    test('200 becomes a parsed model', () async {
      final client = fakeClient({'/series': fixture('series.json')});
      final series = await client.series(1091);
      expect(series.run.runId, 1091);
      expect(series.points.last.bestSoFar, closeTo(299.1856, 1e-6));
    });

    test('a top-level array endpoint parses', () async {
      final client = fakeClient({'/scenarios': fixture('scenarios.json')});
      expect(await client.scenarios(), isNotEmpty);
    });

    test('query parameters are only sent when set', () async {
      // maxPoints omitted -> the server default applies; a literal "null" would 422.
      final client = fakeClient({'/series': fixture('series.json')});
      await expectLater(client.series(1091), completes);
      await expectLater(client.series(1091, maxPoints: 12), completes);
    });
  });

  group('failure — the typed vocabulary', () {
    test('404 run_not_chartable carries the run status', () async {
      final client = failingClient(404,
          '{"detail": {"reason": "run_not_chartable", "run_id": 9, "status": "failed"}}');
      await expectLater(
        client.series(9),
        throwsA(isA<ApiNotFound>()
            .having((e) => e.reason, 'reason', 'run_not_chartable')
            .having((e) => e.status, 'status', 'failed')
            .having((e) => e.runId, 'runId', 9)),
      );
    });

    test('404 unknown_run', () async {
      final client = failingClient(
          404, '{"detail": {"reason": "unknown_run", "run_id": 999}}');
      await expectLater(
        client.run(999),
        throwsA(isA<ApiNotFound>()
            .having((e) => e.reason, 'reason', 'unknown_run')
            .having((e) => e.status, 'status', isNull)),
      );
    });

    test('404 unknown_benchmark', () async {
      final client = failingClient(404,
          '{"detail": {"reason": "unknown_benchmark", "benchmark_id": 77}}');
      await expectLater(
        client.comparison(benchmarkId: 77),
        throwsA(isA<ApiNotFound>()
            .having((e) => e.reason, 'reason', 'unknown_benchmark')
            .having((e) => e.benchmarkId, 'benchmarkId', 77)),
      );
    });

    test('503 becomes ApiUnavailable', () async {
      final client = failingClient(
          503, '{"status": "unavailable", "detail": "OperationalError"}');
      await expectLater(client.scenarios(), throwsA(isA<ApiUnavailable>()));
    });

    test('422 becomes ApiInvalid carrying the server message', () async {
      final client = failingClient(
          422, '{"detail": "max_points must be between 1 and 20000, got 99999"}');
      await expectLater(
        client.series(1, maxPoints: 99999),
        throwsA(isA<ApiInvalid>()
            .having((e) => e.message, 'message', contains('max_points'))),
      );
    });

    test('a dead socket becomes ApiUnreachable', () async {
      await expectLater(
          unreachableClient().scenarios(), throwsA(isA<ApiUnreachable>()));
    });

    test('an unparseable error body still fails cleanly', () async {
      final client = failingClient(500, '<html>gateway</html>');
      await expectLater(client.scenarios(), throwsA(isA<ApiInvalid>()));
    });
  });
}

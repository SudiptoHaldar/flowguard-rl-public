/// HTTP client for the flowguard-rl chart API (req_003 v3.03 D5).
///
/// The client is the **only** place that knows about status codes. It converts them into typed
/// failures so no widget parses a response — the client-side mirror of the server's typed
/// exceptions (v3.02 D5), and for the same reason: dispatching on a parsed reason is stable,
/// matching on strings is not.
///
/// `client` is injectable so widget tests run with no backend, matching the pattern the shell
/// established in v0.04.
library;

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config.dart';
import 'models.dart';

/// Base class for every failure the API can produce. Sealed so callers can switch
/// exhaustively over the cases they handle.
sealed class ApiFailure implements Exception {
  const ApiFailure();
}

/// A 404. [reason] is the machine-readable code the server sends —
/// `unknown_run`, `run_not_chartable` or `unknown_benchmark`.
///
/// A partial run is deliberately a 404 with `run_not_chartable`: it is not a chart resource,
/// but the reason survives so the UI can say *why* rather than "not found".
class ApiNotFound extends ApiFailure {
  const ApiNotFound(this.reason, {this.runId, this.status, this.benchmarkId});

  final String reason;
  final int? runId;

  /// The run's terminal status (`failed` / `abandoned`) when [reason] is `run_not_chartable`.
  final String? status;
  final int? benchmarkId;

  @override
  String toString() => 'ApiNotFound($reason)';
}

/// A 422 — a parameter outside the server's configured bounds.
class ApiInvalid extends ApiFailure {
  const ApiInvalid(this.message);

  final String message;

  @override
  String toString() => 'ApiInvalid($message)';
}

/// A 503 — the API is up but its database is not.
class ApiUnavailable extends ApiFailure {
  const ApiUnavailable();

  @override
  String toString() => 'ApiUnavailable()';
}

/// No answer at all: the backend is not running, or the network failed.
class ApiUnreachable extends ApiFailure {
  const ApiUnreachable();

  @override
  String toString() => 'ApiUnreachable()';
}

class FlowGuardClient {
  FlowGuardClient({http.Client? client, this.baseUrl = apiBaseUrl})
      : _client = client ?? http.Client();

  /// The only occurrence of the API prefix in `lib/`; the base URL lives in `config.dart`.
  static const String _prefix = '/api/v1';

  final http.Client _client;
  final String baseUrl;

  Uri _uri(String path, [Map<String, dynamic>? query]) {
    final params = <String, String>{};
    query?.forEach((key, value) {
      if (value != null) params[key] = '$value';
    });
    return Uri.parse('$baseUrl$_prefix$path')
        .replace(queryParameters: params.isEmpty ? null : params);
  }

  /// Performs the request and turns anything other than 200 into an [ApiFailure].
  Future<dynamic> _get(String path, [Map<String, dynamic>? query]) async {
    final http.Response response;
    try {
      response = await _client.get(_uri(path, query));
    } on Exception {
      throw const ApiUnreachable();
    }
    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }
    if (response.statusCode == 503) {
      throw const ApiUnavailable();
    }
    Object? detail;
    try {
      detail = (jsonDecode(response.body) as Map<String, dynamic>)['detail'];
    } on FormatException {
      detail = null;
    }
    if (response.statusCode == 404 && detail is Map<String, dynamic>) {
      throw ApiNotFound(
        detail['reason'] as String,
        runId: detail['run_id'] as int?,
        status: detail['status'] as String?,
        benchmarkId: detail['benchmark_id'] as int?,
      );
    }
    throw ApiInvalid(
      detail is String ? detail : 'HTTP ${response.statusCode}',
    );
  }

  Future<Map<String, dynamic>> _getObject(String path,
          [Map<String, dynamic>? query]) async =>
      await _get(path, query) as Map<String, dynamic>;

  Future<List<dynamic>> _getList(String path,
          [Map<String, dynamic>? query]) async =>
      await _get(path, query) as List<dynamic>;

  /// Every Circuit(Load) problem with at least one completed run.
  Future<List<ScenarioRef>> scenarios() async =>
      (await _getList('/scenarios'))
          .map((e) => ScenarioRef.fromJson(e as Map<String, dynamic>))
          .toList();

  /// Completed runs, newest first. Bounds on `limit` are enforced server-side.
  Future<RunPage> runs({
    String? circuitName,
    double? totalLoad,
    String? strategy,
    int? limit,
    int? offset,
  }) async =>
      RunPage.fromJson(await _getObject('/runs', {
        'circuit_name': circuitName,
        'total_load': totalLoad,
        'strategy': strategy,
        'limit': limit,
        'offset': offset,
      }));

  Future<RunSummary> run(int runId) async =>
      RunSummary.fromJson(await _getObject('/runs/$runId'));

  /// Cost vs trial with the best-so-far envelope. Omitting [maxPoints] takes the server default.
  Future<RunSeries> series(int runId, {int? maxPoints}) async =>
      RunSeries.fromJson(
          await _getObject('/runs/$runId/series', {'max_points': maxPoints}));

  Future<AllocationSeries> allocations(int runId, {int? maxPoints}) async =>
      AllocationSeries.fromJson(await _getObject(
          '/runs/$runId/allocations', {'max_points': maxPoints}));

  /// The run's circuit as a graph, with per-node carried load. Null when the circuit is gone.
  Future<CircuitTopology?> topology(int runId, {int? maxPoints}) async {
    final body = await _get('/runs/$runId/topology', {'max_points': maxPoints});
    return body == null
        ? null
        : CircuitTopology.fromJson(body as Map<String, dynamic>);
  }

  Future<List<BenchmarkHeader>> benchmarks() async =>
      (await _getList('/benchmarks'))
          .map((e) => BenchmarkHeader.fromJson(e as Map<String, dynamic>))
          .toList();

  /// The comparison grid. Omitting [benchmarkId] selects the newest invocation.
  Future<ComparisonResponse> comparison({int? benchmarkId}) async =>
      ComparisonResponse.fromJson(
          await _getObject('/comparison', {'benchmark_id': benchmarkId}));
}

/// Backend liveness chip for the app bar (req_003 v3.03 D7).
///
/// Lifted out of the v0.04 placeholder `DashboardScreen`, which the four real screens replace.
/// The behaviour is unchanged — one probe of `/health` on load, manual retry, injectable
/// `http.Client` so widget tests need no backend.
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../config.dart';

enum BackendStatus { checking, connected, unreachable }

class BackendStatusChip extends StatefulWidget {
  /// [client] is injectable for tests; defaults to a real HTTP client.
  const BackendStatusChip({super.key, this.client});

  final http.Client? client;

  @override
  State<BackendStatusChip> createState() => _BackendStatusChipState();
}

class _BackendStatusChipState extends State<BackendStatusChip> {
  BackendStatus _status = BackendStatus.checking;
  String _version = '';

  @override
  void initState() {
    super.initState();
    _checkHealth();
  }

  /// One-shot health probe — no polling; tapping the chip retries.
  Future<void> _checkHealth() async {
    setState(() => _status = BackendStatus.checking);
    final client = widget.client ?? http.Client();
    try {
      final response = await client.get(Uri.parse('$apiBaseUrl/health'));
      if (response.statusCode != 200) throw http.ClientException('not ok');
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _version = body['version'] as String? ?? '?';
        _status = BackendStatus.connected;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _status = BackendStatus.unreachable);
    } finally {
      if (widget.client == null) client.close();
    }
  }

  String get _label => switch (_status) {
        BackendStatus.checking => 'Checking API…',
        BackendStatus.connected => 'API v$_version connected',
        BackendStatus.unreachable => 'API unreachable',
      };

  IconData get _icon => switch (_status) {
        BackendStatus.checking => Icons.hourglass_empty,
        BackendStatus.connected => Icons.check_circle_outline,
        BackendStatus.unreachable => Icons.cloud_off,
      };

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      child: ActionChip(
        avatar: Icon(_icon, size: 18),
        label: Text(_label),
        tooltip: 'Retry',
        onPressed: _checkHealth,
      ),
    );
  }
}

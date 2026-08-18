/// Replay transport for the progress chart (req_003 v3.04 D4).
///
/// Replay is client-side over the already-fetched series: the run is complete, the points are
/// in memory, and "replay a completed run" is exactly what the RL group's 2026-08-16 decision
/// described. There is no streaming and no live tail.
///
/// The slider runs on **trial index**, not normalised progress — with runs of different lengths
/// overlaid, normalising would make two runs look like they took the same effort.
library;

import 'dart:async';

import 'package:flutter/material.dart';

class ReplayControls extends StatefulWidget {
  const ReplayControls({
    super.key,
    required this.lastStep,
    required this.step,
    required this.onStepChanged,
  });

  final int lastStep;
  final int step;
  final ValueChanged<int> onStepChanged;

  @override
  State<ReplayControls> createState() => _ReplayControlsState();
}

class _ReplayControlsState extends State<ReplayControls> {
  Timer? _timer;
  double _speed = 1;

  static const List<double> _speeds = [0.5, 1, 2, 4];

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  bool get _playing => _timer != null;

  void _toggle() {
    if (_playing) {
      _stop();
      return;
    }
    // Restart from the beginning when play is pressed at the end.
    if (widget.step >= widget.lastStep) widget.onStepChanged(0);
    setState(() {
      _timer = Timer.periodic(
        Duration(milliseconds: (60 / _speed).round()),
        (_) {
          final next = widget.step + 1;
          if (next > widget.lastStep) {
            _stop();
          } else {
            widget.onStepChanged(next);
          }
        },
      );
    });
  }

  void _stop() {
    _timer?.cancel();
    if (mounted) setState(() => _timer = null);
  }

  void _setSpeed(double speed) {
    setState(() => _speed = speed);
    if (_playing) {
      _stop();
      _toggle();
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      children: [
        IconButton(
          onPressed: widget.lastStep == 0 ? null : _toggle,
          icon: Icon(_playing ? Icons.pause : Icons.play_arrow),
          tooltip: _playing ? 'Pause' : 'Play',
        ),
        IconButton(
          onPressed: () {
            _stop();
            widget.onStepChanged(widget.lastStep);
          },
          icon: const Icon(Icons.skip_next),
          tooltip: 'Show all trials',
        ),
        Expanded(
          child: Slider(
            value: widget.step.clamp(0, widget.lastStep).toDouble(),
            max: widget.lastStep.toDouble().clamp(1, double.infinity),
            divisions: widget.lastStep > 0 ? widget.lastStep : null,
            label: 'trial ${widget.step}',
            onChanged: (value) {
              _stop();
              widget.onStepChanged(value.round());
            },
          ),
        ),
        Text('trial ${widget.step} / ${widget.lastStep}',
            style: theme.textTheme.labelMedium),
        const SizedBox(width: 12),
        DropdownButton<double>(
          value: _speed,
          underline: const SizedBox.shrink(),
          onChanged: (value) => value == null ? null : _setSpeed(value),
          items: [
            for (final speed in _speeds)
              DropdownMenuItem(value: speed, child: Text('${speed}x')),
          ],
        ),
      ],
    );
  }
}

/// Pure chart arithmetic (req_003 v3.04 D10) — no widgets, no fl_chart.
///
/// This is where the mistakes would live, so it lives where it can be tested without a widget
/// tree. **fl_chart has no logarithmic scale**, so the log axis is hand-rolled here: values are
/// plotted as `log10(cost)` and inverted for axis labels and tooltips.
///
/// The one rule that matters: **everything reaching the chart goes through [toAxis]** — spots,
/// the y-range, and every reference line. Mixing transformed and untransformed values puts the
/// optimum line in the wrong place while still looking entirely plausible.
library;

import 'dart:math' as math;

import '../api/models.dart';

enum AxisScale { log, linear }

/// Fallback floor when a series contains no positive cost at all.
const double _absoluteFloor = 1e-9;

/// Smallest positive cost across [costs] — the clamp floor for the log axis.
///
/// A cost of exactly zero would make `log10` return negative infinity and blank the chart.
/// Costs are penalties and are non-negative in every shipped circuit, but "non-negative"
/// includes zero, so this is a real case rather than a defensive one.
double axisFloor(Iterable<double> costs) {
  double? smallest;
  for (final cost in costs) {
    if (cost > 0 && (smallest == null || cost < smallest)) smallest = cost;
  }
  return smallest ?? _absoluteFloor;
}

/// True when any cost in [costs] had to be clamped to be plotted on a log axis.
bool needsClamping(Iterable<double> costs, AxisScale scale) =>
    scale == AxisScale.log && costs.any((c) => c <= 0);

/// Cost → axis value. The single transform (see the library docstring).
double toAxis(double cost, AxisScale scale, double floor) => scale == AxisScale.linear
    ? cost
    : math.log(math.max(cost, floor)) / math.ln10;

/// Axis value → cost. Used by axis labels and tooltips, which must never show log values.
double fromAxis(double value, AxisScale scale) =>
    scale == AxisScale.linear ? value : math.pow(10, value).toDouble();

/// Trials revealed at scrubber position [step] — the prefix with `stepIndex <= step`.
///
/// Cheap slicing over already-parsed points: the scrubber runs at animation rate, so this must
/// not re-parse or re-map anything.
List<T> revealUpTo<T>(List<T> points, int Function(T) stepOf, int step) =>
    points.where((point) => stepOf(point) <= step).toList(growable: false);

/// Which run a chart bar belongs to, and which of its two marks it is.
///
/// Every run contributes exactly two bars in order — the trial cloud then its envelope — so
/// the bar index decodes back to the run. Tooltips need this: without it both marks report the
/// same trial number and the reader cannot tell the trial's own cost from the best-so-far.
({int runIndex, bool isEnvelope}) barRole(int barIndex) =>
    (runIndex: barIndex ~/ 2, isEnvelope: barIndex.isOdd);

/// What a chart bar is called in a tooltip.
///
/// The envelope is the line to follow and the cloud is the search around it, so the two are
/// named rather than left to be inferred from their magnitudes.
String barLabel(int barIndex) =>
    barRole(barIndex).isEnvelope ? 'best so far' : 'trial cost';

/// True when the run never improved after its first trial.
///
/// A flat envelope is a real result — `equal_split` produces exactly one trial — and gets a
/// stated note rather than a chart that merely looks broken.
bool neverImproved(List<SeriesPoint> points) =>
    points.where((point) => point.isBest).length <= 1;

/// The last step index in [series], or 0 when empty. The scrubber's upper bound.
int lastStep(List<RunSeries> series) {
  var last = 0;
  for (final run in series) {
    for (final point in run.points) {
      if (point.stepIndex > last) last = point.stepIndex;
    }
  }
  return last;
}

/// Y-axis bounds for the given scale, padded so reference lines are never clipped.
///
/// [extra] carries the reference values (optimum, best-of-random) — they participate in the
/// range, because a reference line drawn outside the visible window is worse than none: the
/// viewer sees a chart with no target and no indication one exists.
({double min, double max}) axisBounds(
  Iterable<double> costs,
  AxisScale scale,
  double floor, {
  Iterable<double> extra = const [],
}) {
  final values = [
    ...costs.map((c) => toAxis(c, scale, floor)),
    ...extra.map((c) => toAxis(c, scale, floor)),
  ];
  if (values.isEmpty) return (min: 0, max: 1);
  var low = values.first;
  var high = values.first;
  for (final value in values) {
    if (value < low) low = value;
    if (value > high) high = value;
  }
  if (low == high) {
    // A single distinct value (a one-trial run) would otherwise give a zero-height axis.
    final pad = low.abs() < 1 ? 1.0 : low.abs() * 0.1;
    return (min: low - pad, max: high + pad);
  }
  final pad = (high - low) * 0.05;
  return (min: low - pad, max: high + pad);
}

/// Formats a cost for an axis tick or tooltip. Costs span 1e0 to 1e20 in this corpus.
String formatAxisCost(double value) {
  if (value == 0) return '0';
  if (value.abs() >= 1e5 || value.abs() < 1e-2) {
    return value.toStringAsExponential(1);
  }
  if (value.abs() >= 100) return value.toStringAsFixed(0);
  return value.toStringAsFixed(2);
}

/// Asserts the invariant v3.01 D6 designed for: the allocation series and the cost series are
/// thinned with the **same keep set**, so their step indices line up one-for-one.
///
/// Checked rather than trusted — if a future change broke it, the bars would silently show a
/// different step's allocation than the curve, which no test of either alone would catch.
bool allocationsAlignWith(RunSeries series, AllocationSeries allocations) {
  if (series.points.length != allocations.points.length) return false;
  for (var i = 0; i < series.points.length; i++) {
    if (series.points[i].stepIndex != allocations.points[i].stepIndex) return false;
  }
  return true;
}

/// The allocation recorded at or before [step] — what the bars show at the scrubber position.
AllocationPoint? allocationAt(AllocationSeries allocations, int step) {
  AllocationPoint? found;
  for (final point in allocations.points) {
    if (point.stepIndex <= step) {
      found = point;
    } else {
      break;
    }
  }
  return found;
}

/// Names the grouping keys an overlay spans, or null when the runs are directly comparable.
///
/// An overlay computes no aggregate, so it is not *pooling* — but an unlabelled overlay invites
/// the viewer to pool it by eye, which is the same error one step removed.
String? mixedPopulationWarning(List<RunSummary> runs) {
  if (runs.length < 2) return null;
  final modes = runs.map((r) => r.observationMode).toSet();
  final allocationModes = runs.map((r) => r.allocationMode).toSet();
  final versions = runs.map((r) => '${r.strategy}/${r.strategyVersion}').toSet();
  final spans = <String>[
    if (modes.length > 1) 'observation modes (${modes.join(', ')})',
    if (allocationModes.length > 1)
      'allocation modes (${allocationModes.join(', ')})',
  ];
  if (spans.isEmpty) return null;
  final detail = spans.join(' and ');
  return versions.length > 1
      ? 'These runs span $detail — they are not directly comparable.'
      : 'These runs span $detail — the same strategy, but not directly comparable.';
}

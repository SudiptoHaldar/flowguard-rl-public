/// Immutable models mirroring the flowguard-rl chart API (req_003 v3.02).
///
/// Hand-written on purpose (v3.03 D4): the shapes are pinned by the server's Pydantic models
/// and change only when a spec version changes them, so this boilerplate is written roughly
/// once — against a `build_runner` step that CI and every contributor would have to remember.
///
/// **The snake_case JSON key is spelled exactly once, in `fromJson`.** Nothing else in `lib/`
/// mentions the wire spelling; everything above reads camelCase Dart fields. Numbers arrive as
/// `int` when they are whole, so every double is read through `(x as num).toDouble()`.
library;

/// One Circuit(Load) problem with at least one completed run.
class ScenarioRef {
  const ScenarioRef({
    required this.circuitName,
    required this.totalLoad,
    required this.runCount,
    required this.bestCost,
  });

  final String circuitName;
  final double totalLoad;
  final int runCount;
  final double? bestCost;

  factory ScenarioRef.fromJson(Map<String, dynamic> json) => ScenarioRef(
        circuitName: json['circuit_name'] as String,
        totalLoad: (json['total_load'] as num).toDouble(),
        runCount: json['run_count'] as int,
        bestCost: (json['best_cost'] as num?)?.toDouble(),
      );
}

/// Header for one completed run. There is no `status`: the API only ever serves completed
/// runs, so a status field would imply a variation that cannot occur.
class RunSummary {
  const RunSummary({
    required this.runId,
    required this.circuitName,
    required this.totalLoad,
    required this.strategy,
    required this.strategyVersion,
    required this.seed,
    required this.budget,
    required this.observationMode,
    required this.allocationMode,
    required this.coldStart,
    required this.terminationReason,
    required this.externalNodeNames,
    required this.trialsUsed,
    required this.firstCost,
    required this.bestCost,
    required this.improvement,
    required this.createdAt,
    required this.completedAt,
  });

  final int runId;
  final String circuitName;
  final double totalLoad;
  final String strategy;
  final String? strategyVersion;
  final int? seed;
  final int? budget;
  final String observationMode;
  final String allocationMode;
  final bool coldStart;
  final String? terminationReason;
  final List<String> externalNodeNames;
  final int trialsUsed;

  /// Null for a completed run that recorded no trials.
  final double? firstCost;
  final double? bestCost;
  final double improvement;
  final DateTime createdAt;
  final DateTime? completedAt;

  /// The grouping keys, formatted for display. These labels are what every comparison in
  /// v3.05 depends on, so the run list shows them rather than hiding them behind an id.
  String get groupingLabel => '$strategy'
      '${strategyVersion == null ? '' : ' $strategyVersion'}'
      ' · $allocationMode · $observationMode'
      ' · ${coldStart ? 'cold' : 'warm'}';

  factory RunSummary.fromJson(Map<String, dynamic> json) => RunSummary(
        runId: json['run_id'] as int,
        circuitName: json['circuit_name'] as String,
        totalLoad: (json['total_load'] as num).toDouble(),
        strategy: json['strategy'] as String,
        strategyVersion: json['strategy_version'] as String?,
        seed: json['seed'] as int?,
        budget: json['budget'] as int?,
        observationMode: json['observation_mode'] as String,
        allocationMode: json['allocation_mode'] as String,
        coldStart: json['cold_start'] as bool,
        terminationReason: json['termination_reason'] as String?,
        externalNodeNames:
            (json['external_node_names'] as List<dynamic>).cast<String>(),
        trialsUsed: json['trials_used'] as int,
        firstCost: (json['first_cost'] as num?)?.toDouble(),
        bestCost: (json['best_cost'] as num?)?.toDouble(),
        improvement: (json['improvement'] as num).toDouble(),
        createdAt: DateTime.parse(json['created_at'] as String),
        completedAt: json['completed_at'] == null
            ? null
            : DateTime.parse(json['completed_at'] as String),
      );
}

/// A page of runs plus the unpaginated total describing it.
class RunPage {
  const RunPage({
    required this.items,
    required this.total,
    required this.limit,
    required this.offset,
  });

  final List<RunSummary> items;
  final int total;
  final int limit;
  final int offset;

  factory RunPage.fromJson(Map<String, dynamic> json) => RunPage(
        items: (json['items'] as List<dynamic>)
            .map((e) => RunSummary.fromJson(e as Map<String, dynamic>))
            .toList(),
        total: json['total'] as int,
        limit: json['limit'] as int,
        offset: json['offset'] as int,
      );
}

/// One trial on the cost-vs-trial curve.
///
/// `bestSoFar` is the envelope over the **full** series, computed server-side before
/// downsampling, so it stays exact however few points come back.
class SeriesPoint {
  const SeriesPoint({
    required this.stepIndex,
    required this.totalCost,
    required this.bestSoFar,
    required this.isBest,
  });

  final int stepIndex;
  final double totalCost;
  final double bestSoFar;
  final bool isBest;

  factory SeriesPoint.fromJson(Map<String, dynamic> json) => SeriesPoint(
        stepIndex: json['step_index'] as int,
        totalCost: (json['total_cost'] as num).toDouble(),
        bestSoFar: (json['best_so_far'] as num).toDouble(),
        isBest: json['is_best'] as bool,
      );
}

/// Benchmark-derived reference figures for the run's scenario.
///
/// Provenance travels with the numbers: a regret against a `best_observed` optimum is a weaker
/// claim than one against an `enumerated` optimum, so [optimumMethod] is rendered beside the
/// line. [bestOfRandom] is null when the server could not verify the equal-budget comparison.
class ScenarioReference {
  const ScenarioReference({
    required this.optimum,
    required this.optimumMethod,
    required this.bestOfRandom,
    required this.bestOfRandomStrategyVersion,
    required this.catalogName,
    required this.catalogVersion,
    required this.benchmarkId,
  });

  final double? optimum;
  final String optimumMethod;
  final double? bestOfRandom;
  final String? bestOfRandomStrategyVersion;
  final String catalogName;
  final int catalogVersion;
  final int benchmarkId;

  factory ScenarioReference.fromJson(Map<String, dynamic> json) => ScenarioReference(
        optimum: (json['optimum'] as num?)?.toDouble(),
        optimumMethod: json['optimum_method'] as String,
        bestOfRandom: (json['best_of_random'] as num?)?.toDouble(),
        bestOfRandomStrategyVersion:
            json['best_of_random_strategy_version'] as String?,
        catalogName: json['catalog_name'] as String,
        catalogVersion: json['catalog_version'] as int,
        benchmarkId: json['benchmark_id'] as int,
      );
}

/// The replay feed: a run header plus its (possibly thinned) trial series.
class RunSeries {
  const RunSeries({
    required this.run,
    required this.points,
    required this.totalPoints,
    required this.downsampled,
    required this.reference,
  });

  final RunSummary run;
  final List<SeriesPoint> points;

  /// The untinned count. **Never assume `points.length == max_points`** — the server keeps
  /// every improving step even when that exceeds the requested budget.
  final int totalPoints;
  final bool downsampled;

  /// Null when no benchmark covers this scenario — the chart then draws no reference lines.
  final ScenarioReference? reference;

  factory RunSeries.fromJson(Map<String, dynamic> json) => RunSeries(
        run: RunSummary.fromJson(json['run'] as Map<String, dynamic>),
        points: (json['points'] as List<dynamic>)
            .map((e) => SeriesPoint.fromJson(e as Map<String, dynamic>))
            .toList(),
        totalPoints: json['total_points'] as int,
        downsampled: json['downsampled'] as bool,
        reference: json['reference'] == null
            ? null
            : ScenarioReference.fromJson(json['reference'] as Map<String, dynamic>),
      );
}

/// Loads at one step, positional against [AllocationSeries.nodeNames].
class AllocationPoint {
  const AllocationPoint({required this.stepIndex, required this.loads});

  final int stepIndex;
  final List<double> loads;

  factory AllocationPoint.fromJson(Map<String, dynamic> json) => AllocationPoint(
        stepIndex: json['step_index'] as int,
        loads: (json['loads'] as List<dynamic>)
            .map((e) => (e as num).toDouble())
            .toList(),
      );
}

/// One external node's capacities, from the circuit's current definition.
class ExternalNode {
  const ExternalNode({
    required this.name,
    required this.loadFactor,
    required this.loadSafetyCap,
  });

  final String name;
  final double loadFactor;
  final double loadSafetyCap;

  factory ExternalNode.fromJson(Map<String, dynamic> json) => ExternalNode(
        name: json['name'] as String,
        loadFactor: (json['load_factor'] as num).toDouble(),
        loadSafetyCap: (json['load_safety_cap'] as num).toDouble(),
      );
}

/// Capacity marks, and whether they may be drawn.
///
/// [matchesRun] is false when the circuit's external nodes no longer match the ones the run
/// recorded. The nodes are still carried so the UI can show *what* changed — but the marks
/// must not be drawn against a definition the run never saw.
class NodeCapacities {
  const NodeCapacities({required this.nodes, required this.matchesRun});

  final List<ExternalNode> nodes;
  final bool matchesRun;

  factory NodeCapacities.fromJson(Map<String, dynamic> json) => NodeCapacities(
        nodes: (json['nodes'] as List<dynamic>)
            .map((e) => ExternalNode.fromJson(e as Map<String, dynamic>))
            .toList(),
        matchesRun: json['matches_run'] as bool,
      );
}

/// The distinct allocations that reached the run's best cost.
///
/// Computed server-side over every step. A client cannot derive this from [AllocationSeries]:
/// `is_best` marks only a *strict* improvement, so trials that merely match the best are not
/// flagged and get thinned away — one shipped run reaches its best with 14 distinct allocations
/// from a series of 12 points.
class BestAllocations {
  const BestAllocations({required this.cost, required this.allocations});

  final double cost;
  final List<List<double>> allocations;

  /// True when the optimum is flat — the optimizer had real freedom in where to put the load.
  bool get isTied => allocations.length > 1;

  factory BestAllocations.fromJson(Map<String, dynamic> json) => BestAllocations(
        cost: (json['cost'] as num).toDouble(),
        allocations: (json['allocations'] as List<dynamic>)
            .map((row) =>
                (row as List<dynamic>).map((e) => (e as num).toDouble()).toList())
            .toList(),
      );
}

/// Per-node loads over a run, thinned with the same keep set as the cost series.
class AllocationSeries {
  const AllocationSeries({
    required this.runId,
    required this.nodeNames,
    required this.points,
    required this.totalPoints,
    required this.downsampled,
    this.capacities,
    this.best,
  });

  final int runId;

  /// The **run's own** node list — the ordering authority for anything historical.
  final List<String> nodeNames;
  final List<AllocationPoint> points;
  final int totalPoints;
  final bool downsampled;

  /// Null when the circuit no longer exists — a different state from drift.
  final NodeCapacities? capacities;
  final BestAllocations? best;

  factory AllocationSeries.fromJson(Map<String, dynamic> json) => AllocationSeries(
        runId: json['run_id'] as int,
        nodeNames: (json['node_names'] as List<dynamic>).cast<String>(),
        points: (json['points'] as List<dynamic>)
            .map((e) => AllocationPoint.fromJson(e as Map<String, dynamic>))
            .toList(),
        totalPoints: json['total_points'] as int,
        downsampled: json['downsampled'] as bool,
        capacities: json['capacities'] == null
            ? null
            : NodeCapacities.fromJson(json['capacities'] as Map<String, dynamic>),
        best: json['best'] == null
            ? null
            : BestAllocations.fromJson(json['best'] as Map<String, dynamic>),
      );
}

/// Provenance for one harness invocation — what makes a plotted number re-checkable.
class BenchmarkHeader {
  const BenchmarkHeader({
    required this.benchmarkId,
    required this.catalogName,
    required this.catalogVersion,
    required this.nSeeds,
    required this.boundFactor,
    required this.enumerationCap,
    required this.notes,
    required this.createdAt,
  });

  final int benchmarkId;
  final String catalogName;
  final int catalogVersion;
  final int nSeeds;
  final double boundFactor;
  final int enumerationCap;
  final String? notes;
  final DateTime createdAt;

  factory BenchmarkHeader.fromJson(Map<String, dynamic> json) => BenchmarkHeader(
        benchmarkId: json['benchmark_id'] as int,
        catalogName: json['catalog_name'] as String,
        catalogVersion: json['catalog_version'] as int,
        nSeeds: json['n_seeds'] as int,
        boundFactor: (json['bound_factor'] as num).toDouble(),
        enumerationCap: json['enumeration_cap'] as int,
        notes: json['notes'] as String?,
        createdAt: DateTime.parse(json['created_at'] as String),
      );
}

/// One comparable population, aggregated across its seeds.
///
/// The seven leading fields are the grouping keys. Pooling across any of them is the error the
/// server's query layer exists to prevent, so they travel with every cell and are shown.
class ComparisonCell {
  const ComparisonCell({
    required this.circuitName,
    required this.totalLoad,
    required this.strategy,
    required this.strategyVersion,
    required this.allocationMode,
    required this.observationMode,
    required this.coldStart,
    required this.runs,
    required this.bestCostMedian,
    required this.bestCostMin,
    required this.bestCostMax,
    required this.improvementMedian,
    required this.convergenceStepMedian,
    required this.optimum,
    required this.optimumMethod,
    required this.regretMedian,
    required this.safetyFractionMedian,
    required this.excludedFromAggregates,
  });

  final String circuitName;
  final double totalLoad;
  final String strategy;
  final String? strategyVersion;
  final String allocationMode;
  final String observationMode;
  final bool coldStart;
  final int runs;
  final double bestCostMedian;
  final double bestCostMin;
  final double bestCostMax;
  final double improvementMedian;
  final double convergenceStepMedian;
  final double? optimum;

  /// `enumerated` | `best_observed` | `unknown`. A regret against a fallback optimum is not
  /// the same claim as one against a proven optimum, so this is always displayed alongside it.
  final String optimumMethod;
  final double? regretMedian;
  final double safetyFractionMedian;

  /// True for `equal_split`, whose one-cycle disposal cost would swamp any aggregate.
  final bool excludedFromAggregates;

  factory ComparisonCell.fromJson(Map<String, dynamic> json) => ComparisonCell(
        circuitName: json['circuit_name'] as String,
        totalLoad: (json['total_load'] as num).toDouble(),
        strategy: json['strategy'] as String,
        strategyVersion: json['strategy_version'] as String?,
        allocationMode: json['allocation_mode'] as String,
        observationMode: json['observation_mode'] as String,
        coldStart: json['cold_start'] as bool,
        runs: json['runs'] as int,
        bestCostMedian: (json['best_cost_median'] as num).toDouble(),
        bestCostMin: (json['best_cost_min'] as num).toDouble(),
        bestCostMax: (json['best_cost_max'] as num).toDouble(),
        improvementMedian: (json['improvement_median'] as num).toDouble(),
        convergenceStepMedian: (json['convergence_step_median'] as num).toDouble(),
        optimum: (json['optimum'] as num?)?.toDouble(),
        optimumMethod: json['optimum_method'] as String,
        regretMedian: (json['regret_median'] as num?)?.toDouble(),
        safetyFractionMedian: (json['safety_fraction_median'] as num).toDouble(),
        excludedFromAggregates: json['excluded_from_aggregates'] as bool,
      );
}

/// The comparison grid. `available` is false when no benchmark has ever run — an empty state
/// to render, **not** an error.
class ComparisonResponse {
  const ComparisonResponse({
    required this.available,
    required this.benchmark,
    required this.cells,
  });

  final bool available;
  final BenchmarkHeader? benchmark;
  final List<ComparisonCell> cells;

  factory ComparisonResponse.fromJson(Map<String, dynamic> json) => ComparisonResponse(
        available: json['available'] as bool,
        benchmark: json['benchmark'] == null
            ? null
            : BenchmarkHeader.fromJson(json['benchmark'] as Map<String, dynamic>),
        cells: (json['cells'] as List<dynamic>)
            .map((e) => ComparisonCell.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

/// One node of the circuit's current definition (req_003 v3.07).
class TopologyNode {
  const TopologyNode({
    required this.name,
    required this.kind,
    required this.loadFactor,
    required this.loadSafetyCap,
  });

  final String name;

  /// `external` (the optimizer may load it) or `internal` (fed only by edges).
  final String kind;
  final double loadFactor;
  final double loadSafetyCap;

  bool get isExternal => kind == 'external';

  factory TopologyNode.fromJson(Map<String, dynamic> json) => TopologyNode(
        name: json['name'] as String,
        kind: json['kind'] as String,
        loadFactor: (json['load_factor'] as num).toDouble(),
        loadSafetyCap: (json['load_safety_cap'] as num).toDouble(),
      );
}

/// A directed line carrying [weight] of the source's load onward.
class TopologyEdge {
  const TopologyEdge({
    required this.source,
    required this.target,
    required this.weight,
  });

  final String source;
  final String target;
  final double weight;

  factory TopologyEdge.fromJson(Map<String, dynamic> json) => TopologyEdge(
        source: json['source'] as String,
        target: json['target'] as String,
        weight: (json['weight'] as num).toDouble(),
      );
}

/// Carried load per node at one trial, positional against [CircuitTopology.nodes].
class CarriedStep {
  const CarriedStep({required this.stepIndex, required this.loads});

  final int stepIndex;
  final List<double> loads;

  factory CarriedStep.fromJson(Map<String, dynamic> json) => CarriedStep(
        stepIndex: json['step_index'] as int,
        loads: (json['loads'] as List<dynamic>)
            .map((e) => (e as num).toDouble())
            .toList(),
      );
}

/// The circuit's shape and what each node carried during a run.
///
/// The loads are the **engine's** propagation, fetched rather than recomputed — the client
/// never walks the graph itself, or it would hold a second copy of a rule that can drift.
///
/// Node identity here comes from the **circuit**, not the run — the inverse of the per-node
/// allocation panels. That is deliberate: the diagram *is* the circuit's current structure, and
/// the run only supplies loads, and only when [matchesRun] allows.
class CircuitTopology {
  const CircuitTopology({
    required this.circuitName,
    required this.totalLoad,
    required this.nodes,
    required this.edges,
    required this.matchesRun,
    required this.carried,
  });

  final String circuitName;

  /// The scenario's **requested** load — not what any trial assigned. Only `equal_split`
  /// allocates exactly this much; the other strategies routinely undershoot it.
  final double totalLoad;
  final List<TopologyNode> nodes;
  final List<TopologyEdge> edges;

  /// False when the circuit has changed since the run: structure stands, loads are withheld.
  final bool matchesRun;
  final List<CarriedStep> carried;

  /// No edges — every external node is terminal. Three of four shipped circuits are like this.
  bool get isFlat => edges.isEmpty;

  TopologyNode? nodeNamed(String name) {
    for (final node in nodes) {
      if (node.name == name) return node;
    }
    return null;
  }

  factory CircuitTopology.fromJson(Map<String, dynamic> json) => CircuitTopology(
        circuitName: json['circuit_name'] as String,
        totalLoad: (json['total_load'] as num).toDouble(),
        nodes: (json['nodes'] as List<dynamic>)
            .map((e) => TopologyNode.fromJson(e as Map<String, dynamic>))
            .toList(),
        edges: (json['edges'] as List<dynamic>)
            .map((e) => TopologyEdge.fromJson(e as Map<String, dynamic>))
            .toList(),
        matchesRun: json['matches_run'] as bool,
        carried: (json['carried'] as List<dynamic>)
            .map((e) => CarriedStep.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

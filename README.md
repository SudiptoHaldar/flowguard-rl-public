# flowguard-rl

[![CI](https://github.com/SudiptoHaldar/flowguard-rl-public/actions/workflows/ci.yml/badge.svg)](https://github.com/SudiptoHaldar/flowguard-rl-public/actions/workflows/ci.yml)

A partially observable RL environment for distributing load across capacity-constrained networks using terminal polynomial costs and explicit safety limits.

## Components

The `flowguard` package holds one subpackage per component:

- `flowguard/circuits/` — Circuits: DAG engine where nodes carry load factors, safety caps, and polynomial penalty functions; weighted edges split load across branches and merge it at joins, with internal nodes penalized on the load they carry (see `config/example_dag_circuit.yaml`).
- `flowguard/rl/` — RL Element: learns load distribution from `ext_nodes`, the total load, and the terminal scalar penalty.
- `flowguard/data/` — Data/Charting: trajectory capture, storage (PostgreSQL + Alembic), and progress visualization (Flutter).

Tunable parameters (polynomial coefficients, horizons, tolerances) live in versioned YAML files under `config/` — never in code. `flowguard/settings.py` provides env-var access (via `.env`) and the YAML config loader. Default penalty polynomials (f1/f2/f3) live in `config/circuit_defaults.yaml`; circuits/nodes may override them per definition.

Quick taste of the circuits API:

```python
from flowguard.circuits import Circuit

c1 = Circuit.from_config("config/example_circuit.yaml")
print([n.name for n in c1.ext_nodes()])              # ['N1', 'N2']
print(c1.evaluate(60, {"N1": 10, "N2": 10}).total)   # 92.0
```

## Dev setup

```powershell
# Windows (PowerShell)
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env    # then adjust values
pytest
```

```bash
# POSIX
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then adjust values
pytest
```

### Database

Local PostgreSQL with database `flowguard_db` owned by role `flowguard`. Set `DATABASE_URL`
in `.env`, then bring the schema up to date:

```powershell
alembic upgrade head
```

Unit tests never need the database; live-DB integration tests run with `pytest -m db` and
skip automatically when PostgreSQL is unreachable.

Circuit definitions can be persisted via `flowguard.circuits.store` (tables `circuits` /
`circuit_nodes`; requires `alembic upgrade head`), and inspected/exercised from the
command line — `python -m flowguard.circuits describe C2`,
`python -m flowguard.circuits evaluate C2 60 10 10` (loads assigned positionally to the
stable external-node order). RL code uses the opaque
`flowguard.circuits.interface` instead — external-node names and total cost only.

RL algo-runs are persisted trial by trial (tables `rl_runs` / `rl_steps`, plus the
`v_rl_step_loads` view for per-node charting): every `evaluate` call a strategy makes is
recorded as it happens, so a run is replayable and a learner can condition its next load
distribution on the results of earlier calls.

```python
from flowguard.rl.recorder import RunRecorder

with RunRecorder("C2", 60, strategy="equal_split") as run:
    cost = run.evaluate([10, 10])   # 92.0 — and the trial is now in the database
```

Optimisation itself runs through `run_algo`, which drives a strategy under a trial budget and
persists every probe. Four heuristic baselines ship as the reference any
learned strategy must beat:

```python
from flowguard.rl.driver import run_algo
from flowguard.rl.proposers import HillClimb

run_algo("C3", 60, HillClimb(), seed=1)   # best_cost=2.0 — the exact optimum for C3
```

Or from the command line — `--json` on every command, and `runs` also sweeps
runs abandoned by a crashed process:

```powershell
python -m flowguard.rl optimize C4 10000 --strategy hill_climb --seed 1
python -m flowguard.rl runs --circuit C4
python -m flowguard.rl show 601 --trace
```

Strategy comparison runs through a versioned scenario catalog with exact optima computed by
bounded enumeration, persisted with their provenance (tables `rl_benchmarks` /
`rl_benchmark_results`):

```powershell
python -m flowguard.rl benchmark        # 8 scenarios x 4 baselines, ~19 s
```

### API

The data/charting backend exposes a FastAPI service (app factory, no module-level app):

```powershell
uvicorn flowguard.data.api:create_app --factory --reload --port 8100
```

The project's standard dev port is **8100** (8000 is taken by another local project — always
pass `--port 8100`). Then check `http://localhost:8100/health` (liveness + version),
`http://localhost:8100/health/db` (database reachability; 503 when PostgreSQL is down), and
the interactive docs at `http://localhost:8100/docs`. Chart feeds live under `/api/v1`:

```powershell
Invoke-RestMethod "http://localhost:8100/api/v1/scenarios"                       # Circuit(Load) picker
Invoke-RestMethod "http://localhost:8100/api/v1/runs?circuit_name=C4&limit=5"    # run picker
Invoke-RestMethod "http://localhost:8100/api/v1/runs/1091/series?max_points=12"  # cost vs trial
Invoke-RestMethod "http://localhost:8100/api/v1/comparison"                      # algorithm grid
```

Also usable as a library — the endpoints are transport over `flowguard/data/queries.py`:

```python
from flowguard.data import database, queries

session = database.get_session_factory()()
queries.list_scenarios(session)
queries.get_run_series(session, run_id, max_points=500)   # + best-so-far envelope
queries.get_comparison(session)
```

Read-only by construction (GET only; anything else is 405), and only `completed` runs are
visible — a failed or abandoned run is reachable through `python -m flowguard.rl runs`, never
through a chart. Series are capped by default and never drop a step where the best-so-far
improved.

### Front end

`flutter_app/` holds the dashboard (`flowguard_dashboard`, Material 3, sage theme) over the
`/api/v1` chart feeds. Web-first dev workflow (requires the Flutter SDK, stable channel):

```powershell
cd flutter_app
flutter pub get
flutter run -d chrome        # with the API up on 8100
```

Five screens, with URLs mirroring the API so a run is bookmarkable:

| Route | Shows |
|---|---|
| `/` | scenario picker — every Circuit(Load) with completed runs |
| `/runs` | run list for the selected scenario, grouping keys included |
| `/runs/{id}` | **progress chart** — cost vs trial with the best-so-far envelope, optimum reference lines, a replay scrubber, allocation bars and up to 3 overlaid runs |
| `/runs/{id}/allocations` | **per-node panels** — load over trials against each node's factor and safety cap, with ties named |
| `/runs/{id}/topology` | **where the load flows** — the circuit as a DAG with each node's carried load against its own factor and safety cap |
| `/comparison` | **comparison matrix** — scenario × strategy coloured by regret against the optimum, with `equal_split` sectioned out and cells linking back to their runs |

Flutter web uses hash URLs, so a deep link is `http://localhost:PORT/#/runs/1091`.

The API base URL defaults to `http://localhost:8100` and lives only in `lib/config.dart`;
override it per run with `--dart-define=API_BASE_URL=http://host:port`. State is Riverpod,
routing is go_router, and models are hand-written — no code generation, so there is no build
step to remember. The app's `pubspec.yaml` version stays in lockstep with `release_number.md`
(`{major}.{minor}.0`). Checks: `flutter analyze` and `flutter test` from `flutter_app/`
(**neither needs a backend** — screen tests fake only the HTTP transport).

Notes:

- `pip install torch` from PyPI installs the CPU-only wheel on Windows — no CUDA setup needed for development.
- `pytest` runs from the repo root with no extra flags; tests live in `tests/`, mirroring the package structure.
- Quick sanity checks:

```powershell
python -c "import flowguard; print(flowguard.__version__)"
python -c "from flowguard.settings import load_config; print(load_config('config/example_circuit.yaml'))"
```

/// App configuration. All URLs live here — nowhere else in lib/.
library;

/// Base URL of the flowguard-rl FastAPI backend.
///
/// Override at build/run time with
/// `flutter run -d chrome --dart-define=API_BASE_URL=http://host:port`.
/// Defaults to the project-standard dev port 8100.
const String apiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://localhost:8100',
);

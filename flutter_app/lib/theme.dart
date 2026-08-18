/// Material 3 theme baseline for FlowGuard Dashboard.
///
/// The charting group extends this file; do not scatter ThemeData elsewhere.
library;

import 'package:flutter/material.dart';

/// Sage green seed color — the project's theme baseline.
const Color sageSeed = Color(0xFF7C8B6F);

ThemeData lightTheme() => ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(seedColor: sageSeed),
    );

ThemeData darkTheme() => ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        seedColor: sageSeed,
        brightness: Brightness.dark,
      ),
    );

/// One overlaid series' visual identity (req_003 v3.04 D6).
///
/// **Colour is never the only channel.** Each slot also carries a dash pattern and a marker
/// shape, so an overlay stays readable in greyscale, in print, and for a viewer who cannot
/// separate two hues.
class SeriesStyle {
  const SeriesStyle({
    required this.light,
    required this.dark,
    required this.dashArray,
    required this.marker,
  });

  final Color light;
  final Color dark;

  /// `null` means a solid line. Passed straight to fl_chart's `dashArray`.
  final List<int>? dashArray;
  final SeriesMarker marker;

  Color color(Brightness brightness) =>
      brightness == Brightness.dark ? dark : light;
}

enum SeriesMarker { circle, square, triangle }

/// Categorical palette for overlaid runs — **validated, not chosen by eye**.
///
/// Three slots, in this fixed order, never cycled. The cap is three because the chart draws
/// interleaved scatter clouds, so any two series can end up adjacent: the *all-pairs* gate
/// applies, and under it no four-colour set from these ramps clears the hard normal-vision
/// floor in **both** light and dark. (blue/orange/aqua/violet passes light but violet sits
/// ΔE 1.9 from blue under protanopia on the dark surface; blue/red/aqua/yellow passes light
/// but yellow↔red measures 13.0 normal-vision on dark.) Comparing all four shipped strategies
/// at once is the comparison matrix's job, not this view's.
///
/// Measured against this app's real Material 3 surfaces — light `#f8faf0`, dark `#11140e`:
///
/// | mode | worst CVD ΔE | worst normal-vision ΔE | contrast |
/// |---|---|---|---|
/// | light | 9.2 (deutan) | 24.0 | aqua 2.67:1 — relief applies |
/// | dark | 9.4 (deutan) | 20.9 | all ≥ 3:1 |
///
/// The light-mode aqua sits below 3:1, which obligates *relief*: the legend direct-labels every
/// series and the trial table stays available beneath the chart. Both ship, so the obligation
/// is met — it is not dismissable.
const List<SeriesStyle> seriesPalette = [
  SeriesStyle(
    light: Color(0xFF2A78D6),
    dark: Color(0xFF3987E5),
    dashArray: null,
    marker: SeriesMarker.circle,
  ),
  SeriesStyle(
    light: Color(0xFFEB6834),
    dark: Color(0xFFD95926),
    dashArray: [8, 4],
    marker: SeriesMarker.square,
  ),
  SeriesStyle(
    light: Color(0xFF1BAF7A),
    dark: Color(0xFF199E70),
    dashArray: [2, 4],
    marker: SeriesMarker.triangle,
  ),
];

/// How many runs may be overlaid at once — the palette's validated length (see above).
const int maxOverlaySeries = 3;

/// Marks a trial that improved the best-so-far — a **state**, not a series identity.
///
/// The status-good green from the reference palette. Measured against the series slots it does
/// *not* clear the separation floors on hue alone (ΔE 10.0 from aqua in light, 1.4 from orange
/// under deuteranopia in dark), so hue here is emphasis only: the real channels are **size**
/// (an improving dot is twice the radius of an ordinary trial) and a surface-coloured **ring**
/// that lifts it off whatever it overlaps. The chart also states in words that green marks an
/// improvement, so the meaning never rests on colour alone.
const Color improvementLight = Color(0xFF0CA30C);
const Color improvementDark = Color(0xFF0CA30C);

Color improvementColor(Brightness brightness) =>
    brightness == Brightness.dark ? improvementDark : improvementLight;

/// Sequential ramp for regret magnitude in the comparison matrix (req_003 v3.05 D2).
///
/// **Validated, not chosen.** Run through the data-viz validator with `--ordinal` against this
/// app's real Material 3 surfaces:
///
/// | mode | monotone L | adjacent ΔL | near-surface contrast | hue spread |
/// |---|---|---|---|---|
/// | light (`#f8faf0`) | pass | all ≥ 0.06 | `#86b6ef` **2.00:1** | 3° |
/// | dark (`#11140e`) | pass | all ≥ 0.06 | `#184f95` **2.29:1** | 3° |
///
/// Two measured limits, not preferences: a **sixth step fails** the adjacent-ΔL floor
/// (0.047–0.049 against a 0.06 minimum), and **steps lighter than this one fail** the light
/// surface (the next step up measures 1.70:1, below the 2:1 floor). Five steps starting here is
/// the maximum this hue allows.
///
/// One hue, light→dark — never a rainbow, and never diverging: zero regret is an end of the
/// scale, not a centre.
const List<Color> regretRampLight = [
  Color(0xFF86B6EF),
  Color(0xFF5598E7),
  Color(0xFF2A78D6),
  Color(0xFF1C5CAB),
  Color(0xFF104281),
];

/// The same hue re-stepped for the dark surface — and it **inverts**: on a dark surface the
/// low-magnitude end is the *dark* end, because "near the surface" is what low magnitude means.
/// Index 0 is always the lowest regret in both modes.
const List<Color> regretRampDark = [
  Color(0xFF184F95),
  Color(0xFF2A78D6),
  Color(0xFF5598E7),
  Color(0xFF86B6EF),
  Color(0xFFB7D3F6),
];

List<Color> regretRamp(Brightness brightness) =>
    brightness == Brightness.dark ? regretRampDark : regretRampLight;

/// Ink for text sitting **on a ramp cell**.
///
/// Contrast is against the cell fill, not the page surface — the ramp spans both light and dark
/// fills in either mode, so a single ink colour would make the values vanish at one end.
/// Derived from the fill's luminance so it stays correct if the ramp is ever re-stepped.
Color regretInk(Color fill) =>
    fill.computeLuminance() > 0.45 ? const Color(0xFF0B0B0B) : const Color(0xFFFFFFFF);

/// Fill for a cell at the optimum.
///
/// Deliberately **not** the ramp's first step: zero regret is a real and frequent state
/// (`hill_climb` reaches it on every shipped scenario), and rendering *optimal* as *palest blue*
/// would read as *nearly nothing*. It reuses the status-good green the progress chart already
/// uses for improvement, and — as there — it never carries the meaning alone: the cell also
/// shows a glyph and prints `0.00%`.
Color optimalFill(Brightness brightness) => improvementColor(brightness);


/// Node-state treatments for the topology diagram (req_003 v3.07 D4).
///
/// These are the **reserved status palette** — good / warning / serious / critical — never the
/// categorical series palette. A node's state is a status, not a series identity, and status
/// colours must never impersonate a series.
///
/// They are also never the only channel: every node card and legend row carries an icon and a
/// word alongside the colour, so the state survives greyscale, print and colour-vision
/// differences. The palette is mode-invariant by design — all four steps clear 3:1 on the dark
/// surface and are legible on the light one.
const Color statusGood = Color(0xFF0CA30C);
const Color statusWarning = Color(0xFFFAB219);
const Color statusSerious = Color(0xFFEC835A);
const Color statusCritical = Color(0xFFD03B3B);

/// The fifth step the reserved four do not cover: **exactly at the load factor**.
///
/// The node states are five, the status palette is four, and mapping "under factor" and "at
/// factor" both to [statusGood] made the two indistinguishable — the icon differed, the colour
/// did not, and at legend size the colour is what reads first.
///
/// Teal is chosen by measurement, not by taste. Against [statusGood] it measures **ΔE 16.6
/// normal-vision and 15.1 protan** (OKLab ×100), clearing the ≥15 floor, and it clears 3:1
/// contrast on **both** app surfaces (light `#f8faf0`, dark `#11140e`) — which [statusGood]
/// itself only manages at 3.27 on light. Candidates that were rejected on the numbers: aqua
/// `#1baf7a` (ΔE 10.0 from green — it would have become the weakest pair in the palette),
/// olive `#7fb800` (ΔE 3.5 from [statusWarning] under protanopia), and series blue `#2a78d6`,
/// which is categorical slot 1 and would let a status impersonate a series.
///
/// It sits deliberately *outside* the green→amber→orange→red escalation rather than between
/// green and amber: being exactly on the nominal mark is a notable fact, not a severity.
/// Its tritan separation from green is low (3.4), so as everywhere here the icon and the word
/// carry the meaning and the colour only speeds it up.
const Color statusAtLimit = Color(0xFF00A0A0);

/// Ink for a node whose load is unavailable — muted chrome, not a status.
const Color statusUnknown = Color(0xFF898781);

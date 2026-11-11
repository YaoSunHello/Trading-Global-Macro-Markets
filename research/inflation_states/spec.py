"""Declared hypotheses, definitions, thresholds, windows and test families for the inflation-state study.

Everything here is fixed BEFORE any Treasury outcome is computed. `freeze()` serialises it, hashes it and writes it to
results/inflation_states/spec_frozen.json; the outcome stage refuses to run if the hash changed. Definitions were chosen
from economic reasoning (documented per item) and NOT from Treasury performance.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# ----------------------------------------------------------------------------------------------- inputs
MEASURES = {"HEADLINE": "US.CPI.ALL_ITEMS.SA", "CORE": "US.CPI.CORE.SA"}
POLICY_SERIES = "US.FED_FUNDS.EFFECTIVE.M"
CPI_RELEASE_HOUR = 8.5          # BLS publishes at 08:30 ET; ALFRED vintage dates are day-granular
GENUINE_FIRST_RELEASE_MAX_LAG_DAYS = 45   # first appearance of an observation more than this long after its month end = archive artefact
OUTCOME_LAG_SESSIONS = 1        # forward returns start at the close one session after the decision date

# ----------------------------------------------------------------------------------------------- level rules
# CPI is NOT the Fed's PCE target. Over 1990-2020 CPI inflation ran roughly 0.3-0.5pp above PCE, so "target-consistent"
# CPI is about 2.3-2.5%. The fixed band is +/-1pp around that: low < 1.5, high >= 3.5. Chosen before looking at outcomes.
LEVEL_RULES = {
    "L1_FIXED": dict(kind="fixed", low=1.5, high=3.5, hyst=0.25,
                     doc="YoY CPI %: low < 1.5, high >= 3.5, else normal (fixed, economically motivated; CPI != PCE)"),
    "L2_EXP_PCTL": dict(kind="pctl", scope="expanding_full", q_low=25, q_high=75, hyst=0.25, min_hist=120,
                        doc="YoY relative to its own expanding past-only distribution: <= 25th pct low, >= 75th pct high"),
    "L3_ROLL10Y_PCTL": dict(kind="pctl", scope="roll120", q_low=25, q_high=75, hyst=0.25, min_hist=120,
                            doc="YoY relative to the trailing 120-month past-only distribution (25th/75th pct)"),
}
# Momentum: measure in percentage points; rising if > +band, falling if < -band, else stable (neutral band).
MOMENTUM_RULES = {
    "M1_DYOY_3M": dict(measure="dyoy3", band=0.30, hyst=0.15,
                       doc="Change in YoY inflation over 3 months; neutral band +/-0.30pp (index rounding + seasonal-revision noise scale)"),
    "M2_DYOY_6M": dict(measure="dyoy6", band=0.50, hyst=0.25, doc="Change in YoY inflation over 6 months; neutral band +/-0.50pp"),
    "M3_ANN6M_VS_YOY": dict(measure="gap6", band=0.50, hyst=0.25,
                            doc="6-month annualised SA inflation minus YoY (recent pace vs trailing year); neutral band +/-0.50pp"),
    "M4_ANN3M_VS_YOY": dict(measure="gap3", band=1.00, hyst=0.50,
                            doc="3-month annualised SA inflation minus YoY; neutral band +/-1.00pp (noisier horizon, wider band)"),
}
PERSISTENCE = {"raw": "no smoothing (measurement baseline)",
               "confirm2": "a new state must be observed on 2 consecutive monthly decisions before it is adopted",
               "hyst": "Schmitt-trigger: entry at the threshold, exit only after retreating by the rule's hysteresis margin"}

PRIMARY = dict(measure="HEADLINE", level="L1_FIXED", momentum="M1_DYOY_3M", persistence="raw")

# ----------------------------------------------------------------------------------------------- calibration / windows
EXPANDING_STARTS = {"full": None, "from1970": "1970-01-01", "from1985": "1985-01-01"}
ROLL_WINDOWS = [60, 120, 180]
MIN_HISTORY_MONTHS = 120
REVISION_MATURITY_MONTHS = 13
REVISION_PRIOR = dict(yoy=0.10, dyoy3=0.15, dyoy6=0.20, gap3=0.30, gap6=0.25)   # used only until >=24 matured revisions exist
CONFIDENCE_TIERS = dict(high=3.0, medium=1.0)        # margin / revision scale
EPISODES = [  # declared a priori (calendar, ex-post labels); used for robustness splits only
    ("E1_1972_79_GREAT_INFLATION", "1972-08-01", "1979-12-31"),
    ("E2_1980_89_VOLCKER_DISINFLATION", "1980-01-01", "1989-12-31"),
    ("E3_1990_01_MODERATION", "1990-01-01", "2001-12-31"),
    ("E4_2002_08_MID_2000S", "2002-01-01", "2008-12-31"),
    ("E5_2009_19_LOW_INFLATION", "2009-01-01", "2019-12-31"),
    ("E6_2020_26_PANDEMIC_SURGE", "2020-01-01", "2026-12-31"),
]
SAMPLE_STARTS = ["1973-01-01", "1985-01-01", "1997-01-01", "2002-08-01"]
RESERVED_WINDOW_START = "2015-01-01"     # outcome tables are also reported for decisions before / from this date
TURNING_POINT = dict(zigzag_pp=1.5, smooth_months=3, detect_window_months=18)
BOOTSTRAP = dict(reps=2000, seed=20261110, min_block=12)

# ----------------------------------------------------------------------------------------------- fed policy state (separate dimension)
FED_STATE = dict(window_months=6, band_pp=0.50, doc="tightening if FEDFUNDS(last complete month) rose >= 0.50pp over 6 months; easing if fell >= 0.50pp; else hold",
                 sensitivity=[dict(window_months=3, band_pp=0.25), dict(window_months=12, band_pp=0.50), dict(window_months=6, band_pp=0.25)])

# ----------------------------------------------------------------------------------------------- outcomes
HORIZONS = [1, 3, 12]
PRIMARY_HORIZON = 3
TARGETS = {"SYN8Y": "8y constant-maturity par bond built from 5Y/10Y CMT yields (MODEL-ESTIMATED, 1962+)",
           "IEF": "iShares 7-10Y Treasury ETF adjusted close (OBSERVED ETF PROXY, 2002-07+)"}
PRIMARY_TARGET = "SYN8Y"
MIN_MONTHS_CELL, MIN_SPELLS_CELL = 12, 3      # cells below this are descriptive only (no contrast reported)
DRAWDOWN_MIN = -0.05

# ----------------------------------------------------------------------------------------------- hypotheses
HYPOTHESES = [
    # --- directly from section 5.1 (Willer, Trading Global Macro Markets)
    dict(id="B1", source="section_5_1", question="economic", family="E_descriptive",
         statement="The deep Treasury drawdowns (Table 5.1) are associated with Fed tightening cycles.",
         measurable="Share of >5% drawdown episodes whose peak decision date is in the 'tightening' Fed state, vs the unconditional share of tightening months.",
         supported_if="Share of drawdown peaks in tightening materially exceeds the unconditional tightening share, in every sub-sample with >=3 episodes.",
         cannot_establish="Causality; the book's index (1973+) is not available, so episodes come from a model-estimated 8y par bond (1962+) and the IEF ETF proxy."),
    dict(id="B2", source="section_5_1", question="economic", family="E_descriptive",
         statement="The two drawdowns deeper than 10% (1977-81, 2020-23) coincided with very high inflation; without a major inflation problem drawdowns were ~10% or less.",
         measurable="Inflation level / momentum state (point-in-time) at peak and during deep (> 10%) vs shallow drawdowns.",
         supported_if="Deep drawdown episodes start/run in 'high' level states, and shallow ones do not.",
         cannot_establish="Only a handful of independent episodes exist; no inferential test is meaningful."),
    dict(id="B3", source="section_5_1", question="economic", family="E_descriptive",
         statement="High-and-rising inflation during tightening is where Treasuries are hurt; high-but-falling inflation during easing is not.",
         measurable="Forward excess return, downside frequency and forward 12m drawdown in (high, rising, tightening) vs (high, falling, easing).",
         supported_if="Block-bootstrap CI of the mean difference excludes 0 in the book's direction and survives leave-one-episode-out.",
         cannot_establish="Whether the states can be traded; no signals are generated in this study."),
    dict(id="B4", source="section_5_1", question="out_of_scope", family="untested",
         statement="Ex-post real returns depend on starting real yields (Fig 5.1); fair-value 10Y real yield ~ potential growth (Fig 5.2).",
         measurable="Not tested here (covered by the forecasting study's RY10_LEVEL / RY10_MINUS_POTGROWTH factors).", supported_if="n/a", cannot_establish="n/a"),
    # --- research extensions
    dict(id="M1", source="extension", question="measurement", family="D_measurement",
         statement="Inflation level (low/normal/high) and momentum (falling/stable/rising) can be assigned from real-time ALFRED CPI vintages.",
         measurable="Coverage: share of decision dates with a defined state, per measure, within the vintage-verified window; release-to-decision lag.",
         supported_if="Coverage >= 95% of decision dates in the primary window and release_ts <= decision_ts for every row.",
         cannot_establish="That the state is 'correct': no observed true regime exists."),
    dict(id="D1", source="extension", question="detection", family="D_detection",
         statement="Headline and core CPI give consistent level and momentum classifications.",
         measurable="Weighted Cohen's kappa and raw agreement, headline vs core (1997+), stationary block-bootstrap CI.",
         supported_if="Lower 95% CI bound of weighted kappa >= 0.60 for the level rule.", cannot_establish="Accuracy; two noisy measures can agree and both be wrong."),
    dict(id="D2", source="extension", question="detection", family="D_detection",
         statement="Level/momentum labels are robust to reasonable rule definitions.",
         measurable="Pairwise weighted kappa between L1-L3 and between M1-M4 (headline, core).",
         supported_if="Median pairwise kappa >= 0.60 with CI.", cannot_establish="Truth; rules built on the same index share error."),
    dict(id="D3", source="extension", question="detection", family="D_detection",
         statement="Real-time labels are rarely changed by later revisions.",
         measurable="Share of decision dates whose real-time label differs from the label for the same month under latest-revised data.",
         supported_if="Upper 95% CI bound of the flip share <= 5% for the level rule and <= 10% for momentum.",
         cannot_establish="Stability of future, differently-revised data (e.g. the 2013/2019 CPI methodology changes are in the sample but rare)."),
    dict(id="D4", source="extension", question="detection", family="D_detection",
         statement="Raw momentum labels switch too often; persistence rules reduce short-lived reversals at an acceptable delay cost.",
         measurable="Transitions/year, share of spells <= 2 months, reversals within 3 months, and detection delay vs ex-post turning points, per persistence rule.",
         supported_if="confirm2/hyst cut short spells by >= 50% with a median added delay <= 3 months.",
         cannot_establish="Which rule is 'best': the delay reference is ex-post and itself a modelling choice."),
    dict(id="D5", source="extension", question="detection", family="D_detection",
         statement="Momentum turns are detected within a useful delay.",
         measurable="Months from ex-post zigzag turning point (retrospective, latest-revised YoY) to the first matching momentum switch.",
         supported_if="Median delay <= 6 months and >= 75% of turning points detected within 18 months.",
         cannot_establish="Timeliness only - not accuracy; the reference is ex-post."),
    dict(id="R1", source="extension", question="robustness", family="D_robustness",
         statement="Detection properties are stable across calibration scheme, sample start and inflation episodes.",
         measurable="State shares, transition rates and agreement metrics by calibration, sample start and leaving out each declared episode.",
         supported_if="Metrics change by less than the bootstrap half-width when any one episode is removed.",
         cannot_establish="Out-of-regime behaviour: only ~6 distinct episodes exist."),
    dict(id="E1", source="extension", question="economic", family="E_primary",
         statement="Forward 3m Treasury excess returns are lower after high-inflation level states than otherwise.",
         measurable="Mean forward 3m excess return (SYN8Y), high vs not-high, headline L1; block-bootstrap CI.", supported_if="CI excludes 0, sign negative, Holm-adjusted p < 0.05.",
         cannot_establish="Predictability net of costs; a tradable edge."),
    dict(id="E2", source="extension", question="economic", family="E_primary",
         statement="Forward 3m Treasury excess returns are lower after 'rising' than after 'falling' momentum states.",
         measurable="Mean difference rising - falling, headline M1.", supported_if="As E1.", cannot_establish="As E1."),
    dict(id="E3", source="extension", question="economic", family="E_primary",
         statement="Forward 3m excess returns differ between low and high level states.",
         measurable="Mean difference low - high, headline L1.", supported_if="As E1.", cannot_establish="As E1."),
    dict(id="E4", source="extension", question="economic", family="E_primary",
         statement="High-and-rising inflation during tightening has worse forward 3m excess returns than high-but-falling inflation during easing.",
         measurable="Mean difference (high,rising,tightening) - (high,falling,easing).", supported_if="As E1 and each cell has >=12 months and >=3 spells.",
         cannot_establish="As E1."),
    dict(id="E5", source="extension", question="economic", family="E_secondary",
         statement="The E1-E4 contrasts also hold for core CPI, other rules, other horizons (1m, 12m) and the IEF proxy.",
         measurable="All other contrast x measure x rule x target x horizon combinations (exploratory; Benjamini-Hochberg, total count disclosed).",
         supported_if="Consistent sign and CI exclusion across most combinations after BH.", cannot_establish="Confirmatory evidence."),
]

TEST_FAMILIES = dict(
    E_primary="Holm within the 4 primary contrasts (HEADLINE, L1/M1, SYN8Y, 3m horizon)",
    E_secondary="Benjamini-Hochberg across all other contrast combinations; exploratory; total count reported",
    D_detection="No p-values. Effect sizes with stationary block-bootstrap CIs; thresholds in 'supported_if' are declared guides",
)


def as_dict() -> dict:
    return dict(measures=MEASURES, policy_series=POLICY_SERIES, level_rules=LEVEL_RULES, momentum_rules=MOMENTUM_RULES,
                persistence=PERSISTENCE, primary=PRIMARY, expanding_starts=EXPANDING_STARTS, roll_windows=ROLL_WINDOWS,
                episodes=EPISODES, sample_starts=SAMPLE_STARTS, reserved_window_start=RESERVED_WINDOW_START,
                turning_point=TURNING_POINT, bootstrap=BOOTSTRAP, fed_state=FED_STATE, horizons=HORIZONS,
                primary_horizon=PRIMARY_HORIZON, targets=TARGETS, primary_target=PRIMARY_TARGET,
                hypotheses=HYPOTHESES, test_families=TEST_FAMILIES, outcome_lag_sessions=OUTCOME_LAG_SESSIONS,
                revision_prior=REVISION_PRIOR, confidence_tiers=CONFIDENCE_TIERS, min_cell=[MIN_MONTHS_CELL, MIN_SPELLS_CELL])


def spec_hash() -> str:
    return hashlib.sha256(json.dumps(as_dict(), sort_keys=True, default=str).encode()).hexdigest()


def freeze(out_dir: Path, as_of: str) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / "spec_frozen.json"
    h = spec_hash()
    if f.exists():
        old = json.loads(f.read_text())
        if old["sha256"] == h:
            return h
    f.write_text(json.dumps(dict(sha256=h, frozen_at=as_of, spec=as_dict()), indent=2, default=str))
    return h


def verify_frozen(out_dir: Path) -> None:
    f = out_dir / "spec_frozen.json"
    if not f.exists() or json.loads(f.read_text())["sha256"] != spec_hash():
        raise RuntimeError("definitions changed after being frozen; refusing to compute outcomes")

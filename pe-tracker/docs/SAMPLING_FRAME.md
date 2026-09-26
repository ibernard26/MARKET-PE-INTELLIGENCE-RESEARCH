# Sampling frame for deal-break probability research

**Canonical reviewed SEC manifest (through autonomous Batch 9):** **65**
resolved deals (Batch 8 N = 62 + Batch 9 admitted N = 3; KLAC/LRCX and
AKRX/Fresenius excluded without substitution). Label mix: Y=0 closed = 46,
Y=1 terminated = 19, censored = 0. Counts describe the **canonical research
corpus**, not a population. The frozen `first_walkforward_v1` model cohort
remains the Batch-8 N=62 identity and is a subset of this corpus.

## Canonical corpus vs model cohort

| Concept | Meaning |
|---|---|
| **Canonical corpus** | Every transaction whose facts satisfy evidence and provenance rules and are written to the SQLite store via the reviewed SEC path. Membership answers: “is this deal correctly sourced?” |
| **Model cohort** | The subset of canonical deal IDs admitted into a particular probability experiment. Membership answers: “is this deal legitimate for *this* sampling design?” |

Canonical inclusion and training eligibility are **separate**. A correctly sourced
deal may remain outside a probability-calibration cohort.

See `src/model/cohort.py` for the non-destructive cohort mechanism.

## Sampling designs (vocabulary)

| Design | Outcome known at selection? | Use for absolute P(break)? |
|---|---|---|
| **Convenience sample** | Often yes (analyst interest) | No — selection process unknown |
| **Outcome-enriched sample** | Yes — breaks deliberately oversampled | No — prevalence is by construction |
| **Outcome-blind sampling** | No — selected before resolution | Candidate for absolute probabilities *if* the frame matches the claimed universe |
| **Population / research universe** | Defined externally (e.g. all announced US public M&A above a size threshold in a window) | Only if the cohort is a probability sample (or a known design with weights) from that universe |

## Sample prevalence vs population prevalence

- **Sample prevalence** π̂ = n_pos / n_train inside a training set or cohort.
- **Population prevalence** π* = break rate in the claimed research universe.

They coincide only under a known, appropriate sampling design (or after
design-based / model-based reweighting that this repo does **not** currently
implement).

`break_logit_v1` registry fields `prevalence` / `sample_prevalence` record
**sample** prevalence only. They must never be labeled a population break rate.

## Selection on Y (response-based sampling)

If deals are chosen because they closed or broke in interesting ways, the
likelihood is conditional on the selection rule. Standard unweighted MLE for
P(Y=1 | X) does **not** recover population absolute probabilities under
response-based sampling. Discrimination (ranking) may still be informative;
calibration to population π* is not automatic.

## Why a balanced or enriched break sample is not population-calibrated

Deliberately balancing Y=0 and Y=1 (or oversampling breaks) sets π̂ by design.
A logistic model fit on that sample, even with correct features and no leakage,
targets the **sample** conditional distribution. Mapping predictions to
population absolute risk requires either:

1. an outcome-blind draw from a defined universe, or
2. an explicit sampling weight / prior-correction step that is versioned and tested.

Neither is claimed for the current 24-deal corpus.

## Why “more rows” does not fix a biased frame

Increasing N under the same convenience or outcome-enriched rule reduces
variance of estimates **within that biased frame**. It does not identify π*.
A larger biased sample is still biased.

## Current 24-deal corpus (conservative description)

The present reviewed SEC deals are a **reviewer-curated research corpus**:

- selected for evidence quality and class coverage for software / gate testing
- **not** an outcome-blind draw from a defined M&A universe
- observed class prevalence (0.5 at this commit) is **not** a natural population
  break probability

Future large historical packets (including outcome-known candidate lists) may
still enter the **canonical** store after SEC validation. Admission into a
**probability-calibration-eligible** cohort requires an explicit cohort
specification (`outcome_blind`, `probability_calibration_eligible`, selection
method) — not silent conflation with the full canonical table.

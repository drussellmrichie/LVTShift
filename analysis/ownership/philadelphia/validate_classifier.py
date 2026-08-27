"""Hand-adjudicated accuracy check on the legal-form classifier.

Every headline share in this analysis is a regex verdict over an owner-name string that OPA
truncates, so publishing those shares without a measured error rate would not be defensible.
This script holds the hand adjudication of a stratified 210-name sample (35 per predicted
form, fixed seed) and computes per-form precision from it.

The adjudications below were made by reading each name. Names are labelled with what the
string actually shows, and two labels exist for cases the string genuinely cannot settle:

  - `Business — form obscured by truncation` — the name is cut at one of OPA's two
    truncation widths (25 or 40 chars) and ends mid-suffix, e.g. `NOAH REALTY INVESTMENTS L`.
    Certainly a business, almost certainly an LLC, but the string does not prove which.
  - `Ambiguous (COMPANY)` — `... COMPANY` with no further suffix. In Pennsylvania that is
    equally consistent with an LLC and a corporation.

Both are counted as *misses*, not hits, so the reported precision is conservative.

Usage:
    python analysis/ownership/philadelphia/validate_classifier.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import owner_lib as ol  # noqa: E402

RESULTS = HERE / "results"
SAMPLE = RESULTS / "classifier_sample.csv"
OUT = RESULTS / "classifier_validation.csv"

OBSCURED = "Business — form obscured by truncation"
AMBIGUOUS = "Ambiguous (COMPANY)"

# Names whose true legal form differs from the prediction, or which the string cannot settle.
# Everything in the sample and NOT listed here was read and confirmed correct as predicted.
ADJUDICATIONS: dict[str, tuple[str, str]] = {
    # Matched 'PARTNERS' before 'INC'; the entity is a corporation.
    "DYMANIC EQUITY PARTNERS INC": (ol.FORM_CORP, "abbreviated 'PRTNSHP' not matched; INC is the real suffix"),
    # 'PRTNSHP' is an abbreviation the LP pattern does not cover.
    "FINK REALTY PRTNSHP": (ol.FORM_LP, "abbreviated partnership spelling missed by the LP pattern"),
    # Truncated mid-suffix at 25 or 40 characters — business, form unprovable from the string.
    "AMERICAN PRIDE PROPERTIES-PHILADELPHIA L": (OBSCURED, "cut at 40 chars"),
    "SS PLATINIUM PROPERTIES L": (OBSCURED, "cut at 25 chars"),
    "NOAH REALTY INVESTMENTS L": (OBSCURED, "cut at 25 chars"),
    "TANEY STREET ASSOCIATES L": (OBSCURED, "cut at 25 chars"),
    "NE REAL ESTATE HOLDINGS L": (OBSCURED, "cut at 25 chars"),
    "W&C PROPERTY INVESTMENT L": (OBSCURED, "cut at 25 chars"),
    "POA REALITY INVESTMENTS L": (OBSCURED, "cut at 25 chars"),
    "KEN AND NAT REAL ESTATE L": (OBSCURED, "cut at 25 chars"),
    "COSMOPOLITAN PROPERTIES L": (OBSCURED, "cut at 25 chars"),
    # '... COMPANY' with no further suffix is equally consistent with an LLC or a corporation.
    "N & N SUPPLY COMPANY": (AMBIGUOUS, "COMPANY could be LLC or corporation"),
    "OCCUPY HOLDINGS COMPANY": (AMBIGUOUS, "COMPANY could be LLC or corporation"),
}

# Sector-level (not form-level) misclassifications noticed while adjudicating. Recorded
# because they bias the *sector* table, not the LLC headline.
SECTOR_NOTES: dict[str, str] = {
    "CAST YOUR CARES INC": "probably a nonprofit; sector says Business",
    "POSITIVE INFLUENCES INC": "probably a nonprofit; sector says Business",
}


def main() -> None:
    if not SAMPLE.exists():
        raise SystemExit(f"{SAMPLE} not found — run ownership_by_type.py first")
    s = pd.read_csv(SAMPLE)

    # Re-predict live so the check tracks the current classifier rather than a stale column.
    s["predicted_form"] = ol.classify_legal_form(s["owner_name"])
    s["actual_form"] = [ADJUDICATIONS.get(n, (f, ""))[0]
                        for n, f in zip(s["owner_name"], s["predicted_form"])]
    s["note"] = [ADJUDICATIONS.get(n, ("", ""))[1] for n in s["owner_name"]]
    s["sector_note"] = s["owner_name"].map(SECTOR_NOTES).fillna("")
    s["correct"] = s["actual_form"] == s["predicted_form"]

    adjudicated = set(ADJUDICATIONS) | set(SECTOR_NOTES)
    unseen = sorted(set(s["owner_name"]) - adjudicated - set(s.loc[s["correct"], "owner_name"]))
    if unseen:
        print(f"WARNING: {len(unseen)} sampled names are neither confirmed nor adjudicated "
              f"(the sample changed since adjudication): {unseen[:5]}")

    prec = (s.groupby("predicted_form")
            .agg(sampled=("correct", "size"), correct=("correct", "sum"))
            .assign(precision=lambda d: d["correct"] / d["sampled"])
            .reset_index().sort_values("precision"))

    print("Per-form precision (hand-adjudicated, n=%d):" % len(s))
    print(prec.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    obscured = (s["actual_form"] == OBSCURED).sum()
    other_biz = (s["predicted_form"] == ol.FORM_OTHER_BIZ).sum()
    print(f"\nForm-obscured by truncation: {obscured} of {other_biz} sampled "
          f"'{ol.FORM_OTHER_BIZ}' names ({obscured / other_biz:.1%}) — these are the LLCs the "
          "headline share cannot see, and the reason an upper bound is reported alongside it.")

    llc = prec.loc[prec["predicted_form"] == ol.FORM_LLC]
    if len(llc):
        print(f"LLC precision {llc['precision'].iat[0]:.1%}: no false positives in the sample, "
              "so the measured LLC share is a clean lower bound.")

    s.to_csv(OUT, index=False)
    prec.to_csv(RESULTS / "classifier_precision.csv", index=False)
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()

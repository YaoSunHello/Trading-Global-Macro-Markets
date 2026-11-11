"""Multiple-testing adjustments (Holm and Benjamini-Hochberg)."""
from __future__ import annotations

import pandas as pd
from statsmodels.stats.multitest import multipletests


def adjust_pvalues(p: pd.Series, alpha: float = 0.05) -> pd.DataFrame:
    """Holm (FWER) and Benjamini-Hochberg (FDR) adjustments over a family of tests."""
    p = p.astype(float)
    ok = p.notna()
    out = pd.DataFrame(index=p.index, columns=["p_holm", "p_bh", "reject_holm_5pct", "reject_bh_5pct"], dtype=object)
    if ok.sum():
        rh, ph, _, _ = multipletests(p[ok], alpha=alpha, method="holm")
        rb, pb, _, _ = multipletests(p[ok], alpha=alpha, method="fdr_bh")
        out.loc[ok, "p_holm"], out.loc[ok, "p_bh"] = ph, pb
        out.loc[ok, "reject_holm_5pct"], out.loc[ok, "reject_bh_5pct"] = rh, rb
    return out

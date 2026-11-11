"""Formation / availability / execution calendar. One explicit, conservative convention for daily market data."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import CLOSE_HOUR, MARKET_PUBLICATION_HOUR, ts


class Calendar:
    """Monthly decision grid on the ETF session calendar.

    * formation date F_m   = last session of month m (the date the inputs are observed).
    * market availability  = 16:30 ET on the session AFTER the observation date (H.15 release convention).
    * execution            = close of session F_m + `lag` sessions. lag >= 2 is required for the daily FRED/H.15
                             inputs to be public before the trade (lag=2 is the conservative default).
    """

    def __init__(self, sessions: pd.DatetimeIndex, lag: int = 2):
        self.s = pd.DatetimeIndex(sessions).sort_values().unique()
        self.lag = lag
        m = pd.Series(self.s, index=self.s)
        self.formation = pd.DatetimeIndex(m.groupby([self.s.year, self.s.month]).max().values)
        # drop a trailing incomplete month: its last session so far is not the month end
        if self.formation[-1] < self.formation[-1] + pd.offsets.BMonthEnd(0):
            self.formation = self.formation[:-1]
        self.pos = np.array([self.s.get_loc(d) for d in self.formation])

    def exec_date(self, i: int):
        p = self.pos[i] + self.lag
        return self.s[p] if p < len(self.s) else pd.NaT

    @property
    def exec_dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex([self.exec_date(i) for i in range(len(self.formation))])

    def market_availability(self, obs_date) -> pd.Timestamp:
        """When a daily market observation dated `obs_date` is assumed public."""
        p = self.s.searchsorted(pd.Timestamp(obs_date), side="right")   # first session strictly after obs_date
        d = self.s[p] if p < len(self.s) else pd.Timestamp(obs_date) + pd.offsets.BDay(1)
        return ts(d, MARKET_PUBLICATION_HOUR)

    def exec_ts(self, d) -> pd.Timestamp:
        return ts(d, CLOSE_HOUR)

"""Pay rates and labor burden for an employee on a given day.

Union members are paid from the CBA wage schedule; non-union and temporary staff from the employer's
rate card (the CBA says temporary employees are not in the bargaining unit). Burden follows the same
split. Rates come from the contract documents, never from code.

The base rate is the employee's own classification (see decisions log D-06).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from northgate.resolve.names import fold


def pay_schedule(employee: dict) -> str:
    """'union' or 'non_union'."""
    if employee.get("union_member") and (employee.get("employment_type") or "").upper() != "TEMP":
        return "union"
    return "non_union"


@dataclass
class RateBook:
    rates: list[dict]  # rows of the wage_rates table
    burden_pct: dict[str, Decimal]  # schedule -> percent, e.g. {"union": 32}

    def base_rate(self, employee: dict, day: date) -> Decimal | None:
        """Latest rate for the employee's schedule and job class that is in effect on `day`."""
        schedule = pay_schedule(employee)
        job_class = fold(employee.get("job_class"))
        in_effect = [
            r
            for r in self.rates
            if r["schedule"] == schedule
            and fold(r["classification"]) == job_class
            and r["effective_date"] is not None
            and r["effective_date"] <= day
        ]
        if not in_effect:
            return None
        return Decimal(str(max(in_effect, key=lambda r: r["effective_date"])["hourly_rate"]))

    def burden(self, employee: dict) -> Decimal | None:
        """Burden as a fraction (0.32 for 32%)."""
        pct = self.burden_pct.get(pay_schedule(employee))
        return Decimal(str(pct)) / 100 if pct is not None else None

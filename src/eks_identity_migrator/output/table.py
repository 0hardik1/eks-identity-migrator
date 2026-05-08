"""Rich-table renderer for Inventory + VerifyResult."""

from __future__ import annotations

from collections import Counter

from rich.console import Group
from rich.table import Table
from rich.text import Text

from eks_identity_migrator.output.colors import RISK_LABEL, RISK_STYLES
from eks_identity_migrator.types.inventory import Inventory, RiskClassification


def render_inventory_table(inv: Inventory) -> Group:
    """Return a rich renderable for an Inventory: table + summary line."""
    table = Table(
        title=f"IRSA mappings — {inv.cluster.name} ({inv.cluster.region})",
        show_lines=False,
        title_style="bold",
    )
    table.add_column("NAMESPACE", no_wrap=True)
    table.add_column("SA", no_wrap=True)
    table.add_column("ROLE")
    table.add_column("RISK", no_wrap=True)
    table.add_column("FINDINGS", overflow="fold")

    for m in inv.mappings:
        risk_text = Text(RISK_LABEL[m.risk], style=RISK_STYLES[m.risk])
        codes = ", ".join(f.code for f in m.findings) if m.findings else "-"
        table.add_row(m.sa.namespace, m.sa.name, _shorten(m.role_arn), risk_text, codes)

    counts = Counter(m.risk for m in inv.mappings)
    summary = Text.assemble(
        f"{len(inv.mappings)} ServiceAccounts: ",
        (f"{counts[RiskClassification.GREEN]} GREEN", RISK_STYLES[RiskClassification.GREEN]),
        ", ",
        (f"{counts[RiskClassification.YELLOW]} YELLOW", RISK_STYLES[RiskClassification.YELLOW]),
        ", ",
        (f"{counts[RiskClassification.RED]} RED", RISK_STYLES[RiskClassification.RED]),
        ", ",
        (f"{counts[RiskClassification.GRAY]} GRAY", RISK_STYLES[RiskClassification.GRAY]),
    )
    return Group(table, Text(""), summary)


def _shorten(role_arn: str, *, max_len: int = 50) -> str:
    if len(role_arn) <= max_len:
        return role_arn
    return role_arn[: max_len - 3] + "..."

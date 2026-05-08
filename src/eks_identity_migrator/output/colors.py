"""Risk → rich color/style mapping. `Console(no_color=True)` handles --no-color."""

from __future__ import annotations

from rich.style import Style

from eks_identity_migrator.types.inventory import RiskClassification

RISK_STYLES: dict[RiskClassification, Style] = {
    RiskClassification.GREEN: Style(color="green", bold=True),
    RiskClassification.YELLOW: Style(color="yellow", bold=True),
    RiskClassification.RED: Style(color="red", bold=True),
    RiskClassification.GRAY: Style(color="bright_black", bold=True),
}

RISK_LABEL: dict[RiskClassification, str] = {
    RiskClassification.GREEN: "GREEN",
    RiskClassification.YELLOW: "YELLOW",
    RiskClassification.RED: "RED",
    RiskClassification.GRAY: "GRAY",
}

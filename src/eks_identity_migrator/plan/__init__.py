"""Turn an Inventory into a reviewable Plan (and read it back from YAML).

The :func:`generate` step filters the inventory by risk + strategy and
synthesises the actions ``apply`` will perform per ServiceAccount (trust
policy diff, association spec, annotation patch). The output is round-trip
stable YAML — humans can comment rows out before applying.

By default only ``GREEN``-classified mappings produce concrete plan steps;
``YELLOW`` rows appear as ``skip=true`` unless ``--include-yellow`` is set.
``RED`` and ``GRAY`` are always skipped — they need human judgement.
"""

from __future__ import annotations

from eks_identity_migrator.cli.exit_codes import ExitCode


def run(
    *,
    cluster: str,
    region: str | None,
    profile: str | None,
    strategy: str,
    include_yellow: bool,
    out: str,
) -> ExitCode:
    from eks_identity_migrator.plan.entry import run as _run

    return _run(
        cluster=cluster,
        region=region,
        profile=profile,
        strategy=strategy,
        include_yellow=include_yellow,
        out=out,
    )

"""The five scenario domains."""

from __future__ import annotations

from inflatebench.generate.banks import Domain
from inflatebench.generate.domains import coding, office, ops, pipeline, writing

DOMAINS: dict[str, Domain] = {d.name: d for d in (
    coding.DOMAIN, pipeline.DOMAIN, ops.DOMAIN, office.DOMAIN, writing.DOMAIN)}

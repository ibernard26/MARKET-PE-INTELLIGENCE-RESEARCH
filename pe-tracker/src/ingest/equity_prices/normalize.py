"""Bridge normalized observations ↔ target_price_manifest / TargetPricePrint."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from ..historical import SourceRef
from ..target_prices import TargetPricePrint
from .schema import NormalizedEquityObservation


def observation_to_print(o: NormalizedEquityObservation) -> TargetPricePrint:
    """Map normalized observation into the existing ingest writer schema."""
    ts = o.observation_timestamp or f"{o.session_date}T16:00:00"
    known = o.known_at or ts
    ref = SourceRef(
        source_name=o.provider,
        source_identifier=(
            f"{o.provider}:{o.provider_symbol}@{o.session_date}"
            f"?close_field={o.close_field_used}"
            f"&hash={o.provenance_hash()[:16]}"
        ),
        known_at=known,
        source_timestamp=ts,
        company_identifier=(
            f"ticker:{o.ticker or o.provider_symbol}"
            + (f"|cik:{o.target_cik}" if o.target_cik is not None else "")
        ),
    )
    return TargetPricePrint(
        deal_id=o.deal_id,
        observation_timestamp=ts,
        target_price=float(o.close),
        source=ref,
    )


def write_normalized_manifest(
        observations: Iterable[NormalizedEquityObservation],
        path: Path,
        meta: Optional[dict] = None,
) -> Path:
    """Serialize normalized observations to target_price_manifest.json schema."""
    path = Path(path)
    rows = []
    for o in observations:
        p = observation_to_print(o)
        rows.append({
            "deal_id": p.deal_id,
            "observation_timestamp": p.observation_timestamp,
            "target_price": p.target_price,
            "source_name": p.source.source_name,
            "source_identifier": p.source.source_identifier,
            "known_at": p.source.known_at,
            "source_timestamp": p.source.source_timestamp,
            "company_identifier": p.source.company_identifier,
            # Extended normalized fields (backward-compatible extras)
            "session_date": o.session_date,
            "provider": o.provider,
            "provider_symbol": o.provider_symbol,
            "ticker": o.ticker,
            "exchange": o.exchange,
            "adjusted_close": o.adjusted_close,
            "currency": o.currency,
            "close_field_used": o.close_field_used,
            "retrieval_timestamp": o.retrieval_timestamp,
            "corporate_action_note": o.corporate_action_note,
            "provenance_hash": o.provenance_hash(),
        })
    doc = {
        "schema_version": 2,
        "_doc": (
            "Longitudinal target-price prints for spread_stress_v1. "
            "Provider-normalized; never invent prices. "
            "close_field_used documents unadjusted vs adjusted semantics."
        ),
        "meta": meta or {},
        "prints": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return path

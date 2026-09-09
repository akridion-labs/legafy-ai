"""Government verification APIs — checking the user's facts, never the law.

The distinction this module exists to hold
------------------------------------------
API Setu (`apisetu.gov.in`) is the Government of India's API gateway. It is
real, it is official, and it is **not a statute corpus**. What it publishes is a
verification exchange: KYC, document verification, DigiLocker-backed lookups —
*is this PAN real*, *is this registration live*, *does this certificate exist*.

So an API Setu response answers a question about **the caller's own facts**. It
never answers a question about what the law requires. That line is enforced
here rather than trusted:

* a `VerificationResult` is never merged into the grounding matrix;
* it can never raise or lower a traffic-light lane;
* it is not a `SourceDoc` and never reaches the search index;
* it is returned to the caller as what it is — a dated check against a named
  government endpoint.

Get this wrong and the failure is subtle and bad: "the government API says your
GSTIN is active" quietly becomes "the government API says you are compliant".
The first is a fact. The second is legal advice from a lookup service.

What it is genuinely worth
--------------------------
`data/research_registers.json` lists searches a founder must run. Some of those
are lookups a machine can do: is this GSTIN live and does it match the legal
name on the invoice; is this supplier registered on Udyam (which starts a
payment clock); does this CIN exist. With a key configured, those move from
"go and check this yourself" to "checked at 14:32 today, here is the answer and
the endpoint that gave it". Everything else on the checklist stays manual,
because it is judgement, not lookup.

Identifiers are never stored
----------------------------
A GSTIN, PAN or CIN is exactly the identifiable data `app/search/corpus.py`
scrubs out. Verification is call-through only: the identifier goes to the
government endpoint and is not written to any Legafy store, log line or audit
record. Only the outcome is returned, to the caller who already knew the number.

Disabled by default
-------------------
With no key configured, `verify()` returns `NOT_CONFIGURED` and the checklist
item stays manual. No silent degradation, no pretending a check happened.

Endpoints live in data, not code
--------------------------------
`data/gov_api_endpoints.json` maps a check to a path and response fields.
Publishers on API Setu differ in both, and an integration that needs a code
change every time a ministry renames a field is an integration nobody keeps
current.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import httpx

from app.config import REPO_ROOT, get_settings

log = logging.getLogger("legafy.govapi")

ENDPOINT_FILE = REPO_ROOT / "data" / "gov_api_endpoints.json"

# Shape checks only. These say "this could be a GSTIN", never "this is valid" —
# validity is what the API call is for, and guessing it locally would be the
# same error this whole module is built to avoid.
IDENTIFIER_SHAPE: dict[str, re.Pattern[str]] = {
    "gstin": re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d]{2}$"),
    "pan": re.compile(r"^[A-Z]{5}\d{4}[A-Z]$"),
    "cin": re.compile(r"^[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$"),
    "udyam": re.compile(r"^UDYAM-[A-Z]{2}-\d{2}-\d{7}$"),
}


@dataclass(frozen=True)
class VerificationResult:
    """One dated check against one named government endpoint.

    `verified` is deliberately tri-state. None means "we could not check" — an
    outage, a missing key, a rate limit — which is not the same as "not
    registered", and collapsing the two would produce a confident false
    negative about someone's business.
    """

    check: str
    verified: bool | None
    checked_at: str
    endpoint: str
    authority: str
    detail: dict[str, Any] = field(default_factory=dict)
    status: str = "OK"  # OK | NOT_CONFIGURED | BAD_FORMAT | UNAVAILABLE | UNKNOWN_CHECK

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "verified": self.verified,
            "status": self.status,
            "checked_at": self.checked_at,
            "endpoint": self.endpoint,
            "authority": self.authority,
            "detail": self.detail,
            "scope_note": (
                "This is a check on the caller's own registration against a government "
                "endpoint. It is not a statement about what the law requires, it does not "
                "make anything compliant, and it does not change any traffic-light verdict."
            ),
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache(maxsize=1)
def endpoint_map() -> dict[str, dict[str, Any]]:
    if not ENDPOINT_FILE.exists():
        return {}
    return json.loads(ENDPOINT_FILE.read_text(encoding="utf-8")).get("checks", {})


def available_checks() -> list[dict[str, Any]]:
    """What we could verify, and whether a key is configured to actually do it."""
    settings = get_settings()
    configured = bool(settings.gov_api_key)
    return [
        {
            "check": name,
            "authority": spec.get("authority", ""),
            "proves": spec.get("proves", ""),
            "identifier": spec.get("identifier", ""),
            "enabled": configured,
        }
        for name, spec in sorted(endpoint_map().items())
    ]


async def verify(
    check: str, identifier: str, *, client: httpx.AsyncClient | None = None
) -> VerificationResult:
    """Run one verification. Never raises; a failure is a result with a status."""
    spec = endpoint_map().get(check)
    if spec is None:
        return VerificationResult(
            check, None, _now(), "", "",
            {"known_checks": sorted(endpoint_map())}, "UNKNOWN_CHECK",
        )

    settings = get_settings()
    if not settings.gov_api_key:
        return VerificationResult(
            check, None, _now(), spec.get("path", ""), spec.get("authority", ""),
            {
                "hint": "Set LEGAFY_GOV_API_KEY (and LEGAFY_GOV_API_CLIENT_ID if the "
                        "publisher requires one) to enable this check.",
                "meanwhile": spec.get("manual_fallback", "Run this search manually."),
            },
            "NOT_CONFIGURED",
        )

    normalised = identifier.strip().upper().replace(" ", "")
    shape = IDENTIFIER_SHAPE.get(spec.get("identifier", ""))
    if shape and not shape.match(normalised):
        # Refused before it leaves the process: a malformed identifier is a typo,
        # and spending a government API call on it teaches the user nothing.
        return VerificationResult(
            check, None, _now(), spec.get("path", ""), spec.get("authority", ""),
            {"reason": f"Not the shape of a {spec['identifier'].upper()}."},
            "BAD_FORMAT",
        )

    url = settings.gov_api_base_url.rstrip("/") + spec["path"].format(id=normalised)
    headers = {"X-APISETU-APIKEY": settings.gov_api_key, "Accept": "application/json"}
    if settings.gov_api_client_id:
        headers["X-APISETU-CLIENTID"] = settings.gov_api_client_id

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=20.0)
    try:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        # Never log the identifier — the exception text can carry the URL it sits in.
        log.warning("gov api check %s unavailable: %s", check, type(exc).__name__)
        return VerificationResult(
            check, None, _now(), spec["path"], spec.get("authority", ""),
            {
                "error": type(exc).__name__,
                "meaning": "Could not check. This is NOT evidence that the registration "
                           "is absent or invalid.",
                "meanwhile": spec.get("manual_fallback", "Run this search manually."),
            },
            "UNAVAILABLE",
        )
    finally:
        if owns_client:
            await client.aclose()

    # Only the fields the endpoint spec names are surfaced. A verification
    # response can carry a lot of personal data; we return the minimum that
    # answers the question and drop the rest rather than passing it to a model.
    detail = {label: _dig(payload, path) for label, path in spec.get("fields", {}).items()}
    truth_path = spec.get("verified_when", {}).get("path")
    expected = spec.get("verified_when", {}).get("equals")
    verified: bool | None = None
    if truth_path:
        actual = _dig(payload, truth_path)
        verified = None if actual is None else (str(actual).upper() == str(expected).upper())

    return VerificationResult(
        check, verified, _now(), spec["path"], spec.get("authority", ""), detail, "OK"
    )


def _dig(payload: Any, dotted: str) -> Any:
    """Read `a.b.c` out of a nested response, returning None rather than raising."""
    node = payload
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node

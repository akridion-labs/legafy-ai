"""Regional grounding matrix.

Design rules enforced by this module
-----------------------------------
1. STATE-LEVEL ISOLATION. Each Indian state is loaded as its own record with its
   own ``isolation_group``. There is no inheritance between states and no
   "nearest neighbour" fallback. Telangana never answers for Andhra Pradesh.
2. NO UNION-OVER-STATE GENERALISATION. Union instruments are returned in a
   separate ``union`` block, tagged, and are never merged into the state block.
   A caller that wants only state duties can take the state block untouched.
3. UNKNOWN STATE IS AN ERROR, NOT A GUESS. An unrecognised state string raises
   :class:`UnknownJurisdictionError` listing supported codes. Silently defaulting
   to a "similar" state is the exact failure mode this system exists to prevent.
4. EVERY ASSERTION CARRIES PROVENANCE. Instruments expose ``citation_url``,
   ``verification_status`` and an explicit ``penalty_status``. Penalty amounts
   and section numbers are absent by construction until a human verifies them.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT

JURISDICTION_DIR = REPO_ROOT / "data" / "jurisdictions"
UNION_CODE = "IN-CENTRAL"

# Grounding pipelines may only cite these hosts. Anything else is refused by the
# citation guard, which is what keeps "the model found it on a blog" out of a
# compliance artefact.
GLOBAL_SOURCE_WHITELIST: tuple[str, ...] = (
    "indiacode.gov.in",   # migrated from indiacode.nic.in
    "indiacode.nic.in",   # kept: old links in the wild still resolve to a notice
    "egazette.gov.in",
    "mca.gov.in",
    "meity.gov.in",
    "labour.gov.in",
    "incometax.gov.in",
    "gst.gov.in",
    "epfindia.gov.in",
    "esic.gov.in",
    "rbi.org.in",
    "sebi.gov.in",
    "consumeraffairs.nic.in",
    # Court tier — interpretation. Below the gazette by design, and the citable floor.
    "sci.gov.in",
    "judgments.ecourts.gov.in",
    "ecourts.gov.in",
    "tshc.gov.in",
    "aphc.gov.in",
    "bombayhighcourt.nic.in",
    "karnatakajudiciary.kar.nic.in",
    "delhihighcourt.nic.in",
    "nic.in",
    "gov.in",
)


class UnknownJurisdictionError(ValueError):
    """Raised when a state string cannot be resolved to an isolated code path."""

    def __init__(self, raw: str, supported: list[str]) -> None:
        self.raw = raw
        self.supported = supported
        super().__init__(
            f"Jurisdiction '{raw}' is not present in the grounding matrix. "
            f"Supported state code paths: {', '.join(supported)}. "
            "Legafy refuses to approximate an unmapped state with a neighbouring one."
        )


@dataclass(frozen=True)
class Obligation:
    key: str
    summary: str
    lane: str
    instrument_id: str
    instrument_title: str
    authority: str
    citation_url: str
    domain: str
    isolation_group: str
    verification_status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "summary": self.summary,
            "lane": self.lane,
            "instrument_id": self.instrument_id,
            "instrument_title": self.instrument_title,
            "authority": self.authority,
            "citation_url": self.citation_url,
            "domain": self.domain,
            "isolation_group": self.isolation_group,
            "verification_status": self.verification_status,
        }


@dataclass(frozen=True)
class Jurisdiction:
    """One isolated regulatory code path (a state, or the union framework)."""

    code: str
    display_name: str
    isolation_group: str
    tier: str
    seed_compiled_on: str
    verification_status: str
    verification_note: str
    source_whitelist: tuple[str, ...]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def instruments(self) -> list[dict[str, Any]]:
        return list(self.raw.get("instruments", []))

    @property
    def escalation_triggers(self) -> list[str]:
        return list(self.raw.get("state_escalation_triggers", []))

    @property
    def declared_absences(self) -> list[dict[str, Any]]:
        return list(self.raw.get("state_level_absences", []))

    def obligations(self) -> list[Obligation]:
        out: list[Obligation] = []
        for instrument in self.instruments:
            for ob in instrument.get("obligations", []):
                out.append(
                    Obligation(
                        key=ob["key"],
                        summary=ob["summary"],
                        lane=ob.get("lane", "AMBER"),
                        instrument_id=instrument["id"],
                        instrument_title=instrument["title"],
                        authority=instrument.get("authority", "Unspecified authority"),
                        citation_url=instrument.get("citation_url", ""),
                        domain=instrument.get("domain", "general"),
                        isolation_group=self.isolation_group,
                        verification_status=self.verification_status,
                    )
                )
        return out

    def citable_titles(self) -> set[str]:
        return {i["title"] for i in self.instruments}

    def citable_hosts(self) -> set[str]:
        hosts: set[str] = set()
        for url in self.source_whitelist:
            hosts.add(_host_of(url))
        for instrument in self.instruments:
            url = instrument.get("citation_url")
            if url:
                hosts.add(_host_of(url))
        return {h for h in hosts if h}

    def summary(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "display_name": self.display_name,
            "isolation_group": self.isolation_group,
            "tier": self.tier,
            "verification_status": self.verification_status,
            "verification_note": self.verification_note,
            "seed_compiled_on": self.seed_compiled_on,
            "instrument_count": len(self.instruments),
            "source_whitelist": list(self.source_whitelist),
        }


def _host_of(url: str) -> str:
    cleaned = url.split("://", 1)[-1]
    return cleaned.split("/", 1)[0].lower()


class JurisdictionRegistry:
    """Thread-safe loader over ``data/jurisdictions/*.json``."""

    def __init__(self, directory: Path = JURISDICTION_DIR) -> None:
        self._directory = directory
        self._lock = threading.RLock()
        self._by_code: dict[str, Jurisdiction] = {}
        self._alias_index: dict[str, str] = {}
        self._loaded = False

    # -- loading ------------------------------------------------------------
    def load(self, force: bool = False) -> None:
        with self._lock:
            if self._loaded and not force:
                return
            by_code: dict[str, Jurisdiction] = {}
            alias_index: dict[str, str] = {}
            if not self._directory.exists():
                raise FileNotFoundError(f"Jurisdiction directory missing: {self._directory}")
            for path in sorted(self._directory.glob("*.json")):
                if path.name.startswith("_"):
                    continue  # templates and scratch files are not code paths
                payload = json.loads(path.read_text(encoding="utf-8"))
                jur = Jurisdiction(
                    code=payload["code"],
                    display_name=payload["display_name"],
                    isolation_group=payload["isolation_group"],
                    tier=payload.get("tier", "state"),
                    seed_compiled_on=payload.get("seed_compiled_on", ""),
                    verification_status=payload.get("verification_status", "SEED_UNVERIFIED"),
                    verification_note=payload.get("verification_note", ""),
                    source_whitelist=tuple(payload.get("source_whitelist", [])),
                    raw=payload,
                )
                if jur.code in by_code:
                    raise ValueError(f"Duplicate jurisdiction code {jur.code} in {path}")
                by_code[jur.code] = jur
                alias_index[jur.code.lower()] = jur.code
                alias_index[jur.display_name.lower()] = jur.code
                for alias in payload.get("aliases", []):
                    normalised = alias.strip().lower()
                    existing = alias_index.get(normalised)
                    if existing and existing != jur.code:
                        raise ValueError(
                            f"Alias '{alias}' is claimed by both {existing} and {jur.code}. "
                            "Ambiguous aliases break state isolation and are refused."
                        )
                    alias_index[normalised] = jur.code
            if UNION_CODE not in by_code:
                raise ValueError(f"Union framework file {UNION_CODE}.json is required")
            self._by_code = by_code
            self._alias_index = alias_index
            self._loaded = True

    # -- lookup -------------------------------------------------------------
    @property
    def state_codes(self) -> list[str]:
        self.load()
        return sorted(c for c, j in self._by_code.items() if j.tier == "state")

    def union(self) -> Jurisdiction:
        self.load()
        return self._by_code[UNION_CODE]

    def get(self, code: str) -> Jurisdiction:
        self.load()
        return self._by_code[code]

    def resolve(self, raw_state: str) -> Jurisdiction:
        """Resolve a user-supplied state string to exactly one isolated path."""
        self.load()
        if raw_state is None:
            raise UnknownJurisdictionError("<none>", self.state_codes)
        key = " ".join(raw_state.strip().lower().split())
        code = self._alias_index.get(key)
        if code is None:
            raise UnknownJurisdictionError(raw_state, self.state_codes)
        jur = self._by_code[code]
        if jur.tier != "state":
            raise UnknownJurisdictionError(
                raw_state,
                self.state_codes,
            )
        return jur

    def all_summaries(self) -> list[dict[str, Any]]:
        self.load()
        return [j.summary() for j in self._by_code.values()]

    # -- grounding ----------------------------------------------------------
    def build_grounding_payload(
        self,
        raw_state: str,
        activity_flags: set[str] | None = None,
    ) -> dict[str, Any]:
        """Return the segregated grounding block for one state.

        The union block and the state block are returned side by side and are
        never merged. Callers that render prose MUST keep them labelled.
        """
        flags = activity_flags or set()
        state = self.resolve(raw_state)
        union = self.union()

        def _filter(jur: Jurisdiction) -> list[dict[str, Any]]:
            selected: list[dict[str, Any]] = []
            for instrument in jur.instruments:
                applies = set(instrument.get("applies_when", []))
                if applies and flags and not (applies & flags) and "any_entity" not in applies:
                    continue
                # An obligation may narrow its parent instrument's trigger: the
                # Income-tax Act applies to every entity, its ESOP duty does not.
                # Filtered here so every consumer — ledger, duty list, traffic
                # light — sees the same applicable set.
                obligations = [
                    ob
                    for ob in instrument.get("obligations", [])
                    if not ob.get("applies_when") or (set(ob["applies_when"]) & flags)
                ]
                selected.append(
                    {
                        "id": instrument["id"],
                        "title": instrument["title"],
                        "applies_when": sorted(applies),
                        "domain": instrument.get("domain", "general"),
                        "authority": instrument.get("authority", ""),
                        "citation_url": instrument.get("citation_url", ""),
                        "obligations": obligations,
                        "penalty_status": instrument.get("penalty_status", "NOT_VERIFIED"),
                        "penalty_schedule": instrument.get("penalty_schedule"),
                        "commencement_note": instrument.get("commencement_note"),
                        "verified_citations": instrument.get("verified_citations", []),
                    }
                )
            return selected

        return {
            "generated_on": date.today().isoformat(),
            "isolation_contract": (
                "The union block and the state block below are separate code paths. "
                "Union instruments do not override, absorb or substitute for state "
                "instruments, and no state's entry may be read across to another state."
            ),
            "union": {
                "code": union.code,
                "display_name": union.display_name,
                "isolation_group": union.isolation_group,
                "verification_status": union.verification_status,
                "instruments": _filter(union),
            },
            "state": {
                "code": state.code,
                "display_name": state.display_name,
                "isolation_group": state.isolation_group,
                "verification_status": state.verification_status,
                "verification_note": state.verification_note,
                "instruments": _filter(state),
                "declared_absences": state.declared_absences,
                "escalation_triggers": state.escalation_triggers,
            },
            "source_whitelist": sorted(
                set(state.source_whitelist) | set(union.source_whitelist)
            ),
            "citable_hosts": sorted(
                state.citable_hosts() | union.citable_hosts() | set(GLOBAL_SOURCE_WHITELIST)
            ),
            "citable_instrument_titles": sorted(
                state.citable_titles() | union.citable_titles()
            ),
            "provenance_warning": (
                "Instrument titles are seed metadata. Section numbers, thresholds and "
                "penalty amounts are intentionally not stored and must not be asserted "
                "from model memory."
            ),
        }


JURISDICTION_REGISTRY = JurisdictionRegistry()


def resolve_jurisdiction(raw_state: str) -> Jurisdiction:
    return JURISDICTION_REGISTRY.resolve(raw_state)

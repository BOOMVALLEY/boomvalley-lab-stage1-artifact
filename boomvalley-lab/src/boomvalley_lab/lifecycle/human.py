"""The operator's side of a study's human actors (P17, T5-002).

A run asks a person through a desk (``kernel.waiting.HumanDeskV1``): a
directory outside the run's evidence.  The operator does three things there,
each once:

    enroll   say which participant answers as a human actor of the study.  The
             consent terms the participant granted are handed in and their
             SHA-256 is the contract's (BVL-HUMAN-004); the product reads no
             signed form and stores a pseudonym only.
    pending  read the delivered requests that have no answer yet.
    answer   enter the participant's answer to one delivered request.  An
             intent is answered once; a second answer is refused
             (BVL-HUMAN-010).

Nothing here touches a run: the run reads the desk when it is run or resumed,
and what the desk carried becomes evidence only through the call chain.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.kernel.human import HUMAN_CONSENT_NOT_GRANTED, HumanError
from boomvalley_lab.kernel.plugin_registry import PluginType
from boomvalley_lab.kernel.waiting import HumanDeskV1, require_desk_transport
from boomvalley_lab.lifecycle.plugins import resolved
from boomvalley_lab.lifecycle.study import CompiledStudy

LIFECYCLE = "human-desk-1"


def enroll(study: CompiledStudy, desk: Path, *, actor: str, participant: str,
           consent_terms: Path) -> dict[str, Any]:
    if study.humans is None:
        raise HumanError("BVL-HUMAN-003", "the study declares no human actors")
    contract = study.humans.contract(actor)
    require_desk_transport(
        contract, resolved(study.plugins, PluginType.HUMAN_CHANNEL).get(contract.channel)
    )
    terms = str(sha256_bytes(Path(consent_terms).read_bytes()))
    if terms != contract.consent.document_sha256:
        raise HumanError(
            HUMAN_CONSENT_NOT_GRANTED,
            f"{consent_terms} is {terms}; human actor {actor!r} is asked under the terms "
            f"{contract.consent.document_sha256}: consent to other terms is not consent",
        )
    return {"lifecycle": LIFECYCLE, "desk": str(desk), "experiment": study.experiment_id,
            "contract": contract.identity().document(),
            **HumanDeskV1(Path(desk)).enroll(contract, participant)}


def pending(desk: Path) -> dict[str, Any]:
    deliveries = HumanDeskV1(Path(desk)).deliveries()
    return {
        "lifecycle": LIFECYCLE, "desk": str(desk), "delivered": len(deliveries),
        "pending": [
            {key: delivery[key]
             for key in ("intent", "actor", "participant", "channel", "messages", "response")}
            for delivery in deliveries if not delivery["answered"]
        ],
    }


def answer(desk: Path, *, intent: str, text: str, entered_by: str | None) -> dict[str, Any]:
    return {"lifecycle": LIFECYCLE, "desk": str(desk), "answered": True,
            **HumanDeskV1(Path(desk)).answer(intent, text, entered_by)}

"""Protocol DAG and experimental schedule order: two orders, two identities (T2-004).

A run carries two orders that must never stand for each other:

    ProtocolDagIdentity         the intra-episode causal order: the IR's typed
                                nodes, its dependency edges and its round bound
                                (the partial order every evidence lineage and
                                dependency-ready check follows)
    ExperimentScheduleIdentity  the experimental schedule order: which episodes
                                a run executes, in which order

Neither is inside the other's preimage.  The DAG ignores node configuration,
declaration list order and the engine's serialization of independent nodes;
the schedule is nothing but the ordered episode keys.  Neither enters
EpisodeIdentity or StepIdentity (plan x authorization x episode_key / episode x
round x node): moving an episode to another schedule position changes the
schedule, never the episode, its steps or its causal lineage, and a changed
dependency edge changes the DAG (and the plan), never the schedule.

The engine journals both on every EPISODE_OPENED (``protocol_dag``,
``schedule``) and opens episodes only in schedule order (BVL-SCHED-001); both
package verifiers recompute them from the plan's IR and the journal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from boomvalley_lab.core.errors import DeclarationError, ExecutionError
from boomvalley_lab.kernel.identity import ExperimentScheduleIdentity, ProtocolDagIdentity
from boomvalley_lab.kernel.protocol import ProtocolIR

PROTOCOL_DAG_SCHEMA = "bvl-protocol-dag-1"
EXPERIMENT_SCHEDULE_SCHEMA = "bvl-experiment-schedule-1"
# an episode opened at another place than its schedule position
SCHEDULE_ORDER_VIOLATED = "BVL-SCHED-001"


def protocol_dag_document(protocol: ProtocolIR) -> dict[str, Any]:
    """The causal structure of one episode: typed nodes, edges, rounds (canonical)."""

    return {
        "schema": PROTOCOL_DAG_SCHEMA,
        "rounds": protocol.rounds,
        "nodes": sorted(
            ({"id": node.node_id, "kind": node.kind.value} for node in protocol.nodes),
            key=lambda item: item["id"],
        ),
        "edges": sorted(
            [dependency, node.node_id]
            for node in protocol.nodes
            for dependency in node.depends_on
        ),
    }


def protocol_dag_identity(protocol: ProtocolIR) -> ProtocolDagIdentity:
    return ProtocolDagIdentity.of_payload(protocol_dag_document(protocol))


@dataclass(frozen=True)
class ExperimentScheduleV1:
    """The ordered episode keys one run executes."""

    episodes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.episodes, tuple) or not self.episodes:
            raise DeclarationError("an experiment schedule orders at least one episode")
        if any(not isinstance(key, str) or not key for key in self.episodes):
            raise DeclarationError("schedule episode keys are non-empty strings")
        if len(set(self.episodes)) != len(self.episodes):
            raise DeclarationError("a schedule names each episode key once")

    def document(self) -> dict[str, Any]:
        return {"schema": EXPERIMENT_SCHEDULE_SCHEMA, "episodes": list(self.episodes)}

    def identity(self) -> ExperimentScheduleIdentity:
        return ExperimentScheduleIdentity.of_payload(self.document())

    def position(self, episode_key: str) -> int:
        if episode_key not in self.episodes:
            raise ExecutionError(
                f"{SCHEDULE_ORDER_VIOLATED} episode {episode_key!r} is not in the experiment "
                f"schedule {list(self.episodes)}",
                code=SCHEDULE_ORDER_VIOLATED,
            )
        return self.episodes.index(episode_key)

    def opened(self, episode_key: str) -> dict[str, Any]:
        """The ``schedule`` member of the EPISODE_OPENED that opens *episode_key*."""

        return {
            "identity": self.identity().document(),
            "episodes": list(self.episodes),
            "position": self.position(episode_key),
        }

    def require_next(self, episode_key: str, opened: Sequence[Mapping[str, Any]]) -> None:
        """*episode_key* opens next: the run's earlier episodes are its schedule prefix."""

        position = self.position(episode_key)
        mine = self.identity().document()
        earlier = [record.get("episode_key") for record in opened]
        foreign = [r.get("episode_key") for r in opened if (r.get("schedule") or {})
                   .get("identity") != mine]
        if foreign or earlier != list(self.episodes[:position]):
            raise ExecutionError(
                f"{SCHEDULE_ORDER_VIOLATED} episode {episode_key!r} is at schedule position "
                f"{position}; the run opened {earlier}"
                + (f" ({foreign} under another schedule)" if foreign else ""),
                code=SCHEDULE_ORDER_VIOLATED,
            )


def schedule_problems(
    opened: Sequence[Mapping[str, Any]], protocol: ProtocolIR
) -> tuple[list[str], dict[str, Any] | None]:
    """Recompute both orders from the run's EPISODE_OPENED records (verifier side).

    Returns the problems and, when there are none, the attested schedule
    ``{"identity", "episodes"}``.
    """

    problems: list[str] = []
    dag = protocol_dag_identity(protocol).document()
    schedules: list[ExperimentScheduleV1] = []
    for index, record in enumerate(opened):
        name = record.get("episode_key")
        if record.get("protocol_dag") != dag:
            problems.append(
                f"episode {name!r} protocol_dag is not the plan IR's causal order {dag}"
            )
        found = record.get("schedule")
        if not isinstance(found, Mapping) or set(found) != {"identity", "episodes", "position"}:
            problems.append(f"episode {name!r} carries no closed experiment schedule")
            continue
        try:
            schedule = ExperimentScheduleV1(tuple(found["episodes"]))
        except (DeclarationError, TypeError) as error:
            problems.append(f"episode {name!r} schedule is malformed: {error}")
            continue
        if found["identity"] != schedule.identity().document():
            problems.append(f"episode {name!r} schedule identity does not recompute")
        if found["position"] != index or schedule.episodes[index:index + 1] != (name,):
            problems.append(
                f"episode {name!r} is opened {index}th, at schedule position "
                f"{found['position']} of {list(schedule.episodes)}"
            )
        schedules.append(schedule)
    if len(set(schedules)) > 1:
        problems.append("the run's episodes are opened under different experiment schedules")
    elif schedules and len(opened) != len(schedules[0].episodes):
        # SV-03: a run that stopped between two episodes is not the scheduled experiment
        problems.append(
            f"the run opened {len(opened)} of the {len(schedules[0].episodes)} episodes its "
            f"experiment schedule orders; {list(schedules[0].episodes[len(opened):])} never ran"
        )
    if problems or not schedules:
        return problems, None
    return problems, {
        "identity": schedules[0].identity().document(),
        "episodes": list(schedules[0].episodes),
    }

"""FULLMT MANIFEST-4 reader - an independent verifier of BOOMVALLEY Lab manifest-4 packages.

FULLMT is handed a directory whose root holds `MANIFEST-4.json`
(`boomvalley-lab-manifest-4`): the package the current BOOMVALLEY Lab scientific
execution (`bvl-study-1` -> `bvl package`) writes. Like the EPC reader it recomputes
everything it checks from the package bytes alone, with the documented algorithms
(canonical-json-1, SHA-256, ``{"schema", "payload"}`` identity preimages). It shares no
code with the producer: no `boomvalley_lab` module, no BVL helper, builder or verifier,
no subprocess. Python stdlib only.

This module is not an entry point. `epc_reader.py` (the `fullmt` command) looks at the
package root and hands a MANIFEST-4 package here; `EVIDENCE.json` packages keep the
historical EPC reader. Nothing is guessed forward or backward.

What a MANIFEST-4 package means (`meaning` in the result):

    CONFORMANCE
        the manifest lists a conformance attestation, or states the CONFORMANCE
        limitation set. Every rule below is evaluated, ending in this reader's own
        re-derivation of the attestation, which must equal the stored one exactly.
        VERIFIED says the run conformed to its frozen plan and protocol. It is NOT
        scientific evidence and is never reported as such.
    MEMBER_INVENTORY
        a pre-attestation manifest-4 (a bare member list). What such a manifest meant
        when written: these members, these bytes. Only M4-MAN / M4-MEM / M4-CLS are
        evaluated; every conformance rule is NOT_EVALUATED and the result says
        `conformance: NOT_CLAIMED`. It is never upgraded to a conformance claim.
    SCIENTIFIC
        the frozen producer defines no scientific manifest-4 semantics (BVL-REC-102 /
        BVL-REC-104), so this reader has no versioned scientific contract to verify
        against: a manifest claiming `package_class: SCIENTIFIC` is REJECTED (M4-CLS),
        whatever else it holds.

Provenance of the rule set: the rules are the ones BOOMVALLEY Lab froze for its
manifest-4 producer at v1.0.0 (commit db21f4275c512e0b220d8a7ee7889b7bf71296de) and
demonstrated in its two stdlib reference readers: T0-015
(`scripts/fullmt_manifest4_reader.py`, "fullmt-manifest4-spike-reader 0.1.0": M4-MAN ..
M4-ANA) and T5-008 (`scripts/fullmt_p17_reader.py`, "fullmt-manifest4-p17-reader 0.1.0":
the five human / tool member roles, plan-9 / plan-10 and M4-EXT). They were promoted
from those references into this FULLMT-owned module; from here on FULLMT maintains,
tests and releases them. The frozen vectors under fixtures/fullmt_manifest4 hold the
reference outcomes this module is held to (scripts/fullmt/test_manifest4_reader.py).

The producer vocabulary this module reads is the whole one of v1.0.0: every member role
of its manifest-4 (the P17 roles `human_consent`, `human_intent`, `human_response`,
`tool_intent`, `tool_result` included) and every semantic plan it writes, spike-1 and
plan-2 .. plan-10. A later plan schema is not guessed forward: M4-PLN refuses it.

Package access is FULLMT's own (epc_reader.Package): every member is read exactly once,
through a contained, link-free path, and every rule works on those bytes - a file that
changes after it was read cannot change what was verified. Symlinks, junctions and
other reparse points are never followed.

Manifest-4 rules (CONFORMANCE meaning):

    M4-MAN  closed, canonical manifest; schema; plan identity; members in path
            order with portable unique paths; limitations sorted, unique
    M4-MEM  each member: regular file inside the root, SHA-256 and size
    M4-UNL  no file under the root that is not a member (MANIFEST-4.json aside)
    M4-ROL  each member's role is the one its layout place prescribes; evidence
            and request members are canonical and named by their content digest
    M4-CLS  class CONFORMANCE with exactly the CONFORMANCE limitation set
    M4-JRN  journal-2: canonical JSONL, no torn tail, sequence 0..n-1, one run,
            RUN_OPENED at 0 only, no refused/unknown/rejected/failed/aborted event
    M4-AUT  gate-2 CLEARED for the plan; the execution binding and the
            AuthorizationIdentity recompute; RUN_OPENED names exactly them
    M4-PLN  (BVL T4-003: a plan declaring a memory lifecycle declares it on
            every memory_update node in the closed form, over one
            world_transition dependency and a plan actor as owner, carries no
            initial memory, and every memory_artifact source names such a node;
            BVL T4-004: a node may also declare its ``regime_change`` interaction
            (retain / reset; reset only over a World declaring regime events)
            and, under scope ``cross_episode``, its ``carry`` - the ordered
            episodes and the reset boundaries inside them; a World's regime
            (``bvl-world-progression-2``) names declared exogenous event kinds
            and fields of its state schema)
            one plan member recomputes the manifest PlanIdentity and holds one
            closed `bvl-protocol-ir-1` IR in canonical node order, or one
            `bvl-protocol-ir-2` IR whose repetition is a closed round contract
            (safety bound x registered termination rule, BVL T4-001); a
            `bvl-round-contract-2` termination declares the point of the round
            its rule is evaluated at, and a mid-round point is placeable in the
            round body (BVL T4-002)
    M4-EPI  every episode recomputes from plan x authorization x episode_key; its
            STEP_READY sequence is rounds x topological order (StepIdentity
            recomputed), early stop only at a termination node; completed once;
            it names the IR's ProtocolDagIdentity (typed nodes, edges, rounds:
            the causal order) and its place in one experiment schedule (the
            ordered episode keys, a separate identity) - episodes open as the
            schedule's prefix (BVL T2-004); under a round contract every round
            opens on the state the previous one closed on (RoundIdentity
            recomputed) and carries exactly the contract's termination verdict,
            the episode completing at the one TERMINATE (BVL T4-001); under a
            timed contract each verdict is re-derived at its declared point
            (before observation / after decision / after World transition /
            after round-close) from the evidenced state the episode was then
            in, a TERMINATE ends the episode there, and the safety bound ends
            it by a verdict of its own (BVL T4-002)
    M4-CMT  each step carries exactly the commit event its node kind prescribes;
            each dependency's commit event precedes the step's STEP_READY
            (dependency-ready execution, T2-002)
    M4-ART  proposal / decision / memory identities recompute from their content
            and are exactly the ones journal-2 commits, at their step and round;
            under plan-5 (P07) every decision is decision-2; under a plan
            declaring a memory lifecycle (BVL T4-003) every memory member is a
            closed memory-artifact-2, or the memory-artifact-3 of a node
            declaring a regime-change interaction (BVL T4-004)
    M4-CUS  custody entries are canonical; each accepted call recomputes its
            CustodyEntryIdentity, names a request and a response member whose
            bytes are the recorded ones; accepted calls are the actor-call steps
    M4-WLD  each WORLD_APPLIED names its transition / state members; transition,
            intent and post-state identities recompute; one transition per apply;
            under a plan-8 World contract (BVL T3-001) every state is explicit
            and versioned: the episode opens on a ``world_state`` member of the
            plan's initial state, intents (intent-5) and transitions
            (evidence-4) identify their states under the contract's
            ``schema_id:version`` (state identity-2, state evidence-2), every
            pre/post state is a state of that schema, each pre-state is the
            state its episode was in and each round closes on it; a plan
            without a World contract holds none of those documents; under the
            contract (BVL T3-003) every transition's requested
            action is an action of the plan's action schema and its
            requested / admissible / executed actions are one statement of
            ``bvl-world-admissibility-1``, each read as evidenced; under
            contract-3 (BVL T3-004) an intent states its input - NO_ACTION
            exactly for a NO_ACTION decision, within the meaning the contract
            froze - and every transition (transition-2) states whether an
            action was executed and its exogenous events, each of a declared
            kind: a post-state that is not the pre-state follows from an
            executed action or a stated event (``bvl-world-progression-1``),
            and a regime field of a ``bvl-world-progression-2`` moves only
            in a transition stating a declared regime event (BVL T4-004);
            the states of an episode are one chain (BVL T4-005,
            BVL-ROUND-005): it opens on the plan's initial state (episode
            isolation is the one declared reset), every round opens on the
            state the previous one closed on, every transition starts on the
            state its episode is in - its pre- and post-state read from its
            own evidence bytes - and every round closes on the state its last
            transition left; the attestation of a round-contract plan states
            each episode's chain head, re-derived here link by link;
            every committed state is its own canonical serialization read back
            (no null, which the serialization drops) and no two transitions of
            the same World, schema, seed, input and serialized pre-state differ
            (``bvl-world-replay-1``, BVL T3-005: the World's code is not
            replayed here); under contract-4 (BVL T3-006) the plan freezes the
            World's RNG policy (``bvl-world-rng-1``), every intent's seed is the
            world seed the plan's seed tree derives for its episode, round and
            transition, every transition (evidence-4) evidences that policy -
            nothing drawn under DETERMINISTIC, the declared algorithm and its
            draw counts under SEEDED - bound into its identity, and no two
            DETERMINISTIC transitions of the same input and serialized
            pre-state differ, whatever their seeds (BVL-WORLD-013); and (BVL
            T3-007) every World transition is confirmed exactly once: a step
            holds one World intent, each intent consumes one custody entry of
            a call accepted before it in its run and episode and is confirmed
            by one WORLD_APPLIED of its own run, episode, step and round, no
            transition identity or evidence member is confirmed twice
            (BVL-WORLD-012) and no intended apply is left unknown or
            unconfirmed (BVL-WORLD-011)
    M4-LIN  every IR dependency edge is the evidence lineage
            (call -> proposal -> decision -> World intent -> memory); a plan-5
            decision's candidates are the IR's committed proposals of its
            contract's authority, and a builtin rule (single-authority /
            majority / plurality) recomputes to exactly its outcome; a Memory
            Artifact of a lifecycle plan (BVL T4-003) is its node's declared
            owner / key / scope / retention / transform, in its own episode
            and step, valid for exactly the rounds after it that the retention
            names, committed by MEMORY_RECORDED as it stands, and its value is
            the transform of the committed source World transition; an
            artifact-3 (BVL T4-004) also names its episode's key, the declared
            regime-change interaction and exactly the later episodes of the
            declared carry up to the next reset boundary, and the run's
            schedule orders every declared carry's episodes as declared
    M4-RQR  the package holds every evidence role the IR's node kinds require
    M4-ATT  exactly one attestation, and the reader's re-derivation of it from
            the evidence above equals it exactly; a run whose gate-2 decided on
            a P09-ERF coverage attestation (BVL T1-006) holds exactly that
            ``coverage`` member, the reader re-walks the run's plan into the
            attested ERF cell (bvl-erf-inventory-1), recomputes the catalog
            digest and the design's adjacent-isolation comparison set, and
            corroborates request-2 / profile / parser / decision evidence
            against the attested ERF values; a run whose strict gate-2 bound a
            GNDCRW comparison result set (BVL T1-007) holds exactly that
            ``gndcrw_results`` member, and the reader independently rebuilds
            every required edge's five GNDCRW subjects from the attestation and
            holds each edge to one strict CONTROL result over exactly those
            subjects with outcome RUN
    M4-L1C  L1 call bindings (BVL T1-008): when the call intents name
            ``call_binding`` members, every accepted call names exactly one and
            the members are exactly those; each recomputes its CallIdentity
            (episode x step x round x request x the plan actor's provider), its
            ActorIdentity / RoleIdentity / ExecutionProfileIdentity from the
            plan's binding set, the request-2 model / renderer / options /
            seed (re-derived from a plan-7 seed tree, BVL T1-012), and the
            default-deny access trace from the plan's access set
            (an untransformed observation is the source's planned digest; an
            ``actor_output`` source of an access-3 plan, BVL T2-001, is the
            digest of its producer node's committed output in the call's
            round: the accepted response bytes, or the proposal value as
            canonical JSON); request-2 ``upstream`` (BVL T2-003) is exactly,
            per granted ``actor_output`` source, its producer node, the
            producer's committed CallIdentity / ProposalIdentity and that
            digest, and a request observing none carries no ``upstream``;
            a ``memory_artifact`` source of an access-4 plan (BVL T4-003) is
            the digest of its memory_update node's committed Memory Artifacts
            of the call's episode valid in the call's round, request-2
            ``memory`` names exactly those artifacts per granted source, and
            a request observing none carries no ``memory``; under a declared
            carry (BVL T4-004) those artifacts include the ones of the earlier
            carry episodes with no reset boundary in between, and under
            ``regime_change: reset`` none recorded before a committed
            regime-change transition from the round after it on
    M4-L1D  L1 dataset units (BVL T1-008): an L1 package holds exactly one
            ``dataset_units`` member, and the reader's own reconstruction of
            the calls / proposals / decisions / eligibility tables from the
            evidence above equals it byte for byte; a pre-L1 package holds none
    M4-ANA  bound analysis (BVL T1-009): a plan-6 package pre-binds one closed
            ``bvl-analysis-contract-1`` and holds exactly one
            ``analysis_output`` member; the reader admits only the eligible
            decision units of its own dataset reconstruction (and the
            proposals / calls in their lineage), recomputes every declared
            metric with exact rational arithmetic and requires byte equality;
            a package whose plan binds no analysis holds none
    M4-EXT  external actors (P17, BVL T5-001 .. T5-008): every actor call is
            answered by the caller its plan declares, evaluated when every rule
            above passed. Under M4-PLN a plan-9 ``humans`` / plan-10 ``tools``
            member is a closed, canonically ordered set of current contracts
            (``bvl-human-actor-contract-1``; ``bvl-tool-actor-contract-2`` /
            ``-3``) over exactly the plan actors whose frozen binding states the
            reserved human / tool model, the contract's channel / tool as its
            provider and no generation options; no other actor states a reserved
            model; a tool contract selects arguments only from sources its actor
            is granted (T5-PLN-001 .. 005). Here: a human actor's call names one
            ``human_intent`` member whose HumanRequestIntentIdentity recomputes
            and is this step x actor x request under the plan's contract,
            channel and privacy; its participant is a pseudonym asked under one
            GRANTED ``human_consent`` record - named by the intent, its
            HumanConsentIdentity recomputed - of exactly the contract's terms;
            the request is delivered once and answered once, between the call's
            transport and its return, and the journaled delivery is the
            persisted request's messages under the contract; the
            ``human_response`` member recomputes its HumanResponseIdentity,
            answers that intent, participant and consent, states the digest and
            size of the accepted response bytes, and arrived through the
            contract's channel at no less than its minimum provenance grade
            (T5-HUM-001 .. 006). A tool actor's call names its tool intent and
            contract; the step journals that one intent, whose history
            classifies (attempts in order, a mutating tool never called again
            while an earlier attempt is unproven, one result); the
            ``tool_intent`` member recomputes its identity, is this step x
            actor x request under the contract's tool, operation and resource,
            and carries the contract's typed arguments - a constant, or a field
            of an actor_output source re-derived from what the round committed;
            a field of a frozen source is held to one value across the run; the
            ``tool_result`` member recomputes the journaled identity, answers
            that intent in the contract's result type, and the accepted
            response bytes are exactly the ones it derives (T5-TOOL-001 .. 005).
            A member is an exchange's only when a journal-2 record of that
            exchange names it by content address: an intent, response or result
            named by two exchanges is refused (T5-EXT-003), and no HUMAN_* /
            TOOL_* record and no human / tool member exists that no declared
            exchange accounts for; a model actor's call carries none
            (T5-EXT-001, T5-EXT-002)

What this reader does not establish is stated in the result, never implied
(`limitations.consumer`): the World's code is not replayed, model calls are not
re-executed, build / plugin-set identities and gate inputs are producer statements,
and nothing is signed. For a package a person or a tool took part in: nobody is asked
and no tool is called here; that the pseudonym is the person, that the operator entered
what was said and that a receipt corresponds to a change on a site are not re-derived
(`HUMAN_AND_TOOL_ACTS_NOT_REENACTED`); an argument selected from a frozen resource is
held to one value across the run, because a package holds a frozen resource by digest.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from fractions import Fraction

from fullmt_codes import ErrorCode, Outcome, RuleStatus
from fullmt_rules import M4_RULES

READER_NAME = "fullmt-manifest4-reader"
RESULT_SCHEMA = "fullmt-manifest4-verification-result/1"
HANDLER = "verify_manifest_4"
# the producer contract these rules were frozen against (provenance, never executed)
PRODUCER_CONTRACT = {"repository": "boomvalley-lab", "tag": "v1.0.0",
                     "commit": "db21f4275c512e0b220d8a7ee7889b7bf71296de"}

VERIFIED, REJECTED, ERROR = Outcome.VERIFIED, Outcome.REJECTED, Outcome.ERROR
PASS, FAIL, NOT_EVALUATED = RuleStatus.PASS, RuleStatus.FAIL, RuleStatus.NOT_EVALUATED
CONFORMANCE, MEMBER_INVENTORY = "CONFORMANCE", "MEMBER_INVENTORY"

MANIFEST_4 = "MANIFEST-4.json"
MANIFEST_4_SCHEMA = "boomvalley-lab-manifest-4"
MANIFEST_KEYS = {"schema", "package_class", "plan", "members", "limitations"}
MEMBER_KEYS = {"path", "role", "digest", "size"}
PACKAGE_CLASSES = {"CONFORMANCE", "SCIENTIFIC"}
ROLES = {"plan", "execution_binding", "class_manifest", "plugin_manifest", "request",
         "response", "custody", "proposal", "decision", "world_transition", "world_state",
         "memory", "episode_lineage", "coverage", "gndcrw_results", "gate",
         "analysis_binding", "analysis_output", "conformance_attestation",
         "call_binding", "dataset_units",
         # P17 (BVL T5-002 / T5-004): the consent record, request intent and response
         # of a human actor call; the intent and the result of a tool call
         "human_consent", "human_intent", "human_response", "tool_intent", "tool_result"}
# SV-06: roles with no ``evidence-v2/<role>/`` member - four have their own place in the
# layout, three are written by nothing in K0.  No rule below reads such a member, so a
# file put there is not evidence the reader can vouch for.
UNPLACED_ROLES = {"request", "response", "custody", "episode_lineage", "analysis_binding",
                  "class_manifest", "plugin_manifest"}
CONFORMANCE_LIMITATIONS = ["CONFORMANCE_PACKAGE_NOT_SCIENTIFIC_EVIDENCE",
                           "FULLMT_MANIFEST4_SPIKE_READER_REQUIRED",
                           "GATE2_INPUTS_SUPPLIED_NOT_DERIVED",
                           "PLUGIN_SET_NOT_ENGINE_RESOLVED"]

ATTESTATION_SCHEMA = "boomvalley-lab-conformance-attestation-1"
PLAN_EVIDENCE_SCHEMA = "boomvalley-lab-plan-evidence-1"
SEMANTIC_PLAN_SCHEMA = "boomvalley-lab-semantic-plan-spike-1"
SEMANTIC_PLAN_KEYS = {"schema", "experiment_id", "protocol", "initial_world_state",
                      "initial_memory"}
# plan-2 (BVL T1-001) adds resolved P04 actor bindings; spike-1 keeps its meaning
SEMANTIC_PLAN_SCHEMA_2 = "boomvalley-lab-semantic-plan-2"
# plan-3 (BVL T1-002) adds the resolved P05 default-deny information access
SEMANTIC_PLAN_SCHEMA_3 = "boomvalley-lab-semantic-plan-3"
# plan-4 (BVL T1-004) adds the P06 proposal contracts; information stays optional
SEMANTIC_PLAN_SCHEMA_4 = "boomvalley-lab-semantic-plan-4"
# plan-5 (BVL T1-005) adds the P07 decision contracts over plan-4
SEMANTIC_PLAN_SCHEMA_5 = "boomvalley-lab-semantic-plan-5"
# plan-6 (BVL T1-009) pre-binds the official analysis over plan-5
SEMANTIC_PLAN_SCHEMA_6 = "boomvalley-lab-semantic-plan-6"
SEMANTIC_PLAN_SHAPES = {
    SEMANTIC_PLAN_SCHEMA: (SEMANTIC_PLAN_KEYS,),
    SEMANTIC_PLAN_SCHEMA_2: (SEMANTIC_PLAN_KEYS | {"actors"},),
    SEMANTIC_PLAN_SCHEMA_3: (SEMANTIC_PLAN_KEYS | {"actors", "information"},),
    SEMANTIC_PLAN_SCHEMA_4: (SEMANTIC_PLAN_KEYS | {"actors", "proposals"},
                             SEMANTIC_PLAN_KEYS | {"actors", "information", "proposals"}),
    SEMANTIC_PLAN_SCHEMA_5: (SEMANTIC_PLAN_KEYS | {"actors", "proposals", "decisions"},
                             SEMANTIC_PLAN_KEYS | {"actors", "information", "proposals",
                                                   "decisions"})}
# plan-6 pre-binds the official analysis over any actor plan (2..5)
SEMANTIC_PLAN_SHAPES[SEMANTIC_PLAN_SCHEMA_6] = tuple(
    shape | {"analysis"} for schema in (SEMANTIC_PLAN_SCHEMA_2, SEMANTIC_PLAN_SCHEMA_3,
                                        SEMANTIC_PLAN_SCHEMA_4, SEMANTIC_PLAN_SCHEMA_5)
    for shape in SEMANTIC_PLAN_SHAPES[schema])
# plan-7 (BVL T1-012) binds the K0 seed tree over any actor plan (2..6)
SEMANTIC_PLAN_SCHEMA_7 = "boomvalley-lab-semantic-plan-7"
SEMANTIC_PLAN_SHAPES[SEMANTIC_PLAN_SCHEMA_7] = tuple(
    shape | {"seed"} for schema in (SEMANTIC_PLAN_SCHEMA_2, SEMANTIC_PLAN_SCHEMA_3,
                                    SEMANTIC_PLAN_SCHEMA_4, SEMANTIC_PLAN_SCHEMA_5,
                                    SEMANTIC_PLAN_SCHEMA_6)
    for shape in SEMANTIC_PLAN_SHAPES[schema])
# plan-8 (BVL T3-001) freezes the World contract over a seeded plan (7)
SEMANTIC_PLAN_SCHEMA_8 = "boomvalley-lab-semantic-plan-8"
SEMANTIC_PLAN_SHAPES[SEMANTIC_PLAN_SCHEMA_8] = tuple(
    shape | {"world"} for shape in SEMANTIC_PLAN_SHAPES[SEMANTIC_PLAN_SCHEMA_7])
# plan-9 (BVL T5-001) freezes the P17 human actor contracts over a seeded plan (7, 8)
SEMANTIC_PLAN_SCHEMA_9 = "boomvalley-lab-semantic-plan-9"
SEMANTIC_PLAN_SHAPES[SEMANTIC_PLAN_SCHEMA_9] = tuple(
    shape | {"humans"} for schema in (SEMANTIC_PLAN_SCHEMA_7, SEMANTIC_PLAN_SCHEMA_8)
    for shape in SEMANTIC_PLAN_SHAPES[schema])
# plan-10 (BVL T5-003) freezes the P17 tool actor contracts over a seeded plan (7, 8, 9)
SEMANTIC_PLAN_SCHEMA_10 = "boomvalley-lab-semantic-plan-10"
SEMANTIC_PLAN_SHAPES[SEMANTIC_PLAN_SCHEMA_10] = tuple(
    shape | {"tools"} for schema in (SEMANTIC_PLAN_SCHEMA_7, SEMANTIC_PLAN_SCHEMA_8,
                                     SEMANTIC_PLAN_SCHEMA_9)
    for shape in SEMANTIC_PLAN_SHAPES[schema])
# contract-2 (BVL T3-003) also froze the World's action schema and the closed
# admissibility vocabulary its transitions state their three actions under;
# contract-3 (BVL T3-004) freezes what NO_ACTION means to the World and the
# exogenous event kinds it may state; contract-4 (BVL T3-006) freezes whether
# its transitions may be random and through which generator
WORLD_CONTRACT_SCHEMA = "bvl-world-contract-4"
WORLD_RNG = "bvl-world-rng-1"
WORLD_RNG_ALGORITHM = "bvl-rng-sha256-ctr-1"
WORLD_RNG_EVIDENCE = "bvl-world-rng-evidence-1"
WORLD_PROGRESSION = "bvl-world-progression-1"
WORLD_PROGRESSION_2 = "bvl-world-progression-2"  # BVL T4-004: declares a regime
WORLD_NO_ACTION_MEANINGS = ("UNDECLARED", "NO_TRANSITION", "EXOGENOUS_PROGRESSION",
                            "NULL_ACTION")
WORLD_ACTION_INPUTS = ("ACTION", "NO_ACTION")
WORLD_TRANSITION_BODY = {False: "bvl-world-transition-1", True: "bvl-world-transition-2"}
WORLD_TRANSITION_BODY_KEYS = {"schema", "requested_action", "admissibility_verdict",
                              "admissible_action", "executed_action", "pre_state",
                              "post_state", "outcome"}
WORLD_PROGRESSION_KEYS = {"action_input", "executed", "exogenous_events"}
WORLD_STATE_SCHEMA_SCHEMA = "bvl-world-state-schema-1"
WORLD_ACTION_SCHEMA_SCHEMA = "bvl-world-action-schema-1"
WORLD_ADMISSIBILITY = "bvl-world-admissibility-1"
WORLD_ADMISSIBILITY_VERDICTS = ("ADMISSIBLE", "CLIPPED", "INADMISSIBLE")
WORLD_ACTION_ROLES = ("requested_action", "admissible_action", "executed_action")
WORLD_STATE_SERIALIZATION = "bvl-canonical-json-1"
WORLD_STATE_FIELD_TYPES = {"integer", "number", "string", "boolean", "object", "array"}
WORLD_STATE_IDENTITY_2 = "bvl-world-state-identity-2"
WORLD_STATE_EVIDENCE = {False: "boomvalley-lab-world-state-evidence-1",
                        True: "boomvalley-lab-world-state-evidence-2"}
# intent-5 carries the exact action handed to the World (BVL T3-002) and
# whether that input is an action or NO_ACTION (BVL T3-004)
WORLD_INTENT = {False: "boomvalley-lab-world-intent-2", True: "boomvalley-lab-world-intent-5"}
WORLD_INTENT_KEYS = {"schema", "episode", "step", "round", "node", "decision",
                     "source_custody", "world", "seed", "pre_state", "state_schema", "action",
                     "action_input"}
WORLD_TRANSITION_EVIDENCE = {False: "boomvalley-lab-world-transition-evidence-2",
                             True: "boomvalley-lab-world-transition-evidence-4"}
WORLD_TRANSITION_KEYS = {"schema", "identity", "intent", "world", "decision", "seed",
                         "transition"}
WORLD_STATE_CHECK = "world_states_versioned_and_chained"
WORLD_ACTION_CHECK = "world_action_evidenced_before_apply"
WORLD_ADMISSIBILITY_CHECK = "world_admissibility_preserved"
WORLD_PROGRESSION_CHECK = "world_progression_explicit"
WORLD_REPLAY_CHECK = "world_transitions_replayable"
WORLD_RNG_CHECK = "world_rng_bound"
WORLD_CUSTODY_CHECK = "world_transitions_confirmed_once"
SEED_TREE_SCHEMA = "bvl-seed-tree-1"
SEED_POLICY_PER_ACTOR = "bvl-seed-actor-1"
PROPOSAL_CONTRACT_SET_SCHEMA = "bvl-proposal-contract-set-1"
PROPOSAL_CONTRACT_SCHEMA = "bvl-proposal-contract-1"
PROPOSAL_SCHEMA_SCHEMA = "bvl-proposal-schema-1"
PROPOSAL_CONTRACT_KEYS = {"schema", "node_id", "proposal_schema", "parser", "config",
                          "on_invalid"}
PROPOSAL_SCHEMA_KEYS = {"schema", "schema_id", "version", "fields", "allow_no_action"}
PROPOSAL_FIELD_TYPES = {"integer", "number", "string", "boolean"}
PROPOSAL_EVIDENCE_1 = "boomvalley-lab-proposal-1"
PROPOSAL_EVIDENCE_2 = "boomvalley-lab-proposal-2"
DECISION_CONTRACT_SET_SCHEMA = "bvl-decision-contract-set-1"
DECISION_CONTRACT_SCHEMA = "bvl-decision-contract-1"
DECISION_CONTRACT_KEYS = {"schema", "node_id", "rule", "authority", "candidates", "config",
                          "on_unresolved"}
DECISION_EVIDENCE_1 = "boomvalley-lab-decision-1"
DECISION_EVIDENCE_2 = "boomvalley-lab-decision-2"
SINGLE_AUTHORITY = "builtin.single-authority:1"
MAJORITY = "builtin.majority:1"
PLURALITY = "builtin.plurality:1"
# the bounded revision block's endorsement rule (BVL T2-005)
VETO = "builtin.veto:1"
BUILTIN_RULES = (SINGLE_AUTHORITY, MAJORITY, PLURALITY, VETO)
# codes an unresolved rule outcome may carry (P07 §8: 003 / 006 / 007)
UNRESOLVED_CODES = {"BVL-DEC-003", "BVL-DEC-006", "BVL-DEC-007"}
INFORMATION_ACCESS_SCHEMA = "bvl-information-access-1"
# access-2 (BVL T1-003) adds per-grant registered transforms of the P05 pipeline
INFORMATION_ACCESS_SCHEMA_2 = "bvl-information-access-2"
# access-3 (BVL T2-001) adds actor_output sources naming a producer IR node
INFORMATION_ACCESS_SCHEMA_3 = "bvl-information-access-3"
# access-4 (BVL T4-003) adds memory_artifact sources naming a memory_update node
INFORMATION_ACCESS_SCHEMA_4 = "bvl-information-access-4"
INFORMATION_ACTOR_OUTPUT_KEYS = {"source_id", "source_kind", "producer"}
PRODUCED_SOURCE_KINDS = ("actor_output", "memory_artifact")
MEMORY_ARTIFACT_1 = "boomvalley-lab-memory-artifact-1"
MEMORY_ARTIFACT_2 = "boomvalley-lab-memory-artifact-2"
MEMORY_ARTIFACT_3 = "boomvalley-lab-memory-artifact-3"  # BVL T4-004
MEMORY_OBSERVATION_SCHEMA = "bvl-memory-observation-1"
MEMORY_CHECK = "memory_artifact_lifecycle_is_explicit_p05_source"
MEMORY_LIFECYCLE_KEYS = {"owner", "key", "scope", "retention", "transform"}
MEMORY_SCOPES = ("episode", "cross_episode")
MEMORY_REGIME_INTERACTIONS = ("retain", "reset")
MEMORY_TRANSFORMS = ("builtin.outcome-memory-v2:1",)
MEMORY_FIELDS_2 = ("episode", "step", "round", "owner", "key", "scope", "retention",
                   "transform", "source_transition", "valid", "value")
MEMORY_FIELDS_3 = (*MEMORY_FIELDS_2, "episode_key", "regime_change")
ACTOR_OUTPUT_PRODUCERS = {"actor_call", "proposal_parse"}
INFORMATION_TRANSFORM_KEYS = {"actor_id", "source_id", "transform", "config"}
INFORMATION_SOURCE_KEYS = {"source_id", "source_kind", "content_sha256", "size"}
ACTOR_BINDING_SET_SCHEMA = "bvl-actor-binding-set-1"
ACTOR_PROFILE_SCHEMA = "bvl-actor-execution-profile-1"
ACTOR_PROFILE_KEYS = {"schema", "provider", "model", "options", "seed_policy", "renderer"}
PROTOCOL_SCHEMA = "bvl-protocol-ir-1"
# BVL T4-001: a protocol whose repetition is a typed round contract
PROTOCOL_SCHEMA_2 = "bvl-protocol-ir-2"
ROUND_CONTRACT_SCHEMA = "bvl-round-contract-1"
TERMINATION_VERDICT_SCHEMA = "bvl-termination-verdict-1"
FIXED_COUNT_RULE = "builtin.fixed-count:1"
ROUND_CHECK = "round_contract_terminates_as_planned"
# BVL T4-005: World(t) -> World(t+1), one chain of states per episode
STATE_CHAIN_CHECK = "world_state_chain_continuous_across_rounds"
STATE_CHAIN_RULE = "post_state(round t) == pre_state(round t+1)"
STATE_CHAIN_MISMATCH = "BVL-ROUND-005"
# BVL T4-002: a contract whose termination declares its timing
ROUND_CONTRACT_SCHEMA_2 = "bvl-round-contract-2"
TERMINATION_VERDICT_SCHEMA_2 = "bvl-termination-verdict-2"
STATE_PREDICATE_RULE = "builtin.state-predicate:1"
TERMINAL_STATE_RULE = "builtin.terminal-state:1"
TIMINGS = ("before_observation", "after_decision", "after_world_transition",
           "after_round_close")
TIMING_ANCHOR_KIND = {"after_decision": "decision",
                      "after_world_transition": "world_transition"}
TERMINATING_REASONS = {"FIXED_COUNT_REACHED", "STATE_PREDICATE_HOLDS", "TERMINAL_STATE_SUCCESS",
                       "TERMINAL_STATE_FAILURE", "SAFETY_BOUND_REACHED"}
GATE_SCHEMA = "boomvalley-lab-gate-2"
GATE_KEYS = {"schema", "plan", "coverage", "gndcrw_results", "policy_identity", "decision",
             "reasons"}
JOURNAL_SCHEMA = "boomvalley-lab-journal-2"
REF_SCHEMA = "boomvalley-lab-evidence-document-ref-2"
REQUEST_REF_SCHEMA = "boomvalley-lab-request-ref-2"

# Identity preimage schemas: identity = SHA-256(canonical({"schema", "payload"})).
ID_SCHEMA = {"plan": "bvl-plan-identity-1", "episode": "bvl-episode-identity-1",
             "step": "bvl-step-identity-1", "gate_decision": "bvl-gate-decision-identity-1",
             "execution_binding": "bvl-execution-binding-identity-1",
             "authorization": "bvl-authorization-identity-1",
             "custody_entry": "bvl-custody-entry-identity-2",
             "proposal": "bvl-proposal-identity-1", "decision": "bvl-decision-identity-1",
             "memory_artifact": "bvl-memory-artifact-identity-1",
             "world_state": "bvl-world-state-identity-1",
             "world_transition_intent": "bvl-world-transition-intent-identity-1",
             "world_transition": "bvl-world-transition-identity-1",
             "build": "bvl-build-identity-1", "plugin_set": "bvl-plugin-set-identity-1",
             "evidence_manifest": "bvl-evidence-manifest-identity-1",
             "coverage_attestation": "bvl-coverage-attestation-identity-1",
             "gndcrw_result_set": "bvl-gndcrw-result-set-identity-1",
             "call": "bvl-call-identity-1", "role": "bvl-role-identity-1",
             "actor": "bvl-actor-identity-1",
             "execution_profile": "bvl-execution-profile-identity-1",
             "protocol_dag": "bvl-protocol-dag-identity-1",
             "experiment_schedule": "bvl-experiment-schedule-identity-1",
             "round": "bvl-round-identity-1",
             "termination_rule": "bvl-termination-rule-identity-1",
             # P17 (BVL T5-001 / T5-003): the contract, consent, intent and response of
             # a human actor; the contract, intent and result of a tool actor, per effect
             "human_actor_contract": "bvl-human-actor-contract-identity-1",
             "human_consent": "bvl-human-consent-identity-1",
             "human_request_intent": "bvl-human-request-intent-identity-1",
             "human_response": "bvl-human-response-identity-1",
             "tool_actor_contract": "bvl-tool-actor-contract-identity-1",
             "tool_read_intent": "bvl-tool-read-intent-identity-1",
             "tool_mutation_intent": "bvl-tool-mutation-intent-identity-1",
             "tool_read_result": "bvl-tool-read-result-identity-1",
             "tool_mutation_result": "bvl-tool-mutation-result-identity-1"}

NODE_KINDS = ("actor_call", "proposal_parse", "decision", "world_transition",
              "memory_update", "termination")
COMMIT_EVENT = {"actor_call": "CUSTODY_ACCEPTED", "proposal_parse": "PROPOSAL_PARSED",
                "decision": "DECISION_RECORDED", "world_transition": "WORLD_APPLIED",
                "memory_update": "MEMORY_RECORDED"}
BASE_ROLES = {"plan", "execution_binding", "gate", "episode_lineage",
              "conformance_attestation"}
KIND_ROLES = {"actor_call": {"request", "response", "custody"},
              "proposal_parse": {"proposal"}, "decision": {"decision"},
              "world_transition": {"world_transition", "world_state"},
              "memory_update": {"memory"}, "termination": set()}
NON_CONFORMANT = {"PRE_TRANSPORT_REFUSED", "CALL_OUTCOME_UNKNOWN", "RESPONSE_REJECTED",
                  "PROPOSAL_PARSE_FAILED", "DECISION_FAILED",
                  "WORLD_OUTCOME_UNKNOWN", "EPISODE_FAILED", "RUN_ABORTED", "RUN_REFUSED"}
ATTESTED_CHECKS = ["authorization_reconciled", "plan_recomputes_and_parses_to_protocol_ir",
                   "episode_identities_recompute", "protocol_dag_and_schedule_order_separate",
                   "step_coverage_equals_protocol_ir",
                   "one_commit_event_per_step_by_node_kind",
                   "ir_dependency_edges_are_evidence_lineage",
                   "artifact_identities_recompute", "custody_reconciled",
                   "world_transitions_reconciled"]
PROPOSAL_FIELDS_1 = ("episode", "step", "round", "call", "response_artifact", "parser",
                     "value")
# proposal-2 (BVL T1-004) binds the plan's P06 contract, the verdict and the reason
PROPOSAL_FIELDS = {PROPOSAL_EVIDENCE_1: PROPOSAL_FIELDS_1,
                   PROPOSAL_EVIDENCE_2: (*PROPOSAL_FIELDS_1, "contract", "verdict", "reason")}
DECISION_FIELDS_1 = ("episode", "step", "round", "rule", "selected_proposal",
                     "requested_action")
# decision-2 (BVL T1-005) binds the plan's P07 contract, candidates and outcome
DECISION_FIELDS = {DECISION_EVIDENCE_1: DECISION_FIELDS_1,
                   DECISION_EVIDENCE_2: ("episode", "step", "round", "rule", "contract",
                                         "candidates", "outcome", "selected_proposal",
                                         "supporting_proposals", "requested_action", "tally",
                                         "reason")}
ARTIFACT_FIELDS = {
    "proposal": ("proposal", PROPOSAL_FIELDS_1),
    "decision": ("decision", ("episode", "step", "round", "rule", "selected_proposal",
                              "requested_action")),
    "memory": ("memory_artifact", ("owner", "source_transition", "transform", "round",
                                   "value")),
}
MEMORY_FIELDS_1 = ARTIFACT_FIELDS["memory"][1]

RULES = ("M4-MAN", "M4-MEM", "M4-UNL", "M4-ROL", "M4-CLS", "M4-JRN", "M4-AUT", "M4-PLN",
         "M4-EPI", "M4-CMT", "M4-ART", "M4-CUS", "M4-WLD", "M4-LIN", "M4-L1C", "M4-RQR",
         "M4-ATT", "M4-L1D", "M4-ANA", "M4-EXT")
INVENTORY_RULES = ("M4-MAN", "M4-MEM", "M4-CLS")
HEX = set("0123456789abcdef")
SEGMENT = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")


class Refused(Exception):
    """Not a package this reader can act on -> outcome ERROR with a stable code, never a
    verdict."""

    def __init__(self, code: ErrorCode, detail: str):
        code = ErrorCode(code)
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


class Malformed(ValueError):
    """A document is not strict JSON / not canonical-json-1."""


# ------------------------------------------------------------ bytes and identities
def _pairs(pairs):
    out = {}
    for name, value in pairs:
        if name in out:
            raise Malformed(f"duplicate member {name!r}")
        out[name] = value
    return out


def _constant(name):
    raise Malformed(f"{name} is not JSON")


def parse(data: bytes):
    """Strict JSON: UTF-8 without BOM, no duplicate member, no NaN / Infinity."""
    if data.startswith(b"\xef\xbb\xbf"):
        raise Malformed("BOM")
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Malformed(str(error)) from None


def _check(value, path="$"):
    if isinstance(value, float) and (not math.isfinite(value) or value == 0.0
                                     and math.copysign(1.0, value) < 0):
        raise Malformed(f"{path}: no canonical form")
    if isinstance(value, dict):
        for name, item in value.items():
            if item is None:
                raise Malformed(f"{path}.{name}: null never appears in canonical-json-1")
            _check(item, f"{path}.{name}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check(item, f"{path}[{index}]")


def canonical(value) -> bytes:
    """canonical-json-1 as the manifest-4 producer froze it (integers are not bounded:
    a seed-tree seed is a 64-bit integer)."""
    _check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def strict(data: bytes):
    """Strict JSON whose bytes are canonical-json-1 at rest."""
    value = parse(data)
    if canonical(value) != data:
        raise Malformed("not canonical-json-1 at rest")
    return value


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def omit_absent(value):
    """canonical-json-1's one omission rule: a mapping entry whose value is None."""
    if isinstance(value, dict):
        return {name: omit_absent(item) for name, item in value.items() if item is not None}
    if isinstance(value, list):
        return [omit_absent(item) for item in value]
    return value


def identity(kind: str, payload) -> dict:
    """``{"kind", "digest"}`` of a K0 identity, recomputed from its payload."""
    payload = omit_absent(payload)
    return {"kind": kind,
            "digest": sha(canonical({"schema": ID_SCHEMA[kind], "payload": payload}))}


def world_state_identity(state, state_schema: str | None) -> dict:
    """A World state's identity: identity-2 under a schema version, identity-1 without."""
    if state_schema is None:
        return identity("world_state", state)
    payload = omit_absent({"state_schema": state_schema, "state": state})
    return {"kind": "world_state",
            "digest": sha(canonical({"schema": WORLD_STATE_IDENTITY_2, "payload": payload}))}


def state_chain(records: list, origin: dict, state_schema: str | None, documents: dict):
    """BVL T4-005: every episode's World states as one chain, and why they are not.

    *origin* is the identity of the plan's initial state; *documents* the
    package's evidence members by path.  Each transition's states are read
    from its own ``world_transition`` member.  Returns the BVL-ROUND-005
    problems and what a conformance attestation states of the chain: per
    episode its rounds, transitions, final state and the digest every link
    was folded into.
    """
    problems, episodes, total = [], {}, 0

    def fold(head: str, link: dict) -> str:
        return hashlib.sha256(canonical({"previous": head, "link": link})).hexdigest()

    def stated(body, role: str):
        value = body.get(role) if isinstance(body, dict) else None
        return world_state_identity(value, state_schema) if isinstance(value, dict) else None

    def broken(where: str, detail: str) -> None:
        problems.append(f"{where} {detail} ({STATE_CHAIN_MISMATCH})")

    for opened in (r for r in records if r["event"] == "EPISODE_OPENED"):
        name = f"episode {opened.get('episode_key')!r}"
        held = opened.get("initial_state")
        if state_schema is not None and (not isinstance(held, dict)
                                         or held.get("identity") != origin):
            broken(f"{name} EPISODE_OPENED #{opened['sequence']}",
                   "does not open on the plan's initial state, and no World state is "
                   "declared to cross an episode")
        mine = [r for r in records if r.get("episode") == opened["episode"]
                and r["sequence"] > opened["sequence"]]
        identified = any(r["event"] == "ROUND_OPENED" for r in mine)
        current, closed, opened_round, intents = origin, 0, None, {}
        head = fold("", {"kind": "origin", "origin": "plan_initial_state", "state": origin})
        links = applied = 0
        for record in mine:
            where = f"{name} {record['event']} #{record['sequence']}"
            in_round = record.get("round") == closed + 1 and (
                not identified or opened_round == record.get("round"))
            if record["event"] == "ROUND_OPENED":
                if opened_round is not None or record.get("round") != closed + 1:
                    broken(where, f"does not open the round after round {closed}")
                if record.get("pre_state") != current:
                    broken(where, f"pre_state is not the post_state of round {closed}"
                           if closed else "pre_state is not the episode's initial state")
                opened_round = record.get("round")
                head = fold(head, {"kind": "round_open", "round": record.get("round"),
                                   "state": record.get("pre_state")})
                links += 1
            elif record["event"] == "WORLD_INTENT_RECORDED":
                intent = record.get("transition_intent")
                intent = intent if isinstance(intent, dict) else {}
                payload = intent.get("payload") if isinstance(intent.get("payload"), dict) else {}
                if not in_round:
                    broken(where, "intends a transition outside its round")
                if payload.get("pre_state") != current:
                    broken(where, "pre-state is not the state its episode is in")
                intents[canonical(intent.get("identity"))] = record
            elif record["event"] == "WORLD_APPLIED":
                named = record.get("transition_intent")
                intent = intents.pop(canonical(named), None)
                refs = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
                path = (refs.get("transition") or {}).get("path")
                member = documents.get(path)
                if intent is None or intent.get("round") != record.get("round") \
                        or not isinstance(member, dict) or member.get("intent") != named:
                    broken(where, "is not the one committed transition of an intent recorded "
                                  "before it in its round")
                    current = record.get("post_state")
                    continue
                before = stated(member.get("transition"), "pre_state")
                after = stated(member.get("transition"), "post_state")
                if before != current:
                    broken(where, "the pre-state its evidence serializes is not the state its "
                                  "episode is in")
                if after is None or after != record.get("post_state"):
                    broken(where, "post_state is not the state its evidence serializes")
                current = record.get("post_state")
                applied += 1
                head = fold(head, {
                    "kind": "transition", "round": record.get("round"),
                    "intent": named.get("digest"), "transition": record.get("transition"),
                    "pre_state": before, "post_state": current})
                links += 1
            elif record["event"] == "ROUND_COMPLETED":
                if not in_round:
                    broken(where, f"does not close the open round after round {closed}")
                if record.get("post_state") != current:
                    broken(where, "post_state is not the state its last committed transition "
                                  "left")
                closed, opened_round = record.get("round"), None
                head = fold(head, {"kind": "round_close", "round": closed,
                                   "state": record.get("post_state")})
                links += 1
        episodes[str(opened.get("episode_key"))] = {
            "rounds": closed, "transitions": applied, "final_state": current,
            "head": f"sha256:{head}"}
        total += links
    return problems, {"rule": STATE_CHAIN_RULE, "origin": "plan_initial_state",
                      "reset": "episode_isolation", "initial_state": origin,
                      "episodes": dict(sorted(episodes.items())), "links": total}


def _world_state_evidence(state, state_schema: str | None) -> dict:
    document = {"schema": WORLD_STATE_EVIDENCE[state_schema is not None],
                "identity": world_state_identity(state, state_schema), "state": state}
    if state_schema is not None:
        document["state_schema"] = state_schema
    return document


def _world_state_problems(schema: dict, state) -> list[str]:
    """Why *state* is not an object of the plan's World state (or action) schema."""
    if not isinstance(state, dict):
        return ["it is not an object"]
    fields = schema["fields"]
    problems = [f"missing field {name!r}" for name in sorted(fields) if name not in state]
    if not schema["open"]:
        problems += [f"undeclared field {name!r}" for name in sorted(set(state) - set(fields))]
    for name in sorted(fields):
        if name not in state:
            continue
        value, kind = state[name], fields[name]
        fits = {"boolean": isinstance(value, bool),
                "integer": isinstance(value, int) and not isinstance(value, bool),
                "number": isinstance(value, (int, float)) and not isinstance(value, bool),
                "string": isinstance(value, str), "object": isinstance(value, dict),
                "array": isinstance(value, list)}[kind]
        if not fits:
            problems.append(f"field {name!r} is not {kind}")
    return problems


def _is_world_schema(schema, label: str) -> bool:
    """A closed typed-object schema document (a World's state or action schema)."""
    return isinstance(schema, dict) \
        and set(schema) == {"schema", "schema_id", "version", "fields", "open"} \
        and schema["schema"] == label \
        and isinstance(schema["schema_id"], str) and bool(schema["schema_id"]) \
        and ":" not in schema["schema_id"] \
        and isinstance(schema["version"], int) and not isinstance(schema["version"], bool) \
        and schema["version"] >= 1 and isinstance(schema["open"], bool) \
        and isinstance(schema["fields"], dict) \
        and bool(schema["fields"] or schema["open"]) \
        and all(isinstance(name, str) and name and kind in WORLD_STATE_FIELD_TYPES
                for name, kind in schema["fields"].items())


def _world_admissibility_problems(schema: dict, body: dict) -> list[str]:
    """Why a transition's three actions are not one stated bvl-world-admissibility-1.

    BVL T3-003.  Each action is read as the evidence states it; none is derived
    from another: ADMISSIBLE admits the requested action itself, CLIPPED another
    action of the schema, INADMISSIBLE none (and nothing is executed); the
    executed action is empty or any action of the schema.
    """
    actions = [body.get(role) for role in WORLD_ACTION_ROLES]
    for role, action in zip(WORLD_ACTION_ROLES, actions, strict=True):
        if not isinstance(action, dict):
            return [f"{role} is not an object"]
    requested, admissible, executed = actions
    ref = f"{schema['schema_id']}:{schema['version']}"
    problems = [f"requested action is not a {ref} action: {problem} (BVL-WORLD-004)"
                for problem in _world_state_problems(schema, requested)]
    verdict = body.get("admissibility_verdict")
    if verdict not in WORLD_ADMISSIBILITY_VERDICTS:
        return problems + [f"admissibility verdict {verdict!r} is not one of "
                           f"{list(WORLD_ADMISSIBILITY_VERDICTS)} (BVL-WORLD-006)"]
    unchanged = canonical(admissible) == canonical(requested)
    found = []
    if verdict == "ADMISSIBLE" and not unchanged:
        found.append("ADMISSIBLE, but the admissible action is not the requested action")
    if verdict == "CLIPPED":
        if unchanged:
            found.append("CLIPPED, but the admissible action is the requested action")
        found += [f"the admissible action is not a {ref} action: {problem}"
                  for problem in _world_state_problems(schema, admissible)]
    if verdict == "INADMISSIBLE" and (admissible or executed):
        found.append("INADMISSIBLE, but an action is stated admissible or executed")
    if executed:
        found += [f"the executed action is neither empty nor a {ref} action: {problem}"
                  for problem in _world_state_problems(schema, executed)]
    return problems + [f"{problem} (BVL-WORLD-006)" for problem in found]


def _is_world_progression(progression, action_schema: dict) -> bool:
    """A closed bvl-world-progression-1: the NO_ACTION meaning and the event kinds;
    a -2 (BVL T4-004) also declares the World's regime events and regime fields."""
    if not isinstance(progression, dict) \
            or set(progression) - {"null_action", "regime"} != {"schema", "no_action",
                                                                "exogenous_events"} \
            or progression["schema"] != (WORLD_PROGRESSION_2 if "regime" in progression
                                         else WORLD_PROGRESSION) \
            or progression["no_action"] not in WORLD_NO_ACTION_MEANINGS:
        return False
    events = progression["exogenous_events"]
    if not isinstance(events, list) \
            or any(not isinstance(kind, str) or not kind for kind in events) \
            or events != sorted(set(events)):
        return False
    if "regime" in progression:
        regime = progression["regime"]
        if not isinstance(regime, dict) or set(regime) != {"events", "fields"}:
            return False
        for names in regime.values():
            if not isinstance(names, list) or not names \
                    or any(not isinstance(name, str) or not name for name in names) \
                    or names != sorted(set(names)):
                return False
        if not set(regime["events"]) <= set(events):
            return False
    if progression["no_action"] != "NULL_ACTION":
        return "null_action" not in progression  # stated exactly by a NULL_ACTION World
    null = progression.get("null_action")
    return isinstance(null, dict) and not _world_state_problems(action_schema, null)


def _has_null(value) -> bool:
    """Whether a JSON value holds a null (canonical JSON omits one: BVL T3-005)."""
    if isinstance(value, dict):
        return any(item is None or _has_null(item) for item in value.values())
    if isinstance(value, list):
        return any(item is None or _has_null(item) for item in value)
    return value is None


def _world_progression_problems(world: dict, body: dict) -> list[str]:
    """Why a transition-2 is not one stated bvl-world-progression-1 (BVL T3-004).

    Read from the evidence alone: the input, whether an action was executed
    and the exogenous events are what the World stated.  A NO_ACTION input
    stays within the meaning the contract froze, every event is of a declared
    kind, and a post-state that is not the pre-state follows from an executed
    action or a stated event - anything else is a hidden mutation.
    """
    progression, schema = world["progression"], world["action_schema"]
    given, executed, events = (body.get(name) for name in
                               ("action_input", "executed", "exogenous_events"))
    if given not in WORLD_ACTION_INPUTS or not isinstance(executed, bool) \
            or not isinstance(events, list):
        return ["does not state its input, whether an action was executed and its "
                "exogenous events"]
    found = []
    for event in events:
        if not isinstance(event, dict) or set(event) != {"event", "detail"} \
                or not isinstance(event["detail"], dict):
            found.append("states an exogenous event that is not {event, detail}")
        elif event["event"] not in progression["exogenous_events"]:
            found.append(f"states exogenous event {event['event']!r}, a kind the World "
                         "contract does not declare")
    actions = [body.get(role) for role in WORLD_ACTION_ROLES]
    if any(not isinstance(action, dict) for action in actions):
        return found + ["states an action that is not an object"]
    requested, admissible, done = actions
    moved = canonical(body.get("post_state")) != canonical(body.get("pre_state"))
    if not executed and done:
        found.append("executed nothing, but states an executed action")
    if executed:
        found += [f"executed action is not an action of the schema: {problem}"
                  for problem in _world_state_problems(schema, done)]
    verdict = body.get("admissibility_verdict")
    if given == "ACTION":
        if verdict == "INADMISSIBLE" and executed:
            found.append("is INADMISSIBLE, but states an executed action")
    else:
        meaning = progression["no_action"]
        if meaning == "UNDECLARED":
            found.append("applies NO_ACTION, which the World contract does not declare "
                         "(BVL-WORLD-008)")
        if verdict != "NO_ACTION" or requested or admissible:
            found.append("is of a NO_ACTION input, but states an assessed action")
        if meaning in ("NO_TRANSITION", "EXOGENOUS_PROGRESSION") and executed:
            found.append(f"NO_ACTION means {meaning}, but an action is stated executed")
        if meaning == "NO_TRANSITION" and (events or moved):
            found.append("NO_ACTION means NO_TRANSITION, but an event or another "
                         "post-state is stated")
        if meaning == "NULL_ACTION" and not (
                executed and canonical(done) == canonical(progression.get("null_action"))):
            found.append("NO_ACTION means NULL_ACTION, but the executed action is not the "
                         "contract's null action")
    if moved and not executed and not events:
        found.append("is a hidden mutation: the post-state is not the pre-state, but "
                     "neither an executed action nor an exogenous event is stated")
    # BVL T4-004: a regime moves only in a transition that states a regime event
    regime = progression.get("regime") or {"events": [], "fields": []}
    pre, post = body.get("pre_state"), body.get("post_state")
    if isinstance(pre, dict) and isinstance(post, dict):
        shifted = sorted(name for name in regime["fields"]
                         if (name in pre) != (name in post)
                         or (name in pre
                             and canonical({"v": pre[name]}) != canonical({"v": post[name]})))
        if shifted and not regime_changes(progression, body):
            found.append(f"is a hidden regime change: regime fields {shifted} moved, but "
                         "no declared regime event is stated")
    return [f"{problem} (BVL-WORLD-006)" for problem in found]


def regime_changes(progression: dict, body) -> list:
    """BVL T4-004: the declared regime event kinds one transition body states."""
    declared = (progression.get("regime") or {}).get("events", [])
    events = body.get("exogenous_events") if isinstance(body, dict) else None
    return [event["event"] for event in (events if isinstance(events, list) else [])
            if isinstance(event, dict) and event.get("event") in declared]


def _is_world_rng(policy) -> bool:
    """A closed bvl-world-rng-1: DETERMINISTIC, or SEEDED naming the declared RNG."""
    if not isinstance(policy, dict) or policy.get("schema") != WORLD_RNG:
        return False
    if policy.get("policy") == "DETERMINISTIC":
        return set(policy) == {"schema", "policy"}
    return policy.get("policy") == "SEEDED" \
        and set(policy) == {"schema", "policy", "algorithm"} \
        and policy["algorithm"] == WORLD_RNG_ALGORITHM


def _world_rng_problems(policy: dict, evidence) -> list[str]:
    """Why a transition's ``rng`` is not what the contract's RNG policy evidences."""
    if not isinstance(evidence, dict) or evidence.get("schema") != WORLD_RNG_EVIDENCE \
            or evidence.get("policy") != policy["policy"]:
        return [f"does not evidence the World contract's {policy['policy']} RNG policy "
                "(BVL-WORLD-013)"]
    if policy["policy"] == "DETERMINISTIC":
        return [] if set(evidence) == {"schema", "policy"} else [
            "is DETERMINISTIC and states draws from an RNG (BVL-WORLD-013)"]
    counts = [evidence.get("draws"), evidence.get("bits")]
    if set(evidence) != {"schema", "policy", "algorithm", "draws", "bits"} \
            or evidence["algorithm"] != policy["algorithm"] \
            or any(not isinstance(c, int) or isinstance(c, bool) or c < 0 for c in counts) \
            or counts[1] < counts[0]:
        return ["does not state the declared RNG's algorithm and its draw counts "
                "(BVL-WORLD-013)"]
    return []


def _world_contract_problems(semantic: dict, nodes: dict) -> list[str]:
    """The plan-8 ``world``: one closed contract, the plan's only World, a valid start."""
    world = semantic["world"]
    if not isinstance(world, dict) \
            or set(world) != {"schema", "plugin", "state_schema", "state_serialization",
                              "action_schema", "admissibility", "progression", "rng"} \
            or world["schema"] != WORLD_CONTRACT_SCHEMA \
            or world["state_serialization"] != WORLD_STATE_SERIALIZATION \
            or world["admissibility"] != WORLD_ADMISSIBILITY \
            or not isinstance(world["plugin"], str) or not world["plugin"]:
        return ["plan world is not a closed bvl-world-contract-4"]
    schema = world["state_schema"]
    if not _is_world_schema(schema, WORLD_STATE_SCHEMA_SCHEMA):
        return ["plan world state_schema is not a closed bvl-world-state-schema-1"]
    if not _is_world_schema(world["action_schema"], WORLD_ACTION_SCHEMA_SCHEMA):
        return ["plan world action_schema is not a closed bvl-world-action-schema-1"]
    if not _is_world_progression(world["progression"], world["action_schema"]):
        return ["plan world progression is not a closed bvl-world-progression-1 / -2"]
    if not set((world["progression"].get("regime") or {}).get("fields", [])) \
            <= set(schema["fields"]):
        return ["plan world regime fields are not fields of its state schema"]
    if not _is_world_rng(world["rng"]):
        return ["plan world rng is not a closed bvl-world-rng-1"]
    problems = []
    transitions = [n for n in nodes.values() if n["kind"] == "world_transition"]
    if not transitions:
        problems.append("the plan declares a World contract no world_transition applies")
    problems += [f"world_transition {n['id']!r} names another World than the plan's contract"
                 for n in transitions if n["config"].get("world") != world["plugin"]]
    problems += [f"plan initial_world_state is not a state of its World schema: {problem}"
                 for problem in _world_state_problems(schema, semantic["initial_world_state"])]
    return problems


def key(document) -> str:
    """``{"kind", "digest"}`` -> the ``kind:digest`` string journal-2 uses."""
    if not isinstance(document, dict) or set(document) != {"kind", "digest"}:
        raise ValueError(f"not an identity document: {document!r}")
    return f"{document['kind']}:{document['digest']}"


def is_digest(value) -> bool:
    return (isinstance(value, str) and value.startswith("sha256:") and len(value) == 71
            and set(value[7:]) <= HEX)


def portable(path) -> bool:
    return isinstance(path, str) and all(
        seg and seg not in (".", "..") and set(seg) <= SEGMENT and seg[0].isalnum()
        for seg in path.split("/"))


def layout_role(path: str) -> str | None:
    """The one role a member's place in the K0 package layout gives it."""
    parts = path.split("/")
    if path == "journal-2.jsonl":
        return "episode_lineage"
    if path == "custody-v2/entries.jsonl":
        return "custody"
    if len(parts) == 2 and parts[0] == "requests-v2" and parts[1].startswith("request-") \
            and parts[1].endswith(".json"):
        return "request"
    if len(parts) == 2 and parts[0] == "artifacts" and parts[1].startswith("call-") \
            and parts[1].endswith(".bin"):
        return "response"
    if len(parts) == 3 and parts[0] == "evidence-v2" and parts[1] in ROLES - UNPLACED_ROLES \
            and parts[2].endswith(".json"):
        return parts[1]
    return None


def _actor_problems(actors, nodes: dict) -> list[str]:
    """plan-2 actors: a canonical binding set naming every actor_call's actor."""
    if not isinstance(actors, dict) or set(actors) != {"schema", "actors"} \
            or actors["schema"] != ACTOR_BINDING_SET_SCHEMA \
            or not isinstance(actors["actors"], list):
        return ["plan actors are not a bvl-actor-binding-set-1"]
    bound: list[str] = []
    for item in actors["actors"]:
        if not isinstance(item, dict) or set(item) != {"actor_id", "role", "profile"} \
                or not isinstance(item["profile"], dict) \
                or set(item["profile"]) != ACTOR_PROFILE_KEYS \
                or item["profile"]["schema"] != ACTOR_PROFILE_SCHEMA:
            return ["a plan actor binding has the wrong closed shape"]
        bound.append(item["actor_id"])
    if bound != sorted(set(bound)):
        return ["plan actor bindings are not unique and canonically ordered"]
    return [f"actor_call {node_id!r} names actor {node['config'].get('actor')!r} "
            "outside the plan" for node_id, node in sorted(nodes.items())
            if node["kind"] == "actor_call" and node["config"].get("actor") not in bound]


def _is_sha256_hex(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and not set(value) - set("0123456789abcdef"))


def _information_problems(information, actors, nodes=None) -> list[str]:
    """plan-3 information: canonical sources and one grant set per plan actor.

    access-2 additionally names, per granted source, the registered transform
    the actor observes it through.  access-3 (BVL T2-001) may also name
    ``actor_output`` sources: each producer is an actor_call / proposal_parse
    IR node that is a same-round ancestor of every call of a granted actor.
    """
    schema = information.get("schema") if isinstance(information, dict) else None
    v4 = schema == INFORMATION_ACCESS_SCHEMA_4
    v2 = schema in (INFORMATION_ACCESS_SCHEMA_2, INFORMATION_ACCESS_SCHEMA_3) or v4
    v3 = schema == INFORMATION_ACCESS_SCHEMA_3 or v4
    keys = {"schema", "sources", "grants"} | ({"transforms"} if v2 else set())
    if (not isinstance(information, dict)
            or set(information) != keys
            or information["schema"] not in (INFORMATION_ACCESS_SCHEMA,
                                             INFORMATION_ACCESS_SCHEMA_2,
                                             INFORMATION_ACCESS_SCHEMA_3,
                                             INFORMATION_ACCESS_SCHEMA_4)
            or not isinstance(information["sources"], list)
            or not isinstance(information["grants"], list)):
        return ["plan information is not a bvl-information-access-1/-2/-3"]
    sources: list[str] = []
    producers: dict[str, str] = {}
    remembered: list[str] = []
    for item in information["sources"]:
        if v4 and isinstance(item, dict) and item.get("source_kind") == "memory_artifact":
            # BVL T4-003: the producer is a memory_update node (its lifecycle
            # is judged by _memory_plan_problems)
            node = (nodes or {}).get(item.get("producer"))
            if set(item) != INFORMATION_ACTOR_OUTPUT_KEYS or node is None \
                    or node["kind"] != "memory_update":
                return ["a plan memory_artifact source does not name a memory_update "
                        "node of the IR"]
            remembered.append(item["source_id"])
            sources.append(item["source_id"])
            continue
        if v3 and isinstance(item, dict) and item.get("source_kind") == "actor_output":
            node = (nodes or {}).get(item.get("producer"))
            if set(item) != INFORMATION_ACTOR_OUTPUT_KEYS or node is None \
                    or node["kind"] not in ACTOR_OUTPUT_PRODUCERS:
                return ["a plan actor_output source does not name an actor_call / "
                        "proposal_parse producer of the IR"]
            producers[item["source_id"]] = item["producer"]
            sources.append(item["source_id"])
            continue
        if (not isinstance(item, dict) or set(item) != INFORMATION_SOURCE_KEYS
                or item["source_kind"] != "frozen_resource"
                or not _is_sha256_hex(item["content_sha256"])
                or not isinstance(item["size"], int) or isinstance(item["size"], bool)):
            return ["a plan information source has the wrong closed shape"]
        sources.append(item["source_id"])
    if sources != sorted(set(sources)):
        return ["plan information sources are not unique and canonically ordered"]
    granted: list[str] = []
    for item in information["grants"]:
        if (not isinstance(item, dict) or set(item) != {"actor_id", "sources"}
                or not isinstance(item["sources"], list)
                or item["sources"] != sorted(set(item["sources"]))
                or not set(item["sources"]) <= set(sources)):
            return ["a plan information grant is not a canonical subset of its sources"]
        granted.append(item["actor_id"])
    bound = sorted(item["actor_id"] for item in actors["actors"])
    if granted != bound:
        return ["plan information grants do not name exactly the plan actors"]
    if v4 and not remembered:
        return ["plan information access-4 carries no memory_artifact source"]
    if v3 and not v4 and not producers:
        return ["plan information access-3 carries no actor_output source"]
    for item in information["grants"]:
        for node in (nodes or {}).values():
            if node["kind"] != "actor_call" or node["config"].get("actor") != item["actor_id"]:
                continue
            ancestors = _ancestors(nodes, node["id"])
            if any(producers[source] not in ancestors
                   for source in item["sources"] if source in producers):
                return [f"actor {item['actor_id']!r} is granted an actor_output its call "
                        f"{node['id']!r} does not depend on in the round"]
    if v2:
        grants = {item["actor_id"]: set(item["sources"]) for item in information["grants"]}
        transforms = information["transforms"]
        if not isinstance(transforms, list) or (not transforms and not v3):
            return ["plan information access-2 carries no transforms"]
        cells = []
        for item in transforms:
            if (not isinstance(item, dict) or set(item) != INFORMATION_TRANSFORM_KEYS
                    or not isinstance(item["transform"], str) or not item["transform"]
                    or not isinstance(item["config"], dict)
                    or item["source_id"] not in grants.get(item["actor_id"], set())):
                return ["a plan information transform is not over one granted source"]
            cells.append((item["actor_id"], item["source_id"]))
        if cells != sorted(set(cells)):
            return ["plan information transforms are not unique and canonically ordered"]
    return []


def memory_policies(nodes: dict) -> dict:
    """BVL T4-003: memory_update node id -> its declared lifecycle; {} for a plan
    whose memory nodes declare none (the K0 spike semantics)."""
    memory = {node_id: node for node_id, node in nodes.items()
              if node["kind"] == "memory_update"}
    if not any(set(node["config"]) - {"owner", "key"} for node in memory.values()):
        return {}
    policies = {}
    for node_id, node in sorted(memory.items()):
        config = node["config"]
        policy = {**{name: config.get(name) for name in MEMORY_LIFECYCLE_KEYS},
                  "source": (node["depends_on"] or [None])[0]}
        if "regime_change" in config:  # BVL T4-004
            policy["regime_change"] = config["regime_change"]
        if config.get("scope") == "cross_episode":
            carry = config.get("carry")
            policy["carry"] = carry if not _is_carry(carry) else {
                "episodes": list(carry["episodes"]),
                "reset_before": [name for name in carry["episodes"]
                                 if name in carry["reset_before"]]}
        policies[node_id] = policy
    return policies


def _is_carry(carry) -> bool:
    """BVL T4-004: a closed carry - at least two ordered episodes and the reset
    boundaries, each before a consuming episode."""
    if not isinstance(carry, dict) or set(carry) != {"episodes", "reset_before"}:
        return False
    episodes, resets = carry["episodes"], carry["reset_before"]
    for names in (episodes, resets):
        if not isinstance(names, list) \
                or any(not isinstance(name, str) or not name for name in names) \
                or len(set(names)) != len(names):
            return False
    return len(episodes) >= 2 and all(name in episodes[1:] for name in resets)


def memory_consumers(policy: dict, episode_key) -> list:
    """BVL T4-004: the later episodes observing what *episode_key* recorded."""
    carry = policy.get("carry") or {"episodes": [], "reset_before": []}
    if episode_key not in carry["episodes"]:
        return []
    consumers = []
    for name in carry["episodes"][carry["episodes"].index(episode_key) + 1:]:
        if name in carry["reset_before"]:
            break
        consumers.append(name)
    return consumers


def memory_valid(policy: dict, round_index: int, episode_key) -> dict:
    valid = {"from_round": round_index + 1,
             "through_round": round_index + policy["retention"]}
    if "regime_change" in policy:
        valid["episodes"] = memory_consumers(policy, episode_key)
    return valid


def memory_held(policy: dict, timeline: list, round_index: int) -> list:
    """BVL T4-004: the artifacts of one node held when *round_index* of the last
    episode of *timeline* opens.  *timeline* is the run's episodes so far in
    opened order: ``{"key", "episode", "artifacts", "regime_rounds"}``."""
    current = timeline[-1]
    reset = policy.get("regime_change") == "reset"
    carry = (policy.get("carry") or {}).get("episodes", [])
    turned = [g for g in current["regime_rounds"] if g < round_index]
    kept, blocked = [], False
    for entry in reversed(timeline[:-1]):
        if entry["key"] not in carry:
            continue
        if current["key"] in memory_consumers(policy, entry["key"]) \
                and not (reset and (blocked or turned)):
            kept[:0] = [a for a in sorted(entry["artifacts"], key=lambda a: a["round"])
                        if not (reset and any(g > a["round"] for g in entry["regime_rounds"]))]
        blocked = blocked or bool(entry["regime_rounds"])
    kept += [a for a in sorted(current["artifacts"], key=lambda a: a["round"])
             if not (reset and any(a["round"] < g for g in turned))]
    return kept


def _memory_plan_problems(semantic: dict, nodes: dict) -> list[str]:
    """BVL T4-003: the plan's memory is declared end to end."""
    policies = memory_policies(nodes)
    information = semantic.get("information") or {}
    for source in information.get("sources", []):
        if source.get("source_kind") == "memory_artifact" \
                and source.get("producer") not in policies:
            return [f"memory_artifact source {source.get('source_id')!r} names no "
                    "memory_update node declaring a memory lifecycle"]
    if not policies:
        return []
    actors = {item["actor_id"] for item in (semantic.get("actors") or {}).get("actors", [])}
    slots = []
    for node_id, policy in policies.items():
        node = nodes[node_id]
        retention = policy["retention"]
        extra = set(node["config"]) - MEMORY_LIFECYCLE_KEYS
        crossing = policy["scope"] == "cross_episode"
        regime = (semantic.get("world") or {}).get("progression", {}).get("regime")
        if extra != ({"regime_change", "carry"} if crossing else extra & {"regime_change"}) \
                or policy.get("regime_change", "retain") not in MEMORY_REGIME_INTERACTIONS \
                or (crossing and not _is_carry(node["config"]["carry"])) \
                or (policy.get("regime_change") == "reset" and not regime):
            return [f"memory_update {node_id!r} does not declare a closed cross-episode / "
                    "regime-change memory semantics"]
        if not MEMORY_LIFECYCLE_KEYS <= set(node["config"]) \
                or not isinstance(policy["owner"], str) or not policy["owner"] \
                or not isinstance(policy["key"], str) or not policy["key"] \
                or policy["scope"] not in MEMORY_SCOPES \
                or isinstance(retention, bool) or not isinstance(retention, int) \
                or retention < 1 or policy["transform"] not in MEMORY_TRANSFORMS:
            return [f"memory_update {node_id!r} does not declare a closed memory lifecycle"]
        if [nodes[d]["kind"] for d in node["depends_on"]] != ["world_transition"]:
            return [f"memory_update {node_id!r} does not derive from exactly one "
                    "world_transition node"]
        if policy["owner"] not in actors:
            return [f"memory_update {node_id!r} owner is not a plan actor"]
        slots.append((policy["owner"], policy["key"]))
    if len(set(slots)) != len(slots):
        return ["two memory_update nodes declare the same owner and key"]
    if semantic.get("initial_memory"):
        return ["a plan declaring a memory lifecycle carries undeclared initial memory"]
    return []


def memory_view(source_id: str, producer: str, artifacts: list, round_index: int,
                episode=None):
    """BVL T4-003: (content digest, request-2 lineage) of one memory source observed
    in *round_index*: the node's artifacts valid in that round, oldest first.
    With *episode* (BVL T4-004) *artifacts* are the held ones in order: those of
    an earlier episode come first and are valid in every round."""
    def valid_in(artifact: dict) -> bool:
        if episode is not None and artifact.get("episode") != episode:
            return True
        valid = artifact.get("valid")
        if not isinstance(valid, dict) or not isinstance(artifact.get("round"), int):
            return False  # a malformed interval is valid nowhere (M4-LIN names it)
        bounds = (valid.get("from_round"), valid.get("through_round"))
        if any(isinstance(b, bool) or not isinstance(b, int) for b in bounds):
            return False
        return bounds[0] <= round_index <= bounds[1]

    valid = [a for a in artifacts if valid_in(a)]
    if episode is None:
        valid = sorted(valid, key=lambda a: a["round"])
    content = canonical({"schema": MEMORY_OBSERVATION_SCHEMA, "artifacts": [
        {"identity": a["identity"], "owner": a["owner"], "key": a["key"],
         "round": a["round"], "value": a["value"],
         **({"episode_key": a["episode_key"]} if "episode_key" in a else {})}
        for a in valid]})
    digest = hashlib.sha256(content).hexdigest()
    return digest, {"source_id": source_id, "producer": producer,
                    "artifacts": [a["identity"] for a in valid], "content_sha256": digest}


def _memory_artifact_problems(document: dict, policy: dict, episode: dict, step: dict,
                              round_index: int, record, transition,
                              episode_key=None) -> list[str]:
    """BVL T4-003: why one committed artifact is not its node's declared lifecycle."""
    problems = []
    extended = "regime_change" in policy
    schema, fields = ((MEMORY_ARTIFACT_3, MEMORY_FIELDS_3) if extended
                      else (MEMORY_ARTIFACT_2, MEMORY_FIELDS_2))
    if document.get("schema") != schema \
            or set(document) != {"schema", "identity", *fields}:
        problems.append(f"is not a closed {schema}")
    if document.get("episode") != episode or document.get("step") != step:
        problems.append("belongs to another episode / step")
    if extended and (document.get("episode_key") != episode_key
                     or document.get("regime_change") != policy["regime_change"]):
        problems.append("is not its episode's key and the declared regime-change "
                        "interaction")
    if any(document.get(name) != policy[name] for name in MEMORY_LIFECYCLE_KEYS):
        problems.append("is not the plan's declared owner / key / scope / retention / "
                        "transform")
    if document.get("valid") != memory_valid(policy, round_index, episode_key):
        problems.append("validity interval is not its round, declared retention and "
                        "declared carry")
    if record != {"identity": document.get("identity"), "owner": policy["owner"],
                  "key": policy["key"], "value": document.get("value")}:
        problems.append("is not what MEMORY_RECORDED committed")
    if not isinstance(transition, dict) or "outcome" not in transition:
        problems.append("has no committed World transition as source evidence")
    elif document.get("value") != transition["outcome"]:
        problems.append("value is not its transform of the source World transition")
    return problems


def _ancestors(nodes: dict, node_id: str) -> set:
    found, pending = set(), list(nodes[node_id]["depends_on"])
    while pending:
        current = pending.pop()
        if current not in found:
            found.add(current)
            pending.extend(nodes[current]["depends_on"])
    return found


def topological_order(nodes: dict) -> list[str]:
    """Kahn's order, ready nodes by code point (the IR's documented order)."""
    remaining = {node_id: set(node["depends_on"]) for node_id, node in nodes.items()}
    order: list[str] = []
    while remaining:
        ready = sorted(node_id for node_id, deps in remaining.items() if not deps)
        if not ready:
            raise ValueError(f"protocol dependency cycle among {sorted(remaining)}")
        order.extend(ready)
        for node_id in ready:
            remaining.pop(node_id)
        for deps in remaining.values():
            deps.difference_update(ready)
    return order


def protocol_dag(protocol: dict) -> dict:
    """The intra-episode causal order: typed nodes, dependency edges, rounds."""
    return {"schema": "bvl-protocol-dag-1", "rounds": protocol_rounds(protocol),
            "nodes": sorted(({"id": n["id"], "kind": n["kind"]} for n in protocol["nodes"]),
                            key=lambda item: item["id"]),
            "edges": sorted([dep, n["id"]] for n in protocol["nodes"] for dep in n["depends_on"])}


def experiment_schedule(opened: list, dag: dict) -> tuple:
    """The run's one experiment schedule, re-derived from its EPISODE_OPENED records."""
    problems, schedules = [], []
    for index, record in enumerate(opened):
        name = record.get("episode_key")
        if record.get("protocol_dag") != dag:
            problems.append(f"episode {name!r} protocol_dag is not the IR's causal order")
        found = record.get("schedule")
        if not isinstance(found, dict) or set(found) != {"identity", "episodes", "position"}:
            problems.append(f"episode {name!r} carries no closed experiment schedule")
            continue
        keys = found["episodes"]
        if (not isinstance(keys, list) or not keys or len(set(map(str, keys))) != len(keys)
                or any(not isinstance(k, str) or not k for k in keys)):
            problems.append(f"episode {name!r} schedule is malformed")
            continue
        document = {"schema": "bvl-experiment-schedule-1", "episodes": keys}
        if found["identity"] != identity("experiment_schedule", document):
            problems.append(f"episode {name!r} schedule identity does not recompute")
        if found["position"] != index or keys[index:index + 1] != [name]:
            problems.append(f"episode {name!r} is opened {index}th, at schedule position "
                            f"{found['position']} of {keys}")
        schedules.append(found["identity"])
        last = {"identity": found["identity"], "episodes": keys}
    if len({key(item) for item in schedules if isinstance(item, dict)
            and set(item) == {"kind", "digest"}}) > 1:
        problems.append("the run's episodes are opened under different experiment schedules")
    if problems or not schedules:
        return None, problems
    return last, problems


def _proposal_type_ok(kind: str, value) -> bool:
    if kind == "boolean":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    return isinstance(value, {"integer": int, "number": (int, float), "string": str}[kind])


def _proposal_contracts(proposals, nodes: dict) -> tuple[dict, list[str]]:
    """plan-4 proposals: one closed P06 contract per proposal_parse node."""
    if not isinstance(proposals, dict) or set(proposals) != {"schema", "contracts"} \
            or proposals["schema"] != PROPOSAL_CONTRACT_SET_SCHEMA \
            or not isinstance(proposals["contracts"], list):
        return {}, ["plan proposals are not a bvl-proposal-contract-set-1"]
    contracts: dict[str, dict] = {}
    for item in proposals["contracts"]:
        schema = item.get("proposal_schema") if isinstance(item, dict) else None
        if not isinstance(item, dict) or set(item) != PROPOSAL_CONTRACT_KEYS \
                or item["schema"] != PROPOSAL_CONTRACT_SCHEMA \
                or not isinstance(item["config"], dict) or not isinstance(item["parser"], str) \
                or not isinstance(schema, dict) or set(schema) != PROPOSAL_SCHEMA_KEYS \
                or schema["schema"] != PROPOSAL_SCHEMA_SCHEMA \
                or not isinstance(schema["fields"], dict) or not schema["fields"] \
                or set(schema["fields"].values()) - PROPOSAL_FIELD_TYPES \
                or not isinstance(schema["allow_no_action"], bool):
            return {}, ["a plan proposal contract has the wrong closed shape"]
        if item["on_invalid"] not in ("PARSE_FAILURE", "NO_ACTION") or (
                item["on_invalid"] == "NO_ACTION" and not schema["allow_no_action"]):
            return {}, [f"proposal contract {item['node_id']!r} has an inadmissible policy"]
        contracts[item["node_id"]] = item
    if list(contracts) != sorted(contracts) or len(contracts) != len(proposals["contracts"]):
        return {}, ["plan proposal contracts are not unique and canonically ordered"]
    parse_nodes = {node_id for node_id, node in nodes.items()
                   if node["kind"] == "proposal_parse"}
    if set(contracts) != parse_nodes:
        return {}, ["plan proposal contracts do not bind exactly the proposal_parse nodes"]
    return contracts, []


def _committed_proposal_problems(document: dict, contract: dict) -> list[str]:
    """A committed proposal-2 is its plan contract's VALID or allowed NO_ACTION."""
    if document.get("contract") != contract or document.get("parser") != contract["parser"]:
        return ["proposal contract/parser is not the plan's"]
    fields = contract["proposal_schema"]["fields"]
    value, verdict, reason = document.get("value"), document.get("verdict"), document.get("reason")
    if verdict == "VALID":
        if reason is not None or not isinstance(value, dict) or set(value) != set(fields) \
                or not all(_proposal_type_ok(kind, value[name]) for name, kind in fields.items()):
            return ["VALID proposal is not its schema's closed typed shape"]
        return []
    if verdict == "NO_ACTION":
        if contract["on_invalid"] != "NO_ACTION" or value != {} or not reason:
            return ["NO_ACTION proposal outside its policy"]
        return []
    return [f"a {verdict!r} proposal was committed"]


def _decision_contracts(decisions, nodes: dict, proposals: dict) -> tuple[dict, list[str]]:
    """plan-5 decisions: one closed P07 contract per decision node whose authority
    re-derives from the IR (decision -> parse -> actor_call -> actor)."""
    if not isinstance(decisions, dict) or set(decisions) != {"schema", "contracts"} \
            or decisions["schema"] != DECISION_CONTRACT_SET_SCHEMA \
            or not isinstance(decisions["contracts"], list):
        return {}, ["plan decisions are not a bvl-decision-contract-set-1"]
    contracts: dict[str, dict] = {}
    for item in decisions["contracts"]:
        if not isinstance(item, dict) or set(item) != DECISION_CONTRACT_KEYS \
                or item["schema"] != DECISION_CONTRACT_SCHEMA \
                or not isinstance(item["rule"], str) or not isinstance(item["config"], dict) \
                or not isinstance(item["authority"], list) or not item["authority"] \
                or not isinstance(item["candidates"], dict) \
                or item["on_unresolved"] not in ("FAIL_EPISODE", "NO_ACTION"):
            return {}, ["a plan decision contract has the wrong closed shape"]
        node = nodes.get(item["node_id"])
        if node is None or node["kind"] != "decision" or node["config"] != {}:
            return {}, [f"decision contract {item['node_id']!r} binds no config-free "
                        "decision node"]
        if item["authority"] != sorted(set(item["authority"])) \
                or sorted(item["candidates"]) != item["authority"]:
            return {}, [f"decision contract {item['node_id']!r} authority is not canonical"]
        inputs: dict[str, list[str]] = {}
        for dependency in node["depends_on"]:
            parse = nodes[dependency]
            if parse["kind"] != "proposal_parse" or len(parse["depends_on"]) != 1:
                continue
            call = nodes[parse["depends_on"][0]]
            if call["kind"] == "actor_call":
                inputs.setdefault(call["config"].get("actor"), []).append(dependency)
        if any(inputs.get(actor) != [parse] for actor, parse in item["candidates"].items()):
            return {}, [f"decision contract {item['node_id']!r} authority is not the IR's "
                        "proposal inputs"]
        if len({canonical(proposals[parse]["proposal_schema"])
                for parse in item["candidates"].values()}) != 1:
            return {}, [f"decision contract {item['node_id']!r} mixes proposal schemas"]
        if item["rule"] in BUILTIN_RULES and (
                item["config"] != {}
                or (item["rule"] == SINGLE_AUTHORITY) != (len(item["authority"]) == 1)):
            return {}, [f"decision contract {item['node_id']!r} is not admissible for "
                        f"{item['rule']}"]
        contracts[item["node_id"]] = item
    if list(contracts) != sorted(contracts) or len(contracts) != len(decisions["contracts"]):
        return {}, ["plan decision contracts are not unique and canonically ordered"]
    if set(contracts) != {n for n, node in nodes.items() if node["kind"] == "decision"}:
        return {}, ["plan decision contracts do not bind exactly the decision nodes"]
    return contracts, []


def _builtin_decision(rule: str, candidates: list[dict]):
    """(kind, supporting actors, action, tally, unresolved code) of a builtin rule."""
    if rule == SINGLE_AUTHORITY:
        (only,) = candidates
        if only["verdict"] != "VALID":
            return "UNRESOLVED", [], {}, {}, "BVL-DEC-003"
        return "SELECTED", [only["actor"]], only["value"], {}, None
    groups: dict[bytes, list[str]] = {}
    for candidate in candidates:
        if candidate["verdict"] == "VALID":
            groups.setdefault(canonical(candidate["value"]), []).append(candidate["actor"])
    tally = {"eligible": len(candidates),
             "abstained": sorted(c["actor"] for c in candidates if c["verdict"] != "VALID"),
             "votes": [{"action": json.loads(action), "actors": sorted(actors)}
                       for action, actors in sorted(groups.items())]}
    if rule == VETO:
        winners = [a for a, actors in groups.items() if len(actors) == len(candidates)]
        if not winners:
            return "UNRESOLVED", [], {}, tally, "BVL-DEC-007"
    elif rule == MAJORITY:
        winners = [a for a, actors in groups.items() if 2 * len(actors) > len(candidates)]
    else:
        top = max((len(actors) for actors in groups.values()), default=0)
        winners = [a for a, actors in groups.items() if len(actors) == top and top > 0]
    if len(winners) != 1:
        return "UNRESOLVED", [], {}, tally, "BVL-DEC-006"
    return "AGGREGATE", sorted(groups[winners[0]]), json.loads(winners[0]), tally, None


def _committed_decision_problems(document: dict, contract: dict, upstream: dict,
                                 fields: dict) -> list[str]:
    """A committed decision-2 is its plan contract's rule applied to the IR's proposals.

    *upstream* maps each candidate parse node to its committed proposal evidence;
    *fields* is the candidates' proposal schema (the decision action contract).
    """
    if document.get("contract") != contract or document.get("rule") != contract["rule"]:
        return ["decision contract/rule is not the plan's"]
    candidates = []
    for actor, parse in sorted(contract["candidates"].items()):
        proposal = upstream.get(parse)
        if not isinstance(proposal, dict) or proposal.get("verdict") not in ("VALID",
                                                                             "NO_ACTION"):
            return [f"candidate {actor!r} has no committed proposal of {parse!r}"]
        candidates.append({"actor": actor, "node": parse, "proposal": proposal["identity"],
                           "verdict": proposal["verdict"], "value": proposal["value"]})
    if document.get("candidates") != candidates:
        return ["decision candidates are not the IR's committed proposals"]
    by_actor = {c["actor"]: c for c in candidates}
    action = document.get("requested_action")
    outcome = document.get("outcome")
    reason = document.get("reason")
    supporting = document.get("supporting_proposals")
    if not isinstance(supporting, list) or any(not isinstance(p, dict) for p in supporting):
        return ["decision supporting proposals are malformed"]
    if contract["rule"] in BUILTIN_RULES:
        kind, actors, decided, tally, code = _builtin_decision(contract["rule"], candidates)
        if kind == "UNRESOLVED":
            want = {"outcome": "NO_ACTION" if contract["on_unresolved"] == "NO_ACTION"
                    else "FAILED", "selected_proposal": None, "supporting_proposals": [],
                    "requested_action": {}, "tally": tally, "reason_code": code}
        else:
            want = {"outcome": kind,
                    "selected_proposal": by_actor[actors[0]]["proposal"]
                    if kind == "SELECTED" else None,
                    "supporting_proposals": sorted((by_actor[a]["proposal"] for a in actors),
                                                   key=key),
                    "requested_action": decided, "tally": tally, "reason_code": None}
        found = {"outcome": outcome, "selected_proposal": document.get("selected_proposal"),
                 "supporting_proposals": supporting, "requested_action": action,
                 "tally": document.get("tally"),
                 "reason_code": reason.get("code") if isinstance(reason, dict) else None}
        if found != want:
            return [f"builtin rule {contract['rule']} recomputes another decision"]
        if want["outcome"] == "FAILED":
            return ["a FAILED decision was committed"]
        return []
    # a registered third-party rule: kernel settlement consistency only
    keys = [key(p) for p in supporting]
    valid = {key(c["proposal"]): c for c in candidates if c["verdict"] == "VALID"}
    if outcome in ("SELECTED", "AGGREGATE"):
        if not keys or keys != sorted(set(keys)) or any(k not in valid for k in keys) \
                or not isinstance(action, dict) or set(action) != set(fields) \
                or not all(_proposal_type_ok(kind, action[name])
                           for name, kind in fields.items()):
            return ["decided action/supporting proposals are not settled candidates"]
        selected = document.get("selected_proposal")
        if outcome == "SELECTED" and (selected is None or [key(selected)] != keys
                                      or valid[keys[0]]["value"] != action):
            return ["SELECTED decision is not its selected candidate's proposal"]
        if outcome == "AGGREGATE" and selected is not None:
            return ["AGGREGATE decision names a selected proposal"]
        return []
    if outcome == "NO_ACTION":
        if contract["on_unresolved"] != "NO_ACTION" or action != {} \
                or not isinstance(reason, dict) or reason.get("code") not in UNRESOLVED_CODES:
            return ["NO_ACTION decision outside its declared policy"]
        return []
    return [f"a {outcome!r} decision was committed"]


def _positive(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _scalar(value) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _same(left, right) -> bool:
    """JSON scalar equality: a boolean is never a number."""
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if _number(left) and _number(right):
        return left == right
    return type(left) is type(right) and left == right


def _state_rule_config(rule: str, config) -> None:
    keys = {"path", "op", "value"} if rule == STATE_PREDICATE_RULE \
        else {"path", "success", "failure"}
    if not isinstance(config, dict) or set(config) != keys:
        raise ValueError(f"{rule} config has the wrong closed shape")
    path = config["path"]
    if not isinstance(path, list) or not path \
            or any(not isinstance(name, str) or not name for name in path):
        raise ValueError(f"{rule} path is a non-empty list of state member names")
    if rule == STATE_PREDICATE_RULE:
        if config["op"] not in ("eq", "ne", "lt", "le", "gt", "ge") \
                or not _scalar(config["value"]) \
                or (config["op"] not in ("eq", "ne") and not _number(config["value"])):
            raise ValueError(f"{rule} compares a state member with one JSON scalar")
        return
    values = []
    for name in ("success", "failure"):
        if not isinstance(config[name], list) or any(not _scalar(v) for v in config[name]):
            raise ValueError(f"{rule} {name} is a list of JSON scalars")
        values += config[name]
    if not values or any(_same(a, b) for i, a in enumerate(values) for b in values[i + 1:]):
        raise ValueError(f"{rule} declares each terminal value once, and at least one")


def timed_round_contract(document: dict) -> dict:
    """The closed `bvl-round-contract-2` reader (BVL T4-002): bound x rule x timing."""
    termination = document["termination"]
    if not isinstance(termination, dict) or set(termination) != {"rule", "timing", "config"}:
        raise ValueError("timed round termination has the wrong closed shape")
    if termination["timing"] not in TIMINGS:
        raise ValueError(f"termination timing {termination['timing']!r} is not a timing point")
    if not _positive(document["max_rounds"]):
        raise ValueError("round contract max_rounds is a positive integer")
    rule, config = termination["rule"], termination["config"]
    if rule == FIXED_COUNT_RULE:
        if not isinstance(config, dict) or set(config) != {"count"} \
                or not _positive(config["count"]) or config["count"] > document["max_rounds"]:
            raise ValueError("fixed-count termination config is a positive count within "
                             "max_rounds")
        if termination["timing"] != "after_round_close":
            raise ValueError("fixed-count termination counts closed rounds")
    elif rule in (STATE_PREDICATE_RULE, TERMINAL_STATE_RULE):
        _state_rule_config(rule, config)
    else:
        raise ValueError(f"termination rule {rule!r} is not registered")
    return document


def termination_anchor(contract, order: list):
    """The node whose commit is a timed contract's mid-round point (BVL T4-002)."""
    kind = TIMING_ANCHOR_KIND.get((contract or {}).get("termination", {}).get("timing"))
    if kind is None:
        return None
    positions = [index for index, node in enumerate(order) if node["kind"] == kind]
    if not positions:
        raise ValueError(f"termination timing needs a {kind} node in the round body")
    if kind == "decision" and any(node["kind"] == "world_transition"
                                  for node in order[:positions[-1]]):
        raise ValueError("termination timing after_decision is before the World: a World "
                         "transition precedes the round's last decision")
    return order[positions[-1]]["id"]


def state_rule_reason(termination: dict, state) -> str:
    """The reason a state rule derives on one evidenced state; ValueError if it cannot."""
    config, held = termination["config"], state
    for name in config["path"]:
        if not isinstance(held, dict) or name not in held:
            raise ValueError("the observed state has no such member")
        held = held[name]
    if not _scalar(held):
        raise ValueError("the observed state member is not a JSON scalar")
    if termination["rule"] == TERMINAL_STATE_RULE:
        if any(_same(held, value) for value in config["success"]):
            return "TERMINAL_STATE_SUCCESS"
        if any(_same(held, value) for value in config["failure"]):
            return "TERMINAL_STATE_FAILURE"
        return "STATE_NOT_TERMINAL"
    op, value = config["op"], config["value"]
    if op in ("eq", "ne"):
        holds = _same(held, value) is (op == "eq")
    elif not _number(held):
        raise ValueError("the observed state member is not a number")
    else:
        holds = {"lt": held < value, "le": held <= value, "gt": held > value,
                 "ge": held >= value}[op]
    return "STATE_PREDICATE_HOLDS" if holds else "STATE_PREDICATE_NOT_HELD"


def timed_verdict(contract: dict, point: str, round_index: int, observed, state) -> dict:
    """The `bvl-termination-verdict-2` a timed contract derives at one point of a round."""
    termination = contract["termination"]
    closed = round_index if point in ("after_round_close", "safety_bound") else round_index - 1
    if point == "safety_bound":
        reason, observed = "SAFETY_BOUND_REACHED", None
    elif termination["rule"] == FIXED_COUNT_RULE:
        reason = "FIXED_COUNT_REACHED" if closed >= termination["config"]["count"] \
            else "FIXED_COUNT_NOT_REACHED"
        observed = None
    else:
        reason = state_rule_reason(termination, state)
    verdict = {"schema": TERMINATION_VERDICT_SCHEMA_2,
               "rule": identity("termination_rule", termination),
               "timing": termination["timing"], "point": point, "round": round_index,
               "rounds_closed": closed, "max_rounds": contract["max_rounds"],
               "verdict": "TERMINATE" if reason in TERMINATING_REASONS else "CONTINUE",
               "reason": reason}
    if observed is not None:
        verdict["observed_state"] = observed  # only a state rule reads a state
    return verdict


def timed_round_problems(contract: dict, episode: dict, mine: list, initial: dict, name: str,
                         order: list, states: dict) -> list:
    """Why one completed episode is not its timed round contract's lifecycle (BVL T4-002).

    The walk is the engine's: the rule is evaluated at its declared point of
    every round, on the state the episode is then in (the initial state, then
    each WORLD_APPLIED post-state); a TERMINATE ends the episode there (the
    round is not opened, or is cut and closed); when round max_rounds closes
    without one, the core's safety-bound verdict follows.
    """
    timing = contract["termination"]["timing"]
    wrong = [f"episode {name!r} round lifecycle is not its round contract's: every round "
             f"opens, runs its steps and closes, and the termination rule is evaluated {timing}"]
    anchor = termination_anchor(contract, order)
    reads_state = contract["termination"]["rule"] != FIXED_COUNT_RULE
    pending = [r for r in mine if r["event"] in _ROUND_LIFECYCLE or r["event"] == "WORLD_APPLIED"]
    walk = {"cursor": 0, "current": initial}
    problems = []

    def take(event, round_index):
        while walk["cursor"] < len(pending) \
                and pending[walk["cursor"]]["event"] == "WORLD_APPLIED":
            walk["current"] = pending[walk["cursor"]].get("post_state")
            walk["cursor"] += 1
        if walk["cursor"] == len(pending):
            return None
        record = pending[walk["cursor"]]
        if record["event"] != event \
                or (round_index is not None and record.get("round") != round_index):
            return None
        walk["cursor"] += 1
        return record

    def verdict(point, round_index):
        record = take("TERMINATION_EVALUATED", round_index)
        if record is None:
            return None
        where = f"episode {name!r} journal #{record['sequence']} TERMINATION_EVALUATED"
        current = walk["current"]
        try:
            if reads_state and point != "safety_bound" and canonical(current) not in states:
                raise ValueError("the state it read is not evidenced")
            expected = timed_verdict(contract, point, round_index, current,
                                     states.get(canonical(current)))
        except (ValueError, TypeError) as error:
            problems.append(f"{where} cannot be re-derived: {error}")
            return True
        if record.get("termination") != expected or record.get("point") != point \
                or record.get("terminate") is not (expected["verdict"] == "TERMINATE"):
            problems.append(f"{where} is not the verdict the plan's round contract derives "
                            f"{point} of round {round_index}")
        return expected["verdict"] == "TERMINATE"

    round_index, executed = 0, 0
    while True:
        round_index += 1
        if round_index > contract["max_rounds"]:
            return wrong
        if timing == "before_observation":
            stop = verdict(timing, round_index)
            if stop is None:
                return wrong
            if stop:
                break
        opened = take("ROUND_OPENED", round_index)
        if opened is None:
            return wrong
        where = f"episode {name!r} journal #{opened['sequence']} ROUND_OPENED"
        if opened.get("pre_state") != walk["current"]:
            problems.append(f"{where} does not open on the state the previous round closed on")
        if opened.get("round_identity") != identity(
                "round", {"episode": episode, "round": round_index,
                          "pre_state": walk["current"]}):
            problems.append(f"{where} RoundIdentity does not recompute from episode x round x "
                            "pre-state")
        cut = False
        for node in order:
            ready = take("STEP_READY", round_index)
            if ready is None:
                return wrong
            if node["id"] != anchor:
                continue
            stop = verdict(timing, round_index)
            if stop is None:
                return wrong
            evaluated = pending[walk["cursor"] - 1]
            if any(r.get("step") == ready["step"] and r["sequence"] > evaluated["sequence"]
                   for r in mine):
                problems.append(f"episode {name!r} journal #{evaluated['sequence']} "
                                "TERMINATION_EVALUATED precedes the commit of its timing point "
                                f"{node['id']!r}")
            if stop:
                cut = True
                break
        closed = take("ROUND_COMPLETED", round_index)
        if closed is None:
            return wrong
        walk["current"] = closed.get("post_state")
        executed = round_index
        if cut:
            break
        if timing == "after_round_close":
            stop = verdict(timing, round_index)
            if stop is None:
                return wrong
            if stop:
                break
        if round_index == contract["max_rounds"]:
            if verdict("safety_bound", round_index) is None:
                return wrong
            break
    completed = take("EPISODE_COMPLETED", None)
    if completed is None or walk["cursor"] != len(pending):
        return wrong
    if completed.get("rounds") != executed:
        problems.append(f"episode {name!r} journal #{completed['sequence']} EPISODE_COMPLETED "
                        f"completed {completed.get('rounds')} rounds; the round contract "
                        f"terminates at {executed}")
    return problems


def round_contract(document) -> dict:
    """The closed round contract reader: `bvl-round-contract-1` (BVL T4-001, bound x
    registered rule) or `bvl-round-contract-2` (BVL T4-002, the rule's timing declared)."""
    if not isinstance(document, dict) \
            or set(document) != {"schema", "max_rounds", "termination"} \
            or document["schema"] not in (ROUND_CONTRACT_SCHEMA, ROUND_CONTRACT_SCHEMA_2):
        raise ValueError("round contract has the wrong closed shape")
    if document["schema"] == ROUND_CONTRACT_SCHEMA_2:
        return timed_round_contract(document)
    termination = document["termination"]
    if not isinstance(termination, dict) or set(termination) != {"rule", "config"}:
        raise ValueError("round termination has the wrong closed shape")
    if termination["rule"] != FIXED_COUNT_RULE:
        raise ValueError(f"termination rule {termination['rule']!r} is not registered")
    config = termination["config"]
    if not isinstance(config, dict) or set(config) != {"count"} or not _positive(config["count"]):
        raise ValueError("fixed-count termination config is exactly a positive count")
    if not _positive(document["max_rounds"]) or config["count"] > document["max_rounds"]:
        raise ValueError("round contract count exceeds its safety bound max_rounds")
    return document


def protocol_rounds(protocol: dict) -> int:
    """The rounds a Protocol IR plans: the ir-1 bound or the ir-2 contract's count."""
    if "round" in protocol:
        termination = protocol["round"]["termination"]
        return termination["config"]["count"] if termination["rule"] == FIXED_COUNT_RULE \
            else protocol["round"]["max_rounds"]
    return protocol["rounds"]


def termination_verdict(contract: dict, rounds_closed: int) -> dict:
    """The verdict a round contract derives after *rounds_closed* rounds closed."""
    reached = rounds_closed >= contract["termination"]["config"]["count"]
    return {"schema": TERMINATION_VERDICT_SCHEMA,
            "rule": identity("termination_rule", contract["termination"]),
            "rounds_closed": rounds_closed, "max_rounds": contract["max_rounds"],
            "verdict": "TERMINATE" if reached else "CONTINUE",
            "reason": "FIXED_COUNT_REACHED" if reached else "FIXED_COUNT_NOT_REACHED"}


_ROUND_LIFECYCLE = ("ROUND_OPENED", "STEP_READY", "ROUND_COMPLETED", "TERMINATION_EVALUATED",
                    "EPISODE_COMPLETED")


def round_problems(contract, episode: dict, mine: list, initial: dict, name: str) -> list:
    """Why one completed episode's rounds are not its plan's round contract (BVL T4-001).

    Under a contract: rounds 1..count each open once on the state the previous
    one closed on (RoundIdentity = episode x round x pre-state recomputes), run
    their steps, close, and carry exactly the derived verdict; the episode
    completes at the one TERMINATE.  Without a contract no such evidence exists.
    """
    lifecycle = [r for r in mine if r["event"] in _ROUND_LIFECYCLE]
    if contract is None:
        return [f"episode {name!r} journal #{r['sequence']} is {r['event']}; the plan has no "
                "round contract" for r in lifecycle
                if r["event"] in ("ROUND_OPENED", "TERMINATION_EVALUATED")]
    count = contract["termination"]["config"]["count"]
    shape = []
    for record in lifecycle:
        entry = (record["event"], record.get("round"))
        if record["event"] != "STEP_READY" or not shape or shape[-1] != entry:
            shape.append(entry)
    expected = []
    for index in range(1, count + 1):
        expected += [("ROUND_OPENED", index), ("STEP_READY", index), ("ROUND_COMPLETED", index),
                     ("TERMINATION_EVALUATED", index)]
    expected.append(("EPISODE_COMPLETED", None))
    if shape != expected:
        return [f"episode {name!r} round lifecycle is not open -> steps -> close -> termination "
                f"for exactly rounds 1..{count} of its round contract"]
    problems, current = [], initial
    for record in lifecycle:
        where = f"episode {name!r} journal #{record['sequence']} {record['event']}"
        if record["event"] == "ROUND_OPENED":
            if record.get("pre_state") != current:
                problems.append(f"{where} does not open on the state the previous round "
                                "closed on")
            if record.get("round_identity") != identity(
                    "round", {"episode": episode, "round": record["round"],
                              "pre_state": current}):
                problems.append(f"{where} RoundIdentity does not recompute from episode x "
                                "round x pre-state")
        elif record["event"] == "ROUND_COMPLETED":
            current = record.get("post_state")
        elif record["event"] == "TERMINATION_EVALUATED":
            verdict = termination_verdict(contract, record["round"])
            # a timing point is a timed contract's evidence (BVL T4-002), never this one's
            if "point" in record or record.get("termination") != verdict \
                    or record.get("terminate") is not (verdict["verdict"] == "TERMINATE"):
                problems.append(f"{where} is not the verdict the plan's round contract derives")
        elif record["event"] == "EPISODE_COMPLETED" and record.get("rounds") != count:
            problems.append(f"{where} completed {record.get('rounds')} rounds; the round "
                            f"contract terminates at {count}")
    return problems


def protocol_ir(document) -> dict:
    """The closed `bvl-protocol-ir-1` / `-2` reader: id -> node, in canonical node order."""
    if not isinstance(document, dict):
        raise ValueError("protocol IR has the wrong closed shape")
    if document.get("schema") == PROTOCOL_SCHEMA_2:
        if set(document) != {"schema", "round", "nodes"}:
            raise ValueError("protocol IR has the wrong closed shape")
        round_contract(document["round"])
    else:
        if set(document) != {"schema", "rounds", "nodes"}:
            raise ValueError("protocol IR has the wrong closed shape")
        if document["schema"] != PROTOCOL_SCHEMA:
            raise ValueError(f"protocol IR schema is exactly {PROTOCOL_SCHEMA!r} or "
                             f"{PROTOCOL_SCHEMA_2!r}")
        rounds = document["rounds"]
        if isinstance(rounds, bool) or not isinstance(rounds, int) or rounds < 1:
            raise ValueError("protocol IR rounds is a positive integer")
    nodes = document["nodes"]
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("protocol IR has at least one node")
    by_id: dict[str, dict] = {}
    for node in nodes:
        if not isinstance(node, dict) or set(node) != {"id", "kind", "depends_on", "config"}:
            raise ValueError("protocol IR node has the wrong closed shape")
        if node["kind"] not in NODE_KINDS or not isinstance(node["config"], dict) \
                or not isinstance(node["depends_on"], list) or node["id"] in by_id \
                or node["id"] in node["depends_on"] \
                or len(set(node["depends_on"])) != len(node["depends_on"]):
            raise ValueError(f"protocol IR node {node.get('id')!r} is malformed")
        by_id[node["id"]] = node
    if [node["id"] for node in nodes] != sorted(by_id):
        raise ValueError("protocol IR nodes are not in canonical node order")
    for node in nodes:
        if set(node["depends_on"]) - set(by_id):
            raise ValueError(f"protocol IR node {node['id']!r} depends on unknown nodes")
    topological_order(by_id)
    if "round" in document and any(node["kind"] == "termination" for node in nodes):
        raise ValueError("a termination node under a round contract")
    if "round" in document:
        # BVL T4-002: a mid-round timing has its point in this round body
        termination_anchor(document["round"],
                           [by_id[node_id] for node_id in topological_order(by_id)])
    return by_id


# ------------------------------------------------------------ result
class Result:
    """Rule statuses of one read. Every M4 rule is listed; the ones the package's meaning
    does not evaluate stay NOT_EVALUATED."""

    def __init__(self, evaluated) -> None:
        self.evaluated = tuple(evaluated)
        self.rules = {rule: {"status": NOT_EVALUATED, "problems": []} for rule in RULES}
        # the reader's own L1 dataset reconstruction (BVL T1-008), when reached
        self.dataset: dict | None = None
        self.level: str | None = None
        # the reader's own recomputation of a bound analysis (BVL T1-009)
        self.analysis: dict | None = None
        # the reader's own count of who answered the run's actor calls (BVL T5)
        self.external: dict | None = None

    def rule(self, rule: str, problems: list[str]) -> bool:
        self.rules[rule] = {"status": FAIL if problems else PASS, "problems": problems}
        return not problems

    @property
    def failed(self) -> list[str]:
        return [rule for rule, value in self.rules.items() if value["status"] == FAIL]

    def pending(self) -> str | None:
        """The first rule of this meaning not yet evaluated."""
        return next((rule for rule in self.evaluated
                     if self.rules[rule]["status"] == NOT_EVALUATED), None)


# What a VERIFIED result does not establish: stated, never implied.
CONSUMER_LIMITATIONS = {
    CONFORMANCE: (
        ("CONFORMANCE_NOT_SCIENTIFIC_EVIDENCE",
         "a VERIFIED CONFORMANCE package says the run conformed to its frozen plan and "
         "protocol; it is not scientific evidence and supports no scientific claim"),
        ("NOT_SIGNED",
         "the package carries no signature: who produced these bytes is not established"),
        ("WORLD_CODE_NOT_REPLAYED",
         "World transitions are checked for identity, chaining, admissibility and "
         "progression as evidenced; the World's code is not executed by this reader"),
        ("ACTOR_CALLS_NOT_REEXECUTED",
         "responses are bound by digest to custody; no model or provider call is repeated"),
        ("BUILD_AND_PLUGIN_SET_SELF_REPORTED",
         "build and plugin-set identities recompute from the execution binding document, "
         "whose content is the producer's own statement"),
        ("GATE_INPUTS_SUPPLIED_NOT_DERIVED",
         "gate-2 inputs (coverage, GNDCRW result set) are bound and re-walked as supplied; "
         "GNDCRW itself is not re-run"),
    ),
    MEMBER_INVENTORY: (
        ("CONFORMANCE_NOT_CLAIMED",
         "a pre-attestation manifest-4 is a member inventory: these members, these bytes. "
         "No conformance rule was evaluated and no conformance is established"),
        ("UNLISTED_FILES_NOT_EVALUATED",
         "the inventory meaning does not cover files outside the member list"),
        ("NOT_SIGNED",
         "the package carries no signature: who produced these bytes is not established"),
    ),
}
# stated only for a package a person or a tool answered in (BVL T5)
EXTERNAL_ACTOR_LIMITATION = (
    "HUMAN_AND_TOOL_ACTS_NOT_REENACTED",
    "human exchanges and tool calls are re-derived from their evidence under the plan's "
    "contracts; nobody is asked and no tool is called: who the pseudonymous participant "
    "is, what the operator was told and what a tool changed on its site are not "
    "established, and an argument selected from a frozen resource is held to one value "
    "across the run, not re-read")
L1_DATASET_LIMITATION = (
    "OBSERVATION_DIGESTS_ATTESTED_NOT_RECOMPUTED",
    "L1 dataset units carry observation digests as the producer attested them")
NOT_IN_MEANING = "not part of the MEMBER_INVENTORY meaning: no conformance claim to evaluate"
AFTER_FAILURE = "not reached: an earlier rule failed"


# ------------------------------------------------------------ dispatch
def verify(pkg, result: dict) -> None:
    """Verify the MANIFEST-4 package behind `pkg` (epc_reader.Package: contained,
    link-free reads) and fill `result`. Raises Refused when it is not a package this
    reader was written for; a verdict (VERIFIED / REJECTED) is never raised."""
    try:
        data = pkg.read(MANIFEST_4)
    except LookupError as error:
        raise Refused(ErrorCode.MANIFEST_NOT_READABLE, f"{MANIFEST_4}: {error}") from None
    result["input"]["manifest_digest"] = sha(data)
    try:
        manifest = parse(data)
    except ValueError as error:
        raise Refused(ErrorCode.JSON_PARSE_ERROR, f"{MANIFEST_4}: {error}") from None
    schema = manifest.get("schema") if isinstance(manifest, dict) else None
    if not isinstance(schema, str) or schema != MANIFEST_4_SCHEMA:
        raise Refused(ErrorCode.UNSUPPORTED_MANIFEST_SCHEMA,
                      f"{MANIFEST_4} schema {schema!r}; this reader handles "
                      f"{MANIFEST_4_SCHEMA!r} only")
    members = manifest.get("members") if isinstance(manifest.get("members"), list) else []
    roles = [m.get("role") for m in members if isinstance(m, dict)]
    limitations = manifest.get("limitations")
    conformance = any(isinstance(role, str) and role == "conformance_attestation"
                      for role in roles) or (
        isinstance(limitations, list) and CONFORMANCE_LIMITATIONS[0] in [
            x for x in limitations if isinstance(x, str)])
    meaning = CONFORMANCE if conformance else MEMBER_INVENTORY
    result["dispatch"] = {"manifest_file": MANIFEST_4, "manifest_schema": schema,
                          "handler": HANDLER, "meaning": meaning}
    rules = Result(RULES if conformance else INVENTORY_RULES)
    try:
        attestation = _verify_manifest_4(pkg, data, manifest, conformance, rules)
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, LookupError,
            ArithmeticError) as error:
        rules.rule(rules.pending() or "M4-ATT",
                   [f"evidence is malformed: {type(error).__name__}: {error}"])
        attestation = None
    failed = rules.failed
    outcome = REJECTED if failed else VERIFIED
    try:
        manifest_identity = identity("evidence_manifest", manifest)
    except ValueError:  # a manifest with no canonical form has no identity (M4-MAN FAIL)
        manifest_identity = None
    result["outcome"] = outcome
    result["failed_rules"] = failed
    result["meaning"] = meaning
    result["package_class"] = manifest.get("package_class")
    result["plan"] = manifest.get("plan")
    result["manifest_identity"] = manifest_identity
    result["package_identity"] = manifest_identity["digest"] if manifest_identity else None
    if meaning == MEMBER_INVENTORY:
        result["conformance"] = "NOT_CLAIMED"
    if manifest.get("package_class") == "SCIENTIFIC":
        result["scientific"] = "NOT_SUPPORTED"
    result["rules"] = _rule_entries(rules)
    observed = {"members": len(members)}
    if rules.level is not None:
        observed["evidence_level"] = rules.level
    if rules.dataset is not None:
        observed["dataset_units"] = rules.dataset
    if rules.analysis is not None:
        observed["analysis"] = rules.analysis
    if rules.external is not None:
        observed["external_actors"] = rules.external
    if attestation is not None and outcome == VERIFIED:
        observed["attested"] = {name: attestation[name] for name in (
            "experiment_id", "run", "protocol_ir", "episodes", "steps_by_kind",
            "custody_accepted_calls", "world_transitions_applied")}
    result["observed"] = observed
    consumer = [{"code": code, "detail": detail}
                for code, detail in CONSUMER_LIMITATIONS[meaning]]
    if rules.level == "L1":
        consumer.append(dict(zip(("code", "detail"), L1_DATASET_LIMITATION)))
    if rules.external is not None and (rules.external["human_exchanges"]
                                       or rules.external["tool_calls"]):
        consumer.append(dict(zip(("code", "detail"), EXTERNAL_ACTOR_LIMITATION)))
    result["limitations"] = {
        "producer_declared": limitations if isinstance(limitations, list) else [],
        "producer_declared_codes": sorted({x for x in limitations if isinstance(x, str)})
        if isinstance(limitations, list) else [],
        "consumer": consumer}


def _rule_entries(rules: Result) -> list[dict]:
    """The rule statuses as the FULLMT result lists them (registry order)."""
    entries = []
    for rule in RULES:
        layer, title = M4_RULES[rule]
        value = rules.rules[rule]
        entry = {"rule_id": rule, "layer": layer, "title": title, "status": value["status"]}
        if value["problems"]:
            entry["problems"] = value["problems"]
        if value["status"] == NOT_EVALUATED:
            entry["note"] = NOT_IN_MEANING if rule not in rules.evaluated else AFTER_FAILURE
        entries.append(entry)
    return entries


# ------------------------------------------------------------ manifest-4 rules
def _verify_manifest_4(pkg, data: bytes, manifest: dict, conformance: bool,
                       result: Result) -> dict | None:
    # M4-MAN
    problems = []
    if set(manifest) != MANIFEST_KEYS:
        problems.append(f"manifest members are {sorted(manifest)}, not {sorted(MANIFEST_KEYS)}")
    try:
        at_rest = canonical(manifest) == data
    except ValueError:
        at_rest = False
    if not at_rest:
        problems.append("the manifest is not canonical-json-1 at rest")
    plan = manifest.get("plan")
    if not isinstance(plan, dict) or set(plan) != {"kind", "digest"} \
            or plan.get("kind") != "plan" or not is_digest(plan.get("digest")):
        problems.append("the manifest plan is not a PlanIdentity")
    listed = manifest.get("members") if isinstance(manifest.get("members"), list) else None
    by_path: dict[str, dict] = {}
    for member in [None] if listed is None else listed:
        if not isinstance(member, dict) or set(member) != MEMBER_KEYS \
                or not portable(member["path"]) or not isinstance(member["role"], str) \
                or member["role"] not in ROLES \
                or not is_digest(member["digest"]) or isinstance(member["size"], bool) \
                or not isinstance(member["size"], int) or member["size"] < 0:
            problems.append(f"malformed member {member!r}")
            continue
        if member["path"] in by_path:
            problems.append(f"{member['path']} listed twice")
        by_path[member["path"]] = member
    paths = [m["path"] for m in listed or [] if isinstance(m, dict)
             and isinstance(m.get("path"), str)]
    if paths != sorted(paths):
        problems.append("members are not in path order")
    if MANIFEST_4 in by_path:
        problems.append(f"{MANIFEST_4} lists itself as a member")
    limitations = manifest.get("limitations")
    if not isinstance(limitations, list) or not all(isinstance(x, str) for x in limitations) \
            or limitations != sorted(set(limitations)):
        problems.append("limitations are not a sorted list of unique codes")
    result.rule("M4-MAN", problems)

    # M4-MEM: each member is read here, once; every later rule works on these bytes
    held, problems = {}, []
    for path, member in by_path.items():
        try:
            held[path] = pkg.read(path)
        except LookupError as error:
            problems.append(f"{path} is missing, a link, or outside the root ({error})")
            continue
        if sha(held[path]) != member["digest"]:
            problems.append(f"{path}: SHA-256 is not the listed digest")
        if len(held[path]) != member["size"]:
            problems.append(f"{path}: {len(held[path])} bytes, not the listed "
                            f"{member['size']}")
    result.rule("M4-MEM", problems)

    # M4-CLS
    problems = []
    package_class = manifest.get("package_class")
    if not isinstance(package_class, str) or package_class not in PACKAGE_CLASSES:
        problems.append(f"unknown package class {package_class!r}")
    elif package_class != "CONFORMANCE":
        problems.append(f"no {package_class} manifest-4 semantics exist "
                        "(BVL-REC-102 / BVL-REC-104); only CONFORMANCE is read")
    if conformance and limitations != CONFORMANCE_LIMITATIONS:
        problems.append(f"CONFORMANCE limitations are {limitations!r}, "
                        f"not {CONFORMANCE_LIMITATIONS!r}")
    result.rule("M4-CLS", problems)
    if not conformance:
        return None

    # M4-UNL
    present, odd = pkg.files()
    problems = [f"{p} is not a member" for p in sorted(present - set(by_path) - {MANIFEST_4})]
    problems += [f"{p} is a link, a reparse point or not a regular file" for p in sorted(odd)]
    result.rule("M4-UNL", problems)

    # M4-ROL
    problems, documents = [], {}
    for path, member in by_path.items():
        role = layout_role(path)
        if member["role"] != role:
            problems.append(f"{path} is listed as {member['role']!r}; its place is {role!r}")
            continue
        if path not in held or role in ("response", "custody", "episode_lineage"):
            continue
        try:
            documents[path] = strict(held[path])
        except (ValueError, UnicodeDecodeError) as error:
            problems.append(f"{path}: {error}")
            continue
        name = path.rsplit("/", 1)[1].removesuffix(".json").removeprefix("request-")
        if sha(held[path]) != f"sha256:{name}":
            problems.append(f"{path} is not named by its content digest")
    if not result.rule("M4-ROL", problems) or result.failed:
        return None
    return _conformance(manifest, by_path, held, documents, result)


def _of_role(by_path: dict, documents: dict, role: str) -> list[tuple[str, dict]]:
    return [(path, documents[path]) for path, member in sorted(by_path.items())
            if member["role"] == role]


def _ref(path: str, by_path: dict) -> dict:
    member = by_path[path]
    return {"schema": REF_SCHEMA, "role": member["role"], "path": path,
            "digest": member["digest"], "size": member["size"]}


def _conformance(manifest: dict, by_path: dict, held: dict, documents: dict,
                 result: Result) -> dict | None:
    plan = manifest["plan"]

    # M4-JRN
    problems = []
    journal_bytes = held.get("journal-2.jsonl", b"")
    if journal_bytes and not journal_bytes.endswith(b"\n"):
        problems.append("journal-2 has a torn tail")
    records = []
    for index, line in enumerate(journal_bytes.splitlines()):
        try:
            record = strict(line)
        except (ValueError, UnicodeDecodeError) as error:
            problems.append(f"journal-2 line {index}: {error}")
            continue
        if not isinstance(record, dict) or record.get("schema") != JOURNAL_SCHEMA \
                or record.get("sequence") != index:
            problems.append(f"journal-2 line {index} is not record #{index}")
            continue
        records.append(record)
    if not records or records[0].get("event") != "RUN_OPENED":
        problems.append("journal-2 does not open with RUN_OPENED at position 0")
    runs = {record.get("run") for record in records}
    if len(runs) != 1:
        problems.append(f"journal-2 names runs {sorted(map(str, runs))}")
    for record in records:
        if record["event"] in NON_CONFORMANT:
            problems.append(f"journal-2 #{record['sequence']} is {record['event']}")
        if record["event"] == "RUN_OPENED" and record["sequence"] != 0:
            problems.append("RUN_OPENED appears after journal-2 position 0")
    if not result.rule("M4-JRN", problems):
        return None
    opened_run = records[0]

    # M4-AUT
    problems, gate_document = [], None
    gates = _of_role(by_path, documents, "gate")
    bindings = _of_role(by_path, documents, "execution_binding")
    authorization = None
    if len(gates) != 1 or len(bindings) != 1:
        problems.append(f"{len(gates)} gate and {len(bindings)} execution_binding members, "
                        "not one each")
    else:
        (gate_path, gate), (binding_path, binding) = gates[0], bindings[0]
        gate_document = gate
        if set(gate) != GATE_KEYS or gate["schema"] != GATE_SCHEMA:
            problems.append("the gate is not a closed gate-2 decision")
        elif gate["decision"] != "CLEARED" or gate["reasons"] != [] or gate["plan"] != plan:
            problems.append("gate-2 did not CLEAR this plan")
        bound = identity("execution_binding", {
            "plan": binding.get("plan"), "build_identity": binding.get("build_identity"),
            "plugin_set_identity": binding.get("plugin_set_identity")})
        if binding.get("plan") != plan or binding.get("execution_binding_identity") != bound:
            problems.append("the execution binding does not recompute for this plan")
        if binding.get("build_identity") != identity("build", binding.get("build")) \
                or binding.get("plugin_set_identity") != identity(
                    "plugin_set", binding.get("plugin_manifest")):
            problems.append("the build / plugin-set identities do not recompute")
        authorization = identity("authorization", {
            "plan": plan, "binding": bound, "coverage_identity": gate.get("coverage"),
            "gndcrw_result_set_identity": gate.get("gndcrw_results"),
            "gate_identity": identity("gate_decision", gate)})
        expected = {"plan": plan, "binding": bound, "authorization": authorization,
                    "gate": _ref(gate_path, by_path),
                    "binding_evidence": _ref(binding_path, by_path)}
        for name, value in expected.items():
            if opened_run.get(name) != value:
                problems.append(f"RUN_OPENED {name} is not the recomputed one")
    if not result.rule("M4-AUT", problems):
        return None

    # M4-PLN
    problems, nodes, semantic, contracts, decisions = [], None, None, None, None
    plans = _of_role(by_path, documents, "plan")
    if len(plans) != 1:
        problems.append(f"{len(plans)} plan members, not one")
    else:
        plan_path, plan_document = plans[0]
        semantic = plan_document.get("plan")
        if set(plan_document) != {"schema", "identity", "plan"} \
                or plan_document["schema"] != PLAN_EVIDENCE_SCHEMA:
            problems.append("plan evidence has the wrong closed shape")
        elif identity("plan", semantic) != plan or plan_document["identity"] != plan:
            problems.append("plan evidence does not recompute the manifest PlanIdentity")
        elif not isinstance(semantic, dict) \
                or semantic.get("schema") not in SEMANTIC_PLAN_SHAPES \
                or set(semantic) not in SEMANTIC_PLAN_SHAPES[semantic["schema"]]:
            problems.append("semantic plan has the wrong closed shape")
        else:
            try:
                nodes = protocol_ir(semantic["protocol"])
            except ValueError as error:
                problems.append(f"plan protocol is not a Protocol IR: {error}")
            else:
                if "actors" in semantic:
                    problems.extend(_actor_problems(semantic["actors"], nodes))
                if "information" in semantic and not problems:
                    problems.extend(_information_problems(semantic["information"],
                                                          semantic["actors"], nodes))
                if "proposals" in semantic and not problems:
                    contracts, found = _proposal_contracts(semantic["proposals"], nodes)
                    problems.extend(found)
                if "decisions" in semantic and not problems:
                    decisions, found = _decision_contracts(semantic["decisions"], nodes,
                                                           contracts)
                    problems.extend(found)
                if "analysis" in semantic and not problems:
                    problems.extend(_analysis_contract_problems(semantic["analysis"]))
                if "seed" in semantic and not _is_seed_tree(semantic["seed"]):
                    problems.append("plan seed is not a closed bvl-seed-tree-1")
                if "world" in semantic and not problems:
                    problems.extend(_world_contract_problems(semantic, nodes))
                if not problems:
                    problems.extend(_memory_plan_problems(semantic, nodes))
                if not problems:
                    problems.extend(_external_plan_problems(semantic))
    if not result.rule("M4-PLN", problems):
        return None
    policies = memory_policies(nodes)
    protocol = semantic["protocol"]
    order = [nodes[node_id] for node_id in topological_order(nodes)]

    # M4-EPI
    problems, steps, episodes = [], {}, []
    opened = [r for r in records if r["event"] == "EPISODE_OPENED"]
    key_of = {r.get("episode"): r.get("episode_key") for r in opened}
    if not opened:
        problems.append("the run executed no episode")
    episode_keys = [r.get("episode_key") for r in opened]
    if len(episode_keys) != len(set(episode_keys)):
        problems.append("an episode_key is opened twice")
    for record in opened:
        episode = identity("episode", {"plan": plan, "authorization": authorization,
                                       "episode_key": record["episode_key"]})
        name = record["episode_key"]
        if record.get("plan") != plan or record["episode"] != key(episode):
            problems.append(f"episode {name!r} does not recompute from "
                            "plan x authorization x episode_key")
            continue
        mine = [r for r in records if r.get("episode") == record["episode"]
                and r["sequence"] > record["sequence"]]
        ready = [r for r in mine if r["event"] == "STEP_READY"]
        completed = [r for r in mine if r["event"] == "EPISODE_COMPLETED"]
        planned = [(round_index, node)
                   for round_index in range(1, protocol_rounds(protocol) + 1)
                   for node in order]
        if len(completed) != 1:
            problems.append(f"episode {name!r} is not completed exactly once")
            continue
        if not ready or len(ready) > len(planned):
            problems.append(f"episode {name!r} has {len(ready)} steps; the IR plans "
                            f"{len(planned)}")
            continue
        broken = False
        for item, (round_index, node) in zip(ready, planned, strict=False):
            step = identity("step", {"episode": episode, "round": round_index,
                                     "node": node["id"], "kind": node["kind"]})
            if item["step"] != key(step) or item["round"] != round_index:
                problems.append(f"episode {name!r} journal #{item['sequence']} is not IR step "
                                f"{node['id']!r} of round {round_index}")
                broken = True
                break
            steps[item["step"]] = {"episode": record["episode"], "round": round_index,
                                   "node": node, "ready": item["sequence"], "output": None}
        if broken:
            continue
        full = len(ready) == len(planned)
        last_round, last_node = planned[len(ready) - 1]
        timed = "timing" in protocol.get("round", {}).get("termination", {})
        # a timed round contract ends the episode at its verdict (BVL T4-002)
        if not full and not timed and last_node["kind"] != "termination":
            problems.append(f"episode {name!r} stopped after {last_node['id']!r} "
                            f"(round {last_round}), not at an IR termination")
        if completed[0].get("rounds") != last_round:
            problems.append(f"episode {name!r} completed {completed[0].get('rounds')} rounds, "
                            f"its steps cover {last_round}")
        closed = [r["round"] for r in mine if r["event"] == "ROUND_COMPLETED"]
        if closed != list(range(1, last_round + 1)):
            problems.append(f"episode {name!r} rounds closed {closed}")
        world_contract = semantic.get("world")
        state_schema = (f"{world_contract['state_schema']['schema_id']}:"
                        f"{world_contract['state_schema']['version']}"
                        if world_contract else None)
        initial_identity = world_state_identity(semantic["initial_world_state"], state_schema)
        if timed:
            # every evidenced state, by the identity its own content recomputes to
            states = {canonical(initial_identity): semantic["initial_world_state"]}
            for path, held_state in documents.items():
                if path.startswith("evidence-v2/world_state/") \
                        and isinstance(held_state, dict) \
                        and isinstance(held_state.get("state"), dict):
                    states[canonical(world_state_identity(
                        held_state["state"], state_schema))] = held_state["state"]
            problems += timed_round_problems(protocol["round"], episode, mine,
                                             initial_identity, name, order, states)
        else:
            problems += round_problems(protocol.get("round"), episode, mine, initial_identity,
                                       name)
        episodes.append({"episode": episode, "episode_key": name,
                         "rounds_planned": protocol_rounds(protocol),
                         "rounds_executed": completed[0].get("rounds"),
                         "steps": len(ready), "terminated_by_ir": not full})
    known = {r["episode"] for r in opened}
    strays = sorted({r["episode"] for r in records if "episode" in r} - known)
    if strays:
        problems.append(f"journal-2 carries events of unopened episodes {strays}")
    dag = identity("protocol_dag", protocol_dag(protocol))
    schedule, schedule_problems = experiment_schedule(opened, dag)
    problems += schedule_problems
    for item in episodes:
        item["schedule_position"] = (schedule["episodes"].index(item["episode_key"])
                                     if schedule else None)
    if not result.rule("M4-EPI", problems):
        return None

    # M4-CMT
    problems, commits = [], {}
    commit_events = set(COMMIT_EVENT.values())
    for record in records:
        if "step" not in record or record["event"] == "STEP_READY":
            continue
        step = steps.get(record["step"])
        if step is None:
            problems.append(f"journal-2 #{record['sequence']} names a step outside the IR")
            continue
        if record.get("round") != step["round"] or record["sequence"] < step["ready"]:
            problems.append(f"journal-2 #{record['sequence']} is out of its step's round/order")
        if record["event"] in commit_events:
            kind = step["node"]["kind"]
            if record["event"] != COMMIT_EVENT.get(kind):
                problems.append(f"step {step['node']['id']!r} ({kind}) carries "
                                f"{record['event']}")
            elif record["step"] in commits:
                problems.append(f"step {step['node']['id']!r} round {step['round']} "
                                "committed twice")
            else:
                commits[record["step"]] = record
    for step_key, step in steps.items():
        kind = step["node"]["kind"]
        if kind in COMMIT_EVENT and step_key not in commits:
            problems.append(f"step {step['node']['id']!r} round {step['round']} has no "
                            f"{COMMIT_EVENT[kind]}")
    located = {(s["episode"], s["round"], s["node"]["id"]): k for k, s in steps.items()}
    for step in steps.values():
        for dependency in step["node"]["depends_on"]:
            source = located.get((step["episode"], step["round"], dependency))
            if source is None or steps[source]["node"]["kind"] not in COMMIT_EVENT:
                continue
            commit = commits.get(source)
            if commit is None or commit["sequence"] > step["ready"]:
                problems.append(f"step {step['node']['id']!r} round {step['round']} became "
                                f"ready before dependency {dependency!r} committed "
                                f"{COMMIT_EVENT[steps[source]['node']['kind']]}")
    if not result.rule("M4-CMT", problems):
        return None

    # M4-ART
    problems, by_role = [], {}
    for role, (kind, fields) in ARTIFACT_FIELDS.items():
        indexed = {}
        for path, document in _of_role(by_path, documents, role):
            if role == "proposal":
                expected = PROPOSAL_EVIDENCE_1 if contracts is None else PROPOSAL_EVIDENCE_2
                if document.get("schema") != expected:
                    problems.append(f"{path} is not {expected} evidence")
                    continue
                fields = PROPOSAL_FIELDS[expected]
            elif role == "decision":
                expected = DECISION_EVIDENCE_1 if decisions is None else DECISION_EVIDENCE_2
                if document.get("schema") != expected:
                    problems.append(f"{path} is not {expected} evidence")
                    continue
                fields = DECISION_FIELDS[expected]
            else:
                shapes = ({MEMORY_ARTIFACT_2: MEMORY_FIELDS_2,
                           MEMORY_ARTIFACT_3: MEMORY_FIELDS_3} if policies
                          else {MEMORY_ARTIFACT_1: MEMORY_FIELDS_1})
                if document.get("schema") not in shapes:
                    problems.append(f"{path} is not {' / '.join(shapes)} evidence")
                    continue
                fields = shapes[document["schema"]]
                if set(document) != {"schema", "identity", *fields}:
                    problems.append(f"{path} has the wrong closed shape")
                    continue
            # SV-07: of every role - a member the schema does not name is in no identity
            # (a proposal and a decision omit the members they state null)
            if not set(document) <= {"schema", "identity", *fields}:
                problems.append(f"{path} has the wrong closed shape")
                continue
            payload = {name: document.get(name) for name in fields}
            if role == "proposal":
                payload["proposal"] = payload.pop("value")
            if document.get("identity") != identity(kind, payload):
                problems.append(f"{path} identity does not recompute from its content")
                continue
            indexed[key(document["identity"])] = document
        by_role[role] = indexed
    event_field = {"PROPOSAL_PARSED": ("proposal", "proposal"),
                   "DECISION_RECORDED": ("decision", "decision"),
                   "MEMORY_RECORDED": ("memory", "memory")}
    referenced = {role: set() for role in by_role}
    for step_key, record in commits.items():
        step = steps[step_key]
        if record["event"] == "CUSTODY_ACCEPTED":
            step["output"] = record["call"]
        elif record["event"] == "WORLD_APPLIED":
            step["output"] = key(record["transition"])
        else:
            role, name = event_field[record["event"]]
            artifact = key(record[name]["identity"])
            document = by_role[role].get(artifact)
            if document is None:
                problems.append(f"{record['event']} {artifact} has no {role} evidence")
                continue
            if role != "memory" and (key(document["step"]) != step_key
                                     or key(document["episode"]) != step["episode"]):
                problems.append(f"{role} evidence {artifact} belongs to another step")
            if document["round"] != step["round"]:
                problems.append(f"{role} evidence {artifact} belongs to another round")
            if role == "proposal" and contracts is not None:
                problems.extend(f"proposal evidence {artifact}: {problem}" for problem in
                                _committed_proposal_problems(document,
                                                             contracts[step["node"]["id"]]))
            referenced[role].add(artifact)
            step["output"] = artifact
    for role, indexed in by_role.items():
        stray = sorted(set(indexed) - referenced[role])
        if stray:
            problems.append(f"{role} evidence not committed by journal-2: {stray}")
    if not result.rule("M4-ART", problems):
        return None

    # M4-CUS
    problems, entries = [], []
    custody_bytes = held.get("custody-v2/entries.jsonl", b"")
    if custody_bytes and not custody_bytes.endswith(b"\n"):
        problems.append("custody-v2 has a torn tail")
    for index, line in enumerate(custody_bytes.splitlines()):
        try:
            entries.append(strict(line))
        except (ValueError, UnicodeDecodeError) as error:
            problems.append(f"custody-v2 line {index}: {error}")
    by_identity = {key(identity("custody_entry", entry)): entry for entry in entries}
    accepted = [r for r in commits.values() if r["event"] == "CUSTODY_ACCEPTED"]
    for record in accepted:
        entry = by_identity.get(key(record["custody"]))
        if entry is None:
            problems.append(f"{record['call']}: no custody entry recomputes its identity")
            continue
        if entry.get("call") != record["call"] or entry.get("step") != record["step"] \
                or entry.get("artifact") != record.get("artifact"):
            problems.append(f"{record['call']}: custody entry is another call's")
        artifact = f"artifacts/{entry['artifact']['name']}"
        if artifact not in held or sha(held[artifact]) != entry["artifact"]["content"]:
            problems.append(f"{record['call']}: response member is not the custody artifact")
        request = entry.get("request", {})
        request_path = f"requests-v2/{request.get('name')}"
        if request.get("schema") != REQUEST_REF_SCHEMA or request_path not in held \
                or sha(held[request_path]) != request["identity"]["digest"] \
                or len(held[request_path]) != request.get("size"):
            problems.append(f"{record['call']}: request member is not the custody request")
    if {e.get("call") for e in entries} != {r["call"] for r in accepted} \
            or len(entries) != len(accepted):
        problems.append("custody entries are not exactly the IR's accepted actor calls")
    calls_held = {p for p, m in by_path.items() if m["role"] in ("request", "response")}
    calls_named = {f"artifacts/{e['artifact']['name']}" for e in entries if "artifact" in e} \
        | {f"requests-v2/{e['request']['name']}" for e in entries if "request" in e}
    if calls_held != calls_named:
        problems.append("request/response members are not exactly the custody chains'")
    if not result.rule("M4-CUS", problems):
        return None

    # M4-WLD
    problems, applied = [], [r for r in commits.values() if r["event"] == "WORLD_APPLIED"]
    intents = {r["step"]: r for r in records if r["event"] == "WORLD_INTENT_RECORDED"}
    named_states, named_transitions = set(), set()
    world = semantic.get("world")
    versioned = world is not None
    state_ref = f"{world['state_schema']['schema_id']}:{world['state_schema']['version']}" \
        if versioned else None
    admissibility = dict.fromkeys(WORLD_ADMISSIBILITY_VERDICTS, 0)
    progression = {"no_action_transitions": 0, "unexecuted_transitions": 0,
                   "exogenous_events": {}}
    replayed = {}  # the serialized inputs of a transition -> (member, its body)
    unseeded = {}  # the same, whatever the seed (a DETERMINISTIC contract, BVL T3-006)
    rng_counts = {"stochastic_transitions": 0, "draws": 0, "bits": 0}
    current = {}  # episode -> the identity of the state it is in (plan-8)
    for record in opened:
        held_initial = record.get("initial_state")
        if not versioned:
            if held_initial is not None:
                problems.append(f"EPISODE_OPENED #{record['sequence']} names an initial state; "
                                "the plan has no World contract")
            continue
        initial = semantic["initial_world_state"]
        expected_initial = world_state_identity(initial, state_ref)
        initial_path = held_initial.get("evidence", {}).get("path") \
            if isinstance(held_initial, dict) else None
        if not isinstance(held_initial, dict) or set(held_initial) != {"identity", "evidence"} \
                or held_initial["identity"] != expected_initial \
                or initial_path not in documents \
                or held_initial["evidence"] != _ref(initial_path, by_path) \
                or documents[initial_path] != _world_state_evidence(initial, state_ref):
            problems.append(f"EPISODE_OPENED #{record['sequence']} does not open on evidence "
                            f"of the plan's initial {state_ref} state")
            continue
        named_states.add(initial_path)
        current[record["episode"]] = expected_initial
    for record in sorted((r for r in records
                          if r["event"] in ("WORLD_INTENT_RECORDED", "ROUND_COMPLETED")
                          or (r["event"] == "WORLD_APPLIED" and r in applied)),
                         key=lambda r: r["sequence"]) if versioned else ():
        # the state chain: initial -> pre -> post -> next pre, closed by each round
        if record["event"] == "WORLD_APPLIED":
            current[record["episode"]] = record.get("post_state")
        elif record["event"] == "ROUND_COMPLETED":
            if record.get("post_state") != current.get(record["episode"]):
                problems.append(f"ROUND_COMPLETED #{record['sequence']} does not close on its "
                                "episode's current World state")
        else:
            payload = record.get("transition_intent", {}).get("payload", {})
            if payload.get("pre_state") != current.get(record["episode"]):
                problems.append(f"WORLD_INTENT_RECORDED #{record['sequence']} pre-state is not "
                                "the state its episode was in")
    # BVL T4-005: World(t) -> World(t+1), link by link, from the evidence bytes
    chain_problems, chain = state_chain(
        records, world_state_identity(semantic["initial_world_state"], state_ref), state_ref,
        documents)
    problems += chain_problems
    for record in applied:
        refs = record.get("evidence", {})
        transition_path = refs.get("transition", {}).get("path")
        state_path = refs.get("state", {}).get("path")
        if transition_path not in documents or state_path not in documents \
                or refs["transition"] != _ref(transition_path, by_path) \
                or refs["state"] != _ref(state_path, by_path):
            problems.append(f"WORLD_APPLIED #{record['sequence']} names no packaged evidence")
            continue
        named_transitions.add(transition_path)
        named_states.add(state_path)
        evidence = documents[transition_path]
        recomputed = identity("world_transition", {
            "decision": evidence["decision"], "world_plugin_identity": evidence["world"],
            "seed_identity": f"seed:{evidence['seed']}",
            "transition": evidence["transition"],
            **({"state_schema": evidence.get("state_schema"), "rng": evidence.get("rng")}
               if versioned else {})})
        intent = intents.get(record["step"], {}).get("transition_intent", {})
        payload = intent.get("payload") if isinstance(intent.get("payload"), dict) else {}
        body = evidence["transition"]
        extra = {"state_schema", "pre_state", "post_state", "rng"} if versioned else set()
        if evidence.get("schema") != WORLD_TRANSITION_EVIDENCE[versioned] \
                or set(evidence) != WORLD_TRANSITION_KEYS | extra \
                or payload.get("schema") != WORLD_INTENT[versioned] \
                or payload.get("state_schema") != state_ref \
                or ("state_schema" in payload) != versioned:
            problems.append(f"{transition_path} and its intent are not the documents of a "
                            + (f"plan World contract {state_ref}" if versioned
                               else "plan without a World contract"))
            continue
        # a contracted transition is a transition-2; without a contract the
        # World's own statement (transition-1 or -2) is kept and not read
        stated = isinstance(body, dict) and body.get("schema") == WORLD_TRANSITION_BODY[True]
        if not isinstance(body, dict) or (versioned and not stated) \
                or body.get("schema") not in WORLD_TRANSITION_BODY.values() \
                or set(body) != WORLD_TRANSITION_BODY_KEYS | (
                    WORLD_PROGRESSION_KEYS if stated else set()):
            problems.append(f"{transition_path} does not carry a "
                            f"{WORLD_TRANSITION_BODY[versioned]}")
            continue
        if payload.get("pre_state") != world_state_identity(body.get("pre_state"), state_ref):
            problems.append(f"{transition_path} pre-state is not the intended pre-state")
        if versioned:
            # BVL T3-002: the intent evidenced, before apply, the action this
            # transition is of
            opened_at = intents.get(record["step"], {}).get("sequence")
            if not isinstance(opened_at, int) or opened_at >= record["sequence"]:
                problems.append(f"WORLD_APPLIED #{record['sequence']} is preceded by no "
                                "durable World intent (BVL-WORLD-005)")
            if "action" not in payload \
                    or canonical(body.get("requested_action")) != canonical(payload["action"]):
                problems.append(f"{transition_path} is not a transition of the action its "
                                "intent handed to the World (BVL-WORLD-006)")
            if payload.get("world") != world["plugin"] or evidence["world"] != world["plugin"]:
                problems.append(f"{transition_path} is not a transition of the plan's World")
            if evidence["state_schema"] != state_ref \
                    or evidence["pre_state"] != payload.get("pre_state") \
                    or evidence["post_state"] != world_state_identity(body.get("post_state"),
                                                                      state_ref):
                problems.append(f"{transition_path} state identities are not its states "
                                f"under {state_ref}")
            for role in ("pre_state", "post_state"):
                problems += [f"{transition_path} {role} is not a {state_ref} state: {problem}"
                             for problem in _world_state_problems(world["state_schema"],
                                                                  body.get(role))]
            # BVL T3-003: requested, admissible and executed are three stated
            # actions under one verdict of the contract's vocabulary
            # BVL T3-004: the input, the execution and the exogenous events are
            # stated; a NO_ACTION input assessed no action
            hidden = _world_progression_problems(world, body)
            if not hidden and body["action_input"] != payload.get("action_input"):
                hidden = ["is of another input than its intent handed to the World "
                          "(BVL-WORLD-006)"]
            problems += [f"{transition_path} {problem}" for problem in hidden]
            idle = body.get("action_input") == "NO_ACTION"
            found = [] if idle else _world_admissibility_problems(world["action_schema"], body)
            problems += [f"{transition_path} {problem}" for problem in found]
            if not found and not idle:
                admissibility[body["admissibility_verdict"]] += 1
            # BVL T3-005: a transition is one function of its serialized inputs
            for role in ("pre_state", "post_state"):
                if _has_null(body.get(role)):
                    problems.append(f"{transition_path} {role} holds a null: it is not its "
                                    "own serialization read back (BVL-WORLD-009)")
            inputs = canonical({
                "world": world["plugin"], "state_schema": state_ref,
                "seed": payload.get("seed"), "action_input": payload.get("action_input"),
                "action": payload.get("action"), "pre_state": body.get("pre_state")})
            first = replayed.setdefault(inputs, (transition_path, canonical(body)))
            if first[1] != canonical(body):
                problems.append(f"{transition_path} and {first[0]} are transitions of the "
                                "same serialized pre-state, input and seed, and differ "
                                "(BVL-WORLD-009)")
            # BVL T3-006: the transition evidences the contract's RNG policy, and
            # a DETERMINISTIC one is the same whatever its seed
            drawn = _world_rng_problems(world["rng"], evidence.get("rng"))
            problems += [f"{transition_path} {problem}" for problem in drawn]
            if world["rng"]["policy"] == "DETERMINISTIC":
                inputs = canonical({
                    "world": world["plugin"], "state_schema": state_ref,
                    "action_input": payload.get("action_input"),
                    "action": payload.get("action"), "pre_state": body.get("pre_state")})
                first = unseeded.setdefault(inputs, (transition_path, canonical(body)))
                if first[1] != canonical(body):
                    problems.append(f"{transition_path} and {first[0]} are DETERMINISTIC "
                                    "transitions of the same serialized pre-state and "
                                    "input, and differ (BVL-WORLD-013)")
            elif not drawn and evidence["rng"]["draws"] > 0:
                rng_counts["stochastic_transitions"] += 1
                rng_counts["draws"] += evidence["rng"]["draws"]
                rng_counts["bits"] += evidence["rng"]["bits"]
            if not hidden:
                progression["no_action_transitions"] += idle
                progression["unexecuted_transitions"] += not body["executed"]
                for event in body["exogenous_events"]:
                    progression["exogenous_events"][event["event"]] = \
                        progression["exogenous_events"].get(event["event"], 0) + 1
        if evidence.get("identity") != recomputed or record["transition"] != recomputed:
            problems.append(f"{transition_path} identity does not recompute")
        if intent.get("identity") != identity("world_transition_intent",
                                              intent.get("payload")) \
                or evidence.get("intent") != intent.get("identity") \
                or record.get("transition_intent") != intent.get("identity"):
            problems.append(f"{transition_path} is not its recorded World intent's transition")
        state = documents[state_path].get("state")
        if documents[state_path] != _world_state_evidence(state, state_ref) \
                or record.get("post_state") != world_state_identity(state, state_ref) \
                or state != evidence["transition"].get("post_state"):
            problems.append(f"{state_path} is not the transition's recomputed post-state")
    # BVL T3-002: every intent of a plan-8 World contract is an intent-4 whose
    # action is the requested action of the decision it names - the
    # DECISION_RECORDED committed before it in its episode and round, and that
    # decision's own evidence member (its identity recomputed by M4-ART)
    for record in (r for r in records if r["event"] == "WORLD_INTENT_RECORDED"):
        where = f"WORLD_INTENT_RECORDED #{record['sequence']}"
        intent = record.get("transition_intent")
        payload = intent.get("payload") if isinstance(intent, dict) else None
        if not isinstance(payload, dict):
            problems.append(f"{where} carries no intent payload")
            continue
        if not versioned:
            if "action" in payload or payload.get("schema") != WORLD_INTENT[False]:
                problems.append(f"{where} is not a {WORLD_INTENT[False]}; the plan has no "
                                "World contract")
            continue
        if payload.get("schema") != WORLD_INTENT[True] or set(payload) != WORLD_INTENT_KEYS \
                or not isinstance(payload["action"], dict) \
                or payload["action_input"] not in WORLD_ACTION_INPUTS \
                or (payload["action_input"] == "NO_ACTION" and payload["action"]):
            problems.append(f"{where} is not a {WORLD_INTENT[True]} carrying the action "
                            "handed to its World and its input")
            continue
        if payload["decision"] != record.get("decision"):
            problems.append(f"{where} names another decision than its intent")
            continue
        decided = [r for r in records if r["event"] == "DECISION_RECORDED"
                   and isinstance(r.get("decision"), dict)
                   and r["decision"].get("identity") == payload["decision"]]
        if len(decided) != 1 or decided[0]["sequence"] >= record["sequence"] \
                or decided[0]["episode"] != record["episode"] \
                or decided[0]["round"] != record["round"]:
            problems.append(f"{where} intends a decision not committed once, before it, in "
                            "its episode and round")
            continue
        member = by_role["decision"].get(key(payload["decision"]))
        if canonical(decided[0]["decision"].get("requested_action")) \
                != canonical(payload["action"]) or member is None \
                or canonical(member.get("requested_action")) != canonical(payload["action"]):
            problems.append(f"{where} hands the World an action that is not its Decision "
                            "Artifact's requested action")
        # BVL T3-004: NO_ACTION is intended exactly for a NO_ACTION decision,
        # and only when the contract froze what it means to the World
        idle = payload["action_input"] == "NO_ACTION"
        if idle != (decided[0]["decision"].get("outcome") == "NO_ACTION") \
                or (member is not None and idle != (member.get("outcome") == "NO_ACTION")):
            problems.append(f"{where} input {payload['action_input']} is not its decision's "
                            "outcome")
        if idle and world["progression"]["no_action"] == "UNDECLARED":
            problems.append(f"{where} intends NO_ACTION, which the World contract does not "
                            "declare (BVL-WORLD-008)")
        # BVL T3-006: the seed is the plan's seed tree's, not the executor's choice
        if payload["seed"] != _derive_seed(semantic["seed"], "episode", record["episode"],
                                           "round", str(payload["round"]), "world",
                                           str(payload["node"])):
            problems.append(f"{where} seed is not the world seed the plan's seed tree "
                            "derives for its episode, round and transition (BVL-WORLD-013)")
    # BVL T3-007: under a World contract every transition is confirmed exactly
    # once, from custody-accepted input - read from journal-2 and custody-v2 alone
    custody_counts = {"intents": 0, "confirmed": 0, "unconfirmed": 0, "duplicate_confirmed": 0}
    if versioned:
        accepted_at = {r["call"]: r for r in records if r["event"] == "CUSTODY_ACCEPTED"}
        opened_intents, intended_steps = {}, set()
        for record in (r for r in records if r["event"] == "WORLD_INTENT_RECORDED"):
            where = f"WORLD_INTENT_RECORDED #{record['sequence']}"
            intent = record.get("transition_intent")
            payload = intent.get("payload") if isinstance(intent, dict) else None
            if not isinstance(payload, dict) or not isinstance(intent.get("identity"), dict):
                continue  # reported above: it carries no intent
            custody_counts["intents"] += 1
            digest = intent["identity"].get("digest")
            step = (record.get("episode"), record.get("step"))
            if digest in opened_intents or step in intended_steps:
                problems.append(f"{where} is a second World intent of its step "
                                "(BVL-WORLD-012)")
                continue
            opened_intents[digest] = record
            intended_steps.add(step)
            consumed = [entry for entry in entries
                        if identity("custody_entry", entry) == payload.get("source_custody")]
            source = accepted_at.get(consumed[0].get("call")) if len(consumed) == 1 else None
            if source is None or source["sequence"] >= record["sequence"] \
                    or source.get("episode") != record.get("episode") \
                    or source.get("run") != record.get("run"):
                problems.append(f"{where} consumes no single call custody-accepted before it "
                                "in its run and episode (BVL-WORLD-011)")
        confirmed_at, confirmed_transitions, confirmed_members = {}, set(), set()
        for record in records:
            where = f"{record['event']} #{record['sequence']}"
            if record["event"] == "WORLD_OUTCOME_UNKNOWN":
                problems.append(f"{where}: the outcome of an intended apply is unknown "
                                "(BVL-WORLD-011)")
            if record["event"] != "WORLD_APPLIED":
                continue
            bound = record.get("transition_intent")
            digest = bound.get("digest") if isinstance(bound, dict) else None
            opened = opened_intents.get(digest)
            if opened is None or opened["sequence"] >= record["sequence"]:
                problems.append(f"{where} confirms no World intent recorded before it "
                                "(BVL-WORLD-011)")
                continue
            transition = canonical(record.get("transition"))
            member = canonical(record.get("evidence"))
            if digest in confirmed_at or transition in confirmed_transitions \
                    or member in confirmed_members:
                custody_counts["duplicate_confirmed"] += 1
                problems.append(f"{where} confirms a transition another WORLD_APPLIED already "
                                "confirmed (BVL-WORLD-012)")
                continue
            confirmed_at[digest] = record["sequence"]
            confirmed_transitions.add(transition)
            confirmed_members.add(member)
            if any(record.get(name) != opened.get(name)
                   for name in ("run", "episode", "step", "round")):
                problems.append(f"{where} is not of the run, episode, step and round of the "
                                "intent it confirms (BVL-WORLD-011)")
        custody_counts["confirmed"] = len(confirmed_at)
        for digest, opened in opened_intents.items():
            if digest not in confirmed_at:
                custody_counts["unconfirmed"] += 1
                problems.append(f"WORLD_INTENT_RECORDED #{opened['sequence']} is confirmed by "
                                "no WORLD_APPLIED (BVL-WORLD-011)")
    for role, named in (("world_transition", named_transitions),
                        ("world_state", named_states)):
        listed = {p for p, m in by_path.items() if m["role"] == role}
        if listed != named:
            problems.append(f"{role} members are not exactly the ones WORLD_APPLIED "
                            "(and, under a World contract, EPISODE_OPENED) names")
    if len(named_transitions) != len(applied):
        problems.append("world_transition evidence is not one per WORLD_APPLIED")
    if not result.rule("M4-WLD", problems):
        return None

    # M4-LIN
    problems = []
    located = {(s["episode"], s["round"], s["node"]["id"]): s for s in steps.values()}
    intent_decision = {step_key: key(r["decision"]) for step_key, r in intents.items()}
    applied_by_identity = {key(document.get("identity")): document for _, document in
                           _of_role(by_path, documents, "world_transition")
                           if isinstance(document, dict)} if policies else {}
    for step_key, step in steps.items():
        node, kind = step["node"], step["node"]["kind"]
        source = node["depends_on"][0] if len(node["depends_on"]) == 1 else None

        def upstream(node_id, step=step):
            found = located.get((step["episode"], step["round"], node_id))
            return found["output"] if found is not None else None

        if kind == "proposal_parse" and step["output"] in by_role["proposal"]:
            link = key(by_role["proposal"][step["output"]]["call"])
            if source is None or link != upstream(source):
                problems.append(f"proposal of {node['id']!r} round {step['round']} is not "
                                "parsed from its IR actor-call dependency")
        elif kind == "decision" and step["output"] in by_role["decision"] \
                and decisions is not None:
            contract = decisions[node["id"]]
            first = next(iter(contract["candidates"].values()))
            problems.extend(
                f"decision of {node['id']!r} round {step['round']}: {problem}"
                for problem in _committed_decision_problems(
                    by_role["decision"][step["output"]], contract,
                    {parse: by_role["proposal"].get(upstream(parse))
                     for parse in contract["candidates"].values()},
                    contracts[first]["proposal_schema"]["fields"]))
        elif kind == "decision" and step["output"] in by_role["decision"]:
            link = key(by_role["decision"][step["output"]]["selected_proposal"])
            binding = node["config"].get("binding")
            if binding not in node["depends_on"] or link != upstream(binding):
                problems.append(f"decision of {node['id']!r} round {step['round']} does not "
                                "select its IR binding proposal")
        elif kind == "world_transition":
            if source is None or intent_decision.get(step_key) != upstream(source):
                problems.append(f"World transition of {node['id']!r} round {step['round']} "
                                "does not apply its IR decision dependency")
        elif kind == "memory_update" and step["output"] in by_role["memory"]:
            link = key(by_role["memory"][step["output"]]["source_transition"])
            if source is None or link != upstream(source):
                problems.append(f"memory of {node['id']!r} round {step['round']} is not "
                                "derived from its IR World dependency")
            if node["id"] in policies:
                problems.extend(
                    f"memory of {node['id']!r} round {step['round']} {problem}"
                    for problem in _memory_artifact_problems(
                        by_role["memory"][step["output"]], policies[node["id"]],
                        _as_identity(step["episode"]), _as_identity(step_key), step["round"],
                        commits[step_key].get("memory"),
                        applied_by_identity.get(link, {}).get("transition"),
                        key_of.get(step["episode"])))
    # BVL T4-004: the run's schedule orders every declared carry as declared
    scheduled = (schedule or {}).get("episodes", [])
    for node_id, policy in policies.items():
        carry = (policy.get("carry") or {}).get("episodes")
        if carry is not None and [name for name in scheduled if name in carry] != carry:
            problems.append(f"memory_update {node_id!r} declares the carry {carry}; the "
                            f"run's schedule {scheduled} does not order exactly these "
                            "episodes so (BVL-ROUND-011)")
    if not result.rule("M4-LIN", problems):
        return None

    # M4-L1C
    recorded = {}
    for step in steps.values():
        if step["node"]["id"] in policies and step["output"] in by_role["memory"]:
            recorded.setdefault((step["episode"], step["node"]["id"]), []).append(
                by_role["memory"][step["output"]])
    # BVL T4-004: the rounds whose committed transition stated a declared regime event
    regime_rounds = {}
    if policies and versioned:
        for record in records:
            if record["event"] != "WORLD_APPLIED":
                continue
            body = applied_by_identity.get(key(record.get("transition")), {}).get("transition")
            if regime_changes(world["progression"], body):
                regime_rounds.setdefault(record["episode"], set()).add(record["round"])
    names = list(key_of)  # the episodes in opened order

    def remembered(episode: str, node_id: str, round_index: int) -> list:
        if episode not in names or node_id not in policies:
            return []
        timeline = [{"key": key_of[name], "episode": _as_identity(name),
                     "artifacts": recorded.get((name, node_id), []),
                     "regime_rounds": sorted(regime_rounds.get(name, ()))}
                    for name in names[:names.index(episode) + 1]]
        return memory_held(policies[node_id], timeline, round_index)
    bindings, problems = _call_bindings(by_path, documents, records, commits, steps, semantic,
                                        _produced(commits, steps, by_role),
                                        _lineage(commits, steps, by_role), remembered)
    if not result.rule("M4-L1C", problems):
        return None

    # M4-RQR
    required = set(BASE_ROLES) | (L1_ROLES if bindings is not None else set())
    bound_analysis = semantic.get("analysis")
    if bound_analysis is not None:
        required.add(ANALYSIS_ROLE)
    # BVL T4-002: a timed round contract may end the episode before a node
    # kind ever ran; the package owes the evidence of the kinds it executed
    executed_kinds = {step["node"]["kind"] for step in steps.values()}
    timed = "timing" in protocol.get("round", {}).get("termination", {})
    for node in nodes.values():
        if not timed or node["kind"] in executed_kinds:
            required |= KIND_ROLES[node["kind"]]
    lacking = sorted(required - {m["role"] for m in by_path.values()})
    problems = [f"the package lacks IR-required roles {lacking}"] if lacking else []
    if bound_analysis is not None and bindings is None:
        problems.append("a bound analysis needs the L1 dataset units of call-bound runs")
    result.rule("M4-RQR", problems)

    # M4-ATT
    coverage, coverage_problems = _coverage(by_path, documents, gate_document, semantic,
                                            records, steps)
    kinds = Counter(step["node"]["kind"] for step in steps.values())
    derived = {
        "schema": ATTESTATION_SCHEMA, "package_class": "CONFORMANCE",
        "verdict": "CONFORMANT", "run": opened_run["run"],
        "experiment_id": semantic["experiment_id"], "plan": plan,
        "plan_evidence": _ref(plans[0][0], by_path), "protocol_ir": protocol["schema"],
        "binding": opened_run["binding"], "authorization": authorization,
        "required_roles": sorted(required),
        "episodes": sorted(episodes, key=lambda item: item["episode_key"]),
        "protocol_dag": dag, "experiment_schedule": schedule,
        "steps_by_kind": dict(sorted(kinds.items())),
        "custody_accepted_calls": len(entries),
        "world_transitions_applied": kinds.get("world_transition", 0),
        "checks": list(ATTESTED_CHECKS), "limitations": CONFORMANCE_LIMITATIONS,
    }
    gndcrw, gndcrw_problems = _gndcrw_results(by_path, documents, gate_document)
    if "round" in protocol:
        derived["checks"].append(ROUND_CHECK)
        derived["round_contract"] = {
            "max_rounds": protocol["round"]["max_rounds"],
            "termination_rule": protocol["round"]["termination"]["rule"],
            "termination": identity("termination_rule", protocol["round"]["termination"]),
            "rounds": protocol_rounds(protocol)}
        if "timing" in protocol["round"]["termination"]:
            derived["round_contract"]["timing"] = protocol["round"]["termination"]["timing"]
    if "round" in protocol and versioned:
        # BVL T4-005: the chain every round was verified on, head by head
        derived["checks"].append(STATE_CHAIN_CHECK)
        derived["state_chain"] = chain
    if policies:
        # BVL T4-003: which memory was declared, and how much of it is evidence
        derived["checks"].append(MEMORY_CHECK)
        derived["memory_lifecycle"] = {
            "nodes": policies,
            "sources": {source["source_id"]: source["producer"]
                        for source in (semantic.get("information") or {}).get("sources", [])
                        if source.get("source_kind") == "memory_artifact"},
            "artifacts": len(by_role["memory"])}
        if any("regime_change" in policy for policy in policies.values()):
            derived["memory_lifecycle"]["regime_change_rounds"] = {
                key_of[name]: sorted(rounds)
                for name, rounds in sorted(regime_rounds.items())}
            derived["memory_lifecycle"]["regime_resets"] = sorted(
                node_id for node_id, policy in policies.items()
                if policy.get("regime_change") == "reset")
    if versioned:
        derived["checks"] += [WORLD_STATE_CHECK, WORLD_ACTION_CHECK,
                              WORLD_ADMISSIBILITY_CHECK, WORLD_PROGRESSION_CHECK,
                              WORLD_REPLAY_CHECK, WORLD_RNG_CHECK, WORLD_CUSTODY_CHECK]
        derived["world_contract"] = {
            "plugin": world["plugin"], "state_schema": state_ref,
            "action_schema": f"{world['action_schema']['schema_id']}:"
                             f"{world['action_schema']['version']}",
            "no_action": world["progression"]["no_action"],
            "exogenous_events": world["progression"]["exogenous_events"],
            "rng_policy": world["rng"]["policy"]}
        if "regime" in world["progression"]:
            derived["world_contract"]["regime"] = world["progression"]["regime"]
        derived["world_rng"] = rng_counts
        derived["world_custody"] = custody_counts
        derived["world_admissibility"] = admissibility
        progression["exogenous_events"] = dict(sorted(progression["exogenous_events"].items()))
        derived["world_progression"] = progression
    if bindings is not None:
        derived["checks"].append(L1_CALL_CHECK)
    if bound_analysis is not None:
        derived["checks"].append(ANALYSIS_CHECK)
    if coverage is not None:
        derived["checks"].append(COVERAGE_CHECK)
        derived["execution_coverage"] = coverage
    if gndcrw is not None:
        derived["checks"].append(GNDCRW_CHECK)
        derived["gndcrw_results"] = gndcrw
    stored = _of_role(by_path, documents, "conformance_attestation")
    problems = [*coverage_problems, *gndcrw_problems]
    if len(stored) != 1:
        problems.append(f"{len(stored)} conformance attestations, not one")
    elif canonical(stored[0][1]) != canonical(derived):
        differing = sorted(name for name in set(derived) | set(stored[0][1])
                           if stored[0][1].get(name) != derived.get(name))
        problems.append(f"the attestation does not re-derive from the evidence: {differing}")
    if not result.rule("M4-ATT", problems):
        return None

    # M4-L1D
    datasets = _of_role(by_path, documents, "dataset_units")
    result.level = "PRE_L1" if bindings is None else "L1"
    if bindings is None:
        problems = ["dataset_units in a pre-L1 package"] if datasets else []
    elif len(datasets) != 1:
        problems = [f"{len(datasets)} dataset_units members, not one"]
    else:
        dataset = _dataset(records, commits, steps, by_role, bindings, coverage, gndcrw,
                           derived, _ref(stored[0][0], by_path))
        result.dataset = {"digest": sha(canonical(omit_absent(dataset))),
                          "counts": dataset["counts"]}
        problems = [] if canonical(omit_absent(dataset)) == held[datasets[0][0]] else [
            "the dataset units do not re-derive from the evidence"]
    if not result.rule("M4-L1D", problems):
        return derived

    # M4-ANA
    outputs = _of_role(by_path, documents, ANALYSIS_ROLE)
    if bound_analysis is None:
        problems = [f"{ANALYSIS_ROLE} in a package whose plan binds no analysis"] \
            if outputs else []
    elif bindings is None:
        problems = ["a bound analysis needs the L1 dataset units of call-bound runs"]
    elif len(outputs) != 1:
        problems = [f"{len(outputs)} {ANALYSIS_ROLE} members, not one"]
    else:
        analysis = omit_absent(_analysis(bound_analysis, omit_absent(dataset),
                                         _ref(datasets[0][0], by_path)))
        result.analysis = {"digest": sha(canonical(analysis)), "status": analysis["status"],
                           "admitted": len(analysis["admitted"]["decisions"]),
                           "excluded": len(analysis["excluded"]),
                           "metrics": {m["metric_id"]: [g["value"] for g in m["groups"]]
                                       for m in analysis["metrics"]}}
        problems = [] if canonical(analysis) == held[outputs[0][0]] else [
            "the bound analysis does not recompute over the admitted dataset units"]
    if not result.rule("M4-ANA", problems) or result.failed:
        return derived

    # M4-EXT
    counted, problems = _external_actors(records, steps, commits, semantic, by_path,
                                         documents, held, by_role["proposal"])
    if result.rule("M4-EXT", problems):
        result.external = counted
    return derived


# ------------------------------------------------------------ P09-ERF coverage (BVL T1-006)
COVERAGE_SCHEMA = "bvl-coverage-attestation-1"
COVERAGE_CHECK = "erf_coverage_recomputes_and_is_corroborated"
BUILTIN_COVERAGE = {
    "builtin.single-authority:1": ("decision_rule", [], {}),
    "builtin.majority:1": ("decision_rule", [], {}),
    "builtin.plurality:1": ("decision_rule", [], {}),
    "builtin.veto:1": ("decision_rule", [], {}),
    "builtin.redact-json-keys:1": ("visibility_transform", ["keys"], {}),
}
CORE_NODE_CONFIG = {"actor_call": {"actor"}, "proposal_parse": {"parser"},
                    "decision": {"binding"}, "world_transition": {"world"},
                    "memory_update": {"owner", "key", "scope", "retention", "transform",
                                      "carry", "regime_change"},
                    "termination": set()}
TARGET_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


class _ErfWalk:
    """The reader's own walk of one semantic plan (inventory bvl-erf-inventory-1)."""

    def __init__(self, contracts: dict, exclusions: dict) -> None:
        self.contracts, self.exclusions = contracts, exclusions
        self.erf, self.excluded, self.problems, self.claimed = {}, {}, [], set()

    def claim(self, target: str) -> bool:
        if not target or not set(target) <= TARGET_CHARS or target in self.claimed:
            self.problems.append(f"{target}: not one unique GNDCRW target")
            return False
        self.claimed.add(target)
        return True

    def field(self, target, value, owner="core", excludable=None) -> None:
        if not self.claim(target):
            return
        declared = self.exclusions.get(target)
        if declared is not None and declared == excludable:
            self.excluded[target] = {"target": target, "owner": owner, "class": declared}
            return
        if declared is not None:
            self.problems.append(f"{target}: exclusion {declared} is not permitted")
        self.erf[target] = {"target": target, "owner": owner, "value": value}

    def closed(self, prefix: str, document: dict, known: set) -> None:
        self.problems.extend(f"{prefix}.{k}: unmapped ERF" for k in sorted(set(document) - known))

    def leaves(self, prefix: str, value) -> None:
        if isinstance(value, dict) and value:
            for name in sorted(value):
                self.leaves(f"{prefix}.{name}", value[name])
        else:
            self.field(prefix, value)

    def plugin(self, prefix: str, plugin_id, plugin_type: str, config) -> None:
        contract = self.contracts.get(plugin_id)
        if contract is None or contract[0] != plugin_type:
            self.problems.append(f"{prefix}: {plugin_id!r} has no {plugin_type} coverage contract")
            return
        _, erf, excludable = contract
        for name in sorted(config):
            target = f"{prefix}.{name}"
            if name in erf:
                self.field(target, config[name], f"plugin:{plugin_id}")
            elif name in excludable:
                self.field(target, config[name], f"plugin:{plugin_id}", excludable[name])
            else:
                self.problems.append(f"{target}: not in {plugin_id}'s coverage contract")


def _erf_walk(plan: dict, contracts: dict, exclusions: dict) -> _ErfWalk:
    w = _ErfWalk(contracts, exclusions)
    w.closed("plan", plan, {"schema", "experiment_id", "protocol", "initial_world_state",
                            "initial_memory", "actors", "information", "proposals",
                            "decisions", "analysis", "seed", "world", "humans", "tools"})
    w.field("plan.schema", plan["schema"])
    w.field("plan.experiment_id", plan["experiment_id"])
    protocol = plan["protocol"]
    if "round" in protocol:
        contract = protocol["round"]
        w.closed("protocol", protocol, {"schema", "round", "nodes"})
        w.field("protocol.schema", protocol["schema"])
        w.closed("protocol.round", contract, {"schema", "max_rounds", "termination"})
        w.field("protocol.round.schema", contract["schema"])
        w.field("protocol.round.max_rounds", contract["max_rounds"])
        timed = "timing" in contract["termination"]
        w.closed("protocol.round.termination", contract["termination"],
                 {"rule", "timing", "config"} if timed else {"rule", "config"})
        w.field("protocol.round.termination.rule", contract["termination"]["rule"])
        if timed:
            w.field("protocol.round.termination.timing", contract["termination"]["timing"])
        w.leaves("protocol.round.termination.config", contract["termination"]["config"])
    else:
        w.closed("protocol", protocol, {"schema", "rounds", "nodes"})
        w.field("protocol.schema", protocol["schema"])
        w.field("protocol.rounds", protocol["rounds"])
    contracted = {section: {c["node_id"] for c in plan[section]["contracts"]}
                  for section in ("proposals", "decisions") if section in plan}
    for node in protocol["nodes"]:
        prefix = f"protocol.node.{node['id']}"
        w.closed(prefix, node, {"id", "kind", "depends_on", "config"})
        w.field(f"{prefix}.kind", node["kind"])
        w.field(f"{prefix}.depends_on", list(node["depends_on"]))
        for name in sorted(node["config"]):
            target = f"{prefix}.config.{name}"
            section = {("proposal_parse", "parser"): "proposals",
                       ("decision", "binding"): "decisions"}.get((node["kind"], name))
            if section and node["id"] in contracted.get(section, set()):
                if w.claim(target):
                    w.excluded[target] = {"target": target, "owner": "core",
                                          "class": "SUPERSEDED_BY_CONTRACT"}
            elif name in CORE_NODE_CONFIG.get(node["kind"], set()):
                w.field(target, node["config"][name])
            else:
                w.problems.append(f"{target}: unmapped ERF")
    w.leaves("world.initial", plan.get("initial_world_state", {}))
    w.leaves("memory.initial", plan.get("initial_memory", {}))
    external = {contract["actor_id"]: plugin_type
                for section, plugin_type in (("tools", "tool"), ("humans", "human_channel"))
                for contract in plan.get(section, {}).get("actors", [])}
    if "actors" in plan:
        w.closed("actors", plan["actors"], {"schema", "actors"})
        w.field("actors.schema", plan["actors"]["schema"])
        for actor in plan["actors"]["actors"]:
            prefix = f"actor.{actor['actor_id']}"
            w.closed(prefix, actor, {"actor_id", "role", "profile"})
            w.field(f"{prefix}.role", actor["role"])
            profile = actor["profile"]
            keys = {"schema", "provider", "model", "options", "seed_policy", "renderer"}
            w.closed(f"{prefix}.profile", profile, keys)
            for name in sorted(keys - {"options"}):
                w.field(f"{prefix}.profile.{name}", profile[name])
            # a human actor's provider is its human channel (BVL T5-001), a tool
            # actor's is its tool (BVL T5-003); every other provider is an adapter
            w.plugin(f"{prefix}.profile.options", profile["provider"],
                     external.get(actor["actor_id"], "adapter"), profile["options"])
            w.plugin(f"{prefix}.profile.renderer", profile["renderer"], "renderer", {})
    if "information" in plan:
        info = plan["information"]
        w.closed("information", info, {"schema", "sources", "grants", "transforms"})
        w.field("information.schema", info["schema"])
        for source in info["sources"]:
            prefix = f"information.source.{source['source_id']}"
            keys = (INFORMATION_ACTOR_OUTPUT_KEYS
                    if source.get("source_kind") in PRODUCED_SOURCE_KINDS
                    else {"source_id", "source_kind", "content_sha256", "size"})
            w.closed(prefix, source, keys)
            for name in sorted((keys - {"source_id"}) & set(source)):
                w.field(f"{prefix}.{name}", source[name])
        for grant in info["grants"]:
            w.closed(f"information.grant.{grant['actor_id']}", grant, {"actor_id", "sources"})
            w.field(f"information.grant.{grant['actor_id']}", list(grant["sources"]))
        for item in info.get("transforms", []):
            prefix = f"information.transform.{item['actor_id']}.{item['source_id']}"
            w.closed(prefix, item, {"actor_id", "source_id", "transform", "config"})
            w.field(f"{prefix}.transform", item["transform"])
            w.plugin(f"{prefix}.config", item["transform"], "visibility_transform",
                     item["config"])
    for section, owner_type, keys, fields in (
            ("proposals", "proposal_parser",
             {"schema", "node_id", "parser", "proposal_schema", "config", "on_invalid"},
             ("schema", "parser", "proposal_schema", "on_invalid")),
            ("decisions", "decision_rule",
             {"schema", "node_id", "rule", "authority", "candidates", "config",
              "on_unresolved"},
             ("schema", "rule", "authority", "candidates", "on_unresolved"))):
        if section not in plan:
            continue
        w.closed(section, plan[section], {"schema", "contracts"})
        w.field(f"{section}.schema", plan[section]["schema"])
        for contract in plan[section]["contracts"]:
            prefix = f"{section[:-1]}.{contract['node_id']}"
            w.closed(prefix, contract, keys)
            for name in fields:
                w.field(f"{prefix}.{name}", contract[name])
            plugin = contract["parser" if section == "proposals" else "rule"]
            w.plugin(f"{prefix}.config", plugin, owner_type, contract["config"])
    # the plan-6 analysis contract (BVL T1-009) is analysis-relevant, never an ERF
    if "analysis" in plan and w.claim("analysis"):
        w.excluded["analysis"] = {"target": "analysis", "owner": "core",
                                  "class": "ANALYSIS_CONTRACT"}
    # the plan-7 seed tree (BVL T1-012) decides every derived seed: an ERF
    if "seed" in plan:
        w.leaves("seed", plan["seed"])
    # the plan-8 World contract (BVL T3-001): which World, which state schema version
    if "world" in plan:
        w.leaves("world.contract", plan["world"])
    # the plan-9 human / plan-10 tool actor contracts (BVL T5-001 / T5-003): who answers
    # under what terms; which tool, effect, side effect and types
    for section, shapes in (("humans", {HUMAN_CONTRACT_SCHEMA: HUMAN_CONTRACT_KEYS}),
                            ("tools", TOOL_CONTRACT_SHAPES)):
        if section not in plan:
            continue
        w.closed(section, plan[section], {"schema", "actors"})
        w.field(f"{section}.schema", plan[section]["schema"])
        for contract in plan[section]["actors"]:
            prefix = f"{section[:-1]}.{contract['actor_id']}"
            keys = shapes.get(contract.get("schema"), TOOL_CONTRACT_KEYS)
            w.closed(prefix, contract, keys)
            for name in sorted((keys - {"actor_id"}) & set(contract)):
                w.leaves(f"{prefix}.{name}", contract[name])
    return w


def _catalog_digest(cells: dict) -> str:
    return _catalog(cells)["catalog_digest"]


def _catalog(cells: dict) -> dict:
    def kind(value) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "BOOLEAN"
        if isinstance(value, int):
            return "INTEGER"
        if isinstance(value, float):
            return "NUMBER"
        return "STRING" if isinstance(value, str) else "JSON"

    targets = {}
    for target in sorted({t for values in cells.values() for t in values}):
        kinds = {kind(values.get(target)) for values in cells.values()}
        value_kind = kinds.pop() if len(kinds) == 1 else "JSON"
        targets[target] = {"level": "SUBSTRUCTURE" if value_kind == "JSON" else "SURFACE",
                           "value_kind": value_kind, "availability": "SUPPORTED",
                           "equality": "JSON_STRUCTURAL"}
    catalog = {
        "catalog_version": "gndcrw-target-catalog/v0.1", "catalog_id": "bvl-plan-erf",
        "profile_id": "erf-l1", "provider_id": "boomvalley-lab", "targets": targets,
        "composition_targets": {
            "entity_count": {"value_kind": "INTEGER", "availability": "SUPPORTED",
                             "equality": "JSON_STRUCTURAL"},
            "entity_set": {"value_kind": "STRING_SET", "availability": "SUPPORTED",
                           "equality": "SET_EXACT"}}}
    catalog["catalog_digest"] = sha(canonical(catalog))
    return catalog


def _required_edges(design: dict) -> list[str]:
    factors = design["factors"]
    edges = []
    for factor, levels in factors.items():
        contexts = [[]]
        for other in (f for f in factors if f != factor):
            contexts = [[*c, (other, level)] for c in contexts for level in factors[other]]
        for context in contexts:
            suffix = "".join(f".{f}-{level}" for f, level in sorted(context))
            edges.extend(f"edge.{factor}.{low}-{high}{suffix}"
                         for low, high in zip(levels, levels[1:], strict=False))
    return sorted(edges)


def _corroborate(records: list, steps: dict, documents: dict, by_path: dict, values: dict,
                 excluded: list) -> list[str]:
    """BVL-COV-011: what ran is what was attested (profile, parser, decision)."""
    problems = []
    returned = {r["call"]: r for r in records if r["event"] == "CALL_RETURNED"}

    def config_of(prefix: str) -> tuple[dict, set]:
        attested = {t[len(prefix) + 1:]: v for t, v in values.items()
                    if t.startswith(f"{prefix}.")}
        dropped = {e["target"][len(prefix) + 1:] for e in excluded
                   if e["target"].startswith(f"{prefix}.")}
        return attested, dropped

    for record in records:
        if record["event"] != "CALL_INTENT_RECORDED":
            continue
        actor = steps.get(record["step"], {}).get("node", {}).get("config", {}).get("actor")
        request = documents.get(f"requests-v2/{record['request']['name']}", {})
        base = f"actor.{actor}.profile"
        options, dropped = config_of(f"{base}.options")
        model = values.get(f"{base}.model")
        reported = returned.get(record["call"], {}).get("response", {}).get(
            "model_identity", model)
        consumed = {k: v for k, v in request.get("options", {}).items() if k not in dropped}
        if actor is None or request.get("model_identity") != model or reported != model \
                or request.get("renderer_identity") != values.get(f"{base}.renderer") \
                or consumed != options:
            problems.append(f"BVL-COV-011: call {record['call']} is not the attested profile")
    for role, fields in (("proposal", ("parser", "on_invalid", "proposal_schema")),
                         ("decision", ("rule", "authority", "candidates", "on_unresolved"))):
        for _, evidence in _of_role(by_path, documents, role):
            contract = evidence.get("contract")
            if contract is None:  # pre-contract evidence binds no plan contract
                continue
            prefix = f"{role}.{contract['node_id']}"
            config, dropped = config_of(f"{prefix}.config")
            consumed = {k: v for k, v in contract.get("config", {}).items() if k not in dropped}
            if consumed != config or any(
                    contract.get(name) != values.get(f"{prefix}.{name}") for name in fields):
                problems.append(f"BVL-COV-011: {prefix} ran outside the attested ERFs")
    return problems


def _coverage(by_path: dict, documents: dict, gate: dict | None, semantic: dict,
              records: list, steps: dict) -> tuple[dict | None, list[str]]:
    members = _of_role(by_path, documents, "coverage")
    if not members:
        return None, []
    if len(members) != 1 or gate is None:
        return None, [f"{len(members)} coverage members, not one"]
    path, document = members[0]
    problems = []
    if identity("coverage_attestation", document) != gate.get("coverage"):
        problems.append("the coverage member is not the gate-2 decision's coverage")
    if document.get("schema") != COVERAGE_SCHEMA:
        return None, [*problems, "the coverage member is not a coverage attestation"]
    if document.get("execution_coverage") != "COMPLETE" or document.get("findings"):
        problems.append("the attested execution coverage is not COMPLETE")
    plan = identity("plan", semantic)
    cell = next((c for c in document["cells"] if c.get("plan") == plan), None)
    if cell is None:
        return None, [*problems, "the coverage attestation does not attest this plan"]
    contracts = dict(BUILTIN_COVERAGE)
    for contract in document["plugin_contracts"]:
        contracts[contract["plugin_id"]] = (contract["plugin_type"], contract["erf"],
                                            contract["excludable"])
    walk = _erf_walk(semantic, contracts, document["design"]["exclusions"])
    problems.extend(f"coverage: {problem}" for problem in walk.problems)
    erf = [walk.erf[t] for t in sorted(walk.erf)]
    excluded = [walk.excluded[t] for t in sorted(walk.excluded)]
    if canonical(cell["erf"]) != canonical(erf) or canonical(cell["excluded"]) != canonical(
            excluded):
        problems.append("the attested ERF cell does not re-walk from the plan")
    values = {item["target"]: item.get("value") for item in erf}
    if cell["surface_digest"] != sha(canonical(values)):
        problems.append("the attested surface digest does not recompute")
    cells = {c["cell"]: {e["target"]: e.get("value") for e in c["erf"]}
             for c in document["cells"]}
    if document["catalog"]["catalog_ref"]["catalog_digest"] != _catalog_digest(cells):
        problems.append("the attested catalog digest does not recompute")
    if [e["edge_id"] for e in document["comparison_set"]["edges"]] != _required_edges(
            document["design"]):
        problems.append("the attested comparison set is not the design's required set")
    problems.extend(_corroborate(records, steps, documents, by_path, values, excluded))
    summary = {"attestation": identity("coverage_attestation", document),
               "evidence": _ref(path, by_path), "cell": cell["cell"], "erf": len(erf),
               "excluded": len(excluded), "verdict": document.get("execution_coverage")}
    return summary, problems

# ------------------------------------------------------------ GNDCRW comparison set (BVL T1-007)
GNDCRW_CHECK = "gndcrw_comparison_set_bound_and_run"
GNDCRW_SET_SCHEMA = "bvl-gndcrw-result-set-1"
GNDCRW_STRICT = ("gndcrw-result/v0.1", "GNDCRW-STRICT-0.1", "CONTROL")


def _gndcrw_digest(document) -> str:
    """GNDCRW content digest: sorted compact JSON that keeps nulls."""
    return sha(json.dumps(document, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8"))


def _edge_subjects(coverage: dict) -> dict:
    """Every required edge's GNDCRW ``subject``, rebuilt from the attestation alone."""
    design = coverage["design"]
    cells = {c["cell"]: c for c in coverage["cells"]}
    values = {key: {e["target"]: e.get("value") for e in c["erf"]} for key, c in cells.items()}
    catalog = _catalog(values)
    ref = {name: catalog[name] for name in
           ("provider_id", "catalog_id", "catalog_version", "profile_id", "catalog_digest")}

    def surface(key: str, role: str) -> dict:
        return {
            "surface_version": "gndcrw-surface/v0.1", "surface_id": key, "role": role,
            "provider": {"provider_id": "boomvalley-lab",
                         "provider_version": "bvl-erf-inventory-1",
                         "adapter_id": "bvl-plan-surface", "adapter_version": "1"},
            "assembly": {"mode": "DIRECT",
                         "assembly_entrypoint": "boomvalley_lab.kernel.coverage.plan_surface",
                         "equivalence": None},
            "targets": {t: {"level": d["level"], "observability": "OBSERVED",
                            "value": values[key].get(t)} for t, d in catalog["targets"].items()},
            "composition": {"entity_kind": "actor", "entity_count": len(cells[key]["actors"]),
                            "entity_ids": sorted(cells[key]["actors"]),
                            "identity_namespace": "bvl.actor/v1"},
            "provenance": {"input_digests": {
                "boomvalley-lab-plan-identity": cells[key]["plan"]["digest"]}},
            "premises": []}

    def rules(prefix: str, operation: str, targets: list) -> list:
        return [{"rule_id": f"{prefix}-{i:04d}", "target": {"kind": "TARGET", "id": t},
                 "operation": operation, "scope": {"kind": "WHOLE_TARGET"}, "premise_refs": []}
                for i, t in enumerate(targets, 1)]

    def matches(pattern: str, target: str) -> bool:
        return target.startswith(pattern[:-1]) if pattern.endswith(".*") else target == pattern

    subjects = {}
    for edge in coverage["comparison_set"]["edges"]:
        changes = sorted(t for t in catalog["targets"]
                         if any(matches(p, t) for p in design["contrasts"][edge["factor"]]))
        body = {"catalog_ref": ref, "comparison": {"required_mode": "CONTROL"},
                "expected_changes": rules("CHG", "MUST_DIFFER", changes),
                "invariants": rules("INV", "MUST_EQUAL",
                                    [t for t in catalog["targets"] if t not in changes]),
                "declared_consequences": [], "premises": [], "context": []}
        intent = sha(canonical(body))
        declaration = {"declaration_version": "gndcrw-declaration/v0.1",
                       "declaration_id": edge["edge_id"],
                       "intent": {"intent_id": edge["edge_id"], "intent_digest": intent}, **body}
        pair = {"pair_version": "gndcrw-pair/v0.1", "comparison_mode": "CONTROL",
                "base_surface_id": edge["base_cell"],
                "candidate_surface_id": edge["candidate_cell"],
                "entity_comparability": {
                    "status": "ESTABLISHED", "method": "STABLE_DOMAIN_ID",
                    "authority": {"kind": "PROVIDER", "id": "boomvalley-lab"},
                    "mapping": None, "limitations": []}}
        subjects[edge["edge_id"]] = {
            "declaration": {"id": edge["edge_id"], "intent_digest": intent,
                            "content_digest": _gndcrw_digest(declaration)},
            "catalog": {"id": "bvl-plan-erf", "profile_id": "erf-l1",
                        "catalog_digest": catalog["catalog_digest"]},
            "base_surface": {"id": edge["base_cell"], "content_digest": _gndcrw_digest(
                surface(edge["base_cell"], "BASE"))},
            "candidate_surface": {"id": edge["candidate_cell"], "content_digest": _gndcrw_digest(
                surface(edge["candidate_cell"], "CANDIDATE"))},
            "pair": {"content_digest": _gndcrw_digest(pair)}}
    return subjects


def _gndcrw_results(by_path: dict, documents: dict,
                    gate: dict | None) -> tuple[dict | None, list[str]]:
    members = _of_role(by_path, documents, "gndcrw_results")
    if not members:
        return None, []
    coverage = _of_role(by_path, documents, "coverage")
    if len(members) != 1 or len(coverage) != 1 or gate is None:
        return None, [f"{len(members)} GNDCRW result sets / {len(coverage)} coverage members, "
                      "not one each"]
    path, document = members[0]
    problems = []
    if identity("gndcrw_result_set", document) != gate.get("gndcrw_results"):
        problems.append("the GNDCRW result set is not the gate-2 decision's")
    if not isinstance(document, dict) or document.get("schema") != GNDCRW_SET_SCHEMA:
        return None, [*problems, "the gndcrw_results member is not a GNDCRW result set"]
    attestation = coverage[0][1]
    if document.get("coverage") != identity("coverage_attestation", attestation):
        problems.append("the GNDCRW result set binds another coverage attestation")
    try:
        subjects = _edge_subjects(attestation)
    except (KeyError, TypeError, AttributeError) as error:
        return None, [*problems, f"the attested comparison set does not rebuild: {error}"]
    required = _required_edges(attestation["design"])
    if sorted(subjects) != required or document.get("required_edges") != required:
        problems.append("the GNDCRW result set is not the design's required comparison set")
    results = {}
    for entry in document.get("results", []):
        if entry.get("edge_id") in results:
            problems.append(f"{entry.get('edge_id')}: more than one GNDCRW result")
        results[entry.get("edge_id")] = entry.get("result")
    for edge in required:
        result = results.pop(edge, None)
        if not isinstance(result, dict):
            problems.append(f"BVL-COV-009: {edge} has no GNDCRW result")
        elif (result.get("result_version"), result.get("policy_id"),
              result.get("comparison_mode")) != GNDCRW_STRICT:
            problems.append(f"BVL-GATE-004: {edge} is not a strict CONTROL GNDCRW result")
        elif result.get("subject") != subjects.get(edge):
            problems.append(f"BVL-GATE-002: {edge} result does not bind the edge's subjects")
        elif result.get("outcome") != "RUN":
            problems.append(f"BVL-GATE-003: {edge} outcome is {result.get('outcome')!r}")
    problems.extend(f"BVL-GATE-002: {edge} is not a required comparison" for edge in results)
    summary = {"result_set": identity("gndcrw_result_set", document),
               "evidence": _ref(path, by_path), "edges": len(required), "outcome": "RUN"}
    return summary, problems


# ------------------------------------------------------------ L1 roles / dataset (BVL T1-008)
CALL_BINDING_SCHEMA = "boomvalley-lab-call-binding-1"
CALL_BINDING_KEYS = {"schema", "episode", "step", "round", "node", "call", "request",
                     "provider", "actor", "role", "profile", "seed", "access"}
TRACE_SCHEMA = "bvl-request-pipeline-trace-1"
TRACE_KEYS = {"schema", "actor_id", "considered", "granted", "denied", "transforms",
              "observation", "renderer", "rendering_sha256", "codec", "corroboration_grade",
              "request_identity"}
GRADES = {"EXACT_TRANSPORT", "CLIENT_CANONICAL", "PROVIDER_BOUND_INDIRECT", "UNVERIFIABLE"}
L1_ROLES = {"call_binding", "dataset_units"}
L1_CALL_CHECK = "l1_call_bindings_recompute"
DATASET_SCHEMA = "boomvalley-lab-l1-dataset-1"
DATASET_LIMITATIONS = ["OBSERVATION_DIGESTS_ATTESTED_NOT_RECOMPUTED"]
ELIGIBILITY = ("lineage_bound", "decided", "coverage_complete", "comparisons_run")


def _is_seed_tree(document) -> bool:
    return isinstance(document, dict) and set(document) == {"schema", "root_seed"} \
        and document["schema"] == SEED_TREE_SCHEMA \
        and isinstance(document["root_seed"], int) and not isinstance(document["root_seed"], bool)


def _derive_seed(tree: dict, *path: str) -> int:
    """K0 seed derivation, recomputed: 63 bits of the seed path's document digest."""
    document = {"schema": tree["schema"], "root_seed": tree["root_seed"], "path": list(path)}
    return int(hashlib.sha256(canonical(document)).hexdigest()[:16], 16) & ((1 << 63) - 1)


def _call_seed(tree: dict, profile: dict, actor_identity: dict, episode: str, round_index: int,
               node_id: str) -> int:
    """The seed a call at this position derives under the profile's seed policy."""
    if profile["seed_policy"] == SEED_POLICY_PER_ACTOR:
        return _derive_seed(tree, "episode", episode, "round", str(round_index), "step", node_id,
                            "actor", key(actor_identity), "attempt", "1")
    return _derive_seed(tree, "episode", episode, "round", str(round_index), "actor-shared",
                        profile["seed_policy"], "attempt", "1")


def _as_identity(text: str) -> dict:
    kind, digest = text.split(":", 1)
    return {"kind": kind, "digest": digest}


def _produced(commits: dict, steps: dict, by_role: dict) -> dict:
    """(episode, round, node) -> SHA-256 of the output an actor_output source carries."""
    found = {}
    for step_key, record in commits.items():
        step = steps[step_key]
        where = (step["episode"], step["round"], step["node"]["id"])
        if record["event"] == "CUSTODY_ACCEPTED" and isinstance(record.get("artifact"), dict):
            algorithm, _, digest = str(record["artifact"].get("content")).partition(":")
            if algorithm == "sha256":
                found[where] = digest
        elif record["event"] == "PROPOSAL_PARSED":
            document = by_role["proposal"].get(step["output"])
            if isinstance(document, dict) and isinstance(document.get("value"), dict):
                found[where] = hashlib.sha256(canonical(document["value"])).hexdigest()
    return found


def _lineage(commits: dict, steps: dict, by_role: dict) -> dict:
    """(episode, round, node) -> the committed identity an actor_output carries (T2-003)."""
    digests = _produced(commits, steps, by_role)
    found = {}
    for step_key, record in commits.items():
        step = steps[step_key]
        where = (step["episode"], step["round"], step["node"]["id"])
        if where not in digests:
            continue
        if record["event"] == "CUSTODY_ACCEPTED":
            kind, ident = "actor_call", _as_identity(record["call"])
        else:
            kind, ident = "proposal_parse", record["proposal"]["identity"]
        found[where] = {"producer_kind": kind, "identity": ident,
                        "content_sha256": digests[where]}
    return found


def _upstream_problems(request: dict, granted: list, sources: dict, lineage: dict) -> list[str]:
    outputs = sorted(s for s in granted if sources[s]["source_kind"] == "actor_output")
    if not outputs:
        return (["request-2 binds upstream lineage but observes no actor_output source"]
                if "upstream" in request else [])
    expected = []
    for source in outputs:
        committed = lineage.get(source)
        if committed is None:
            return [f"actor_output {source!r} has no committed producer identity in the round"]
        expected.append({"source_id": source, "producer": sources[source]["producer"],
                         **committed})
    if request.get("upstream") != expected:
        return ["request-2 upstream is not the exact committed upstream proposal / call "
                "identity"]
    return []


def _call_bindings(by_path: dict, documents: dict, records: list, commits: dict, steps: dict,
                   semantic: dict, produced: dict | None = None,
                   lineage: dict | None = None,
                   remembered=None) -> tuple[dict | None, list[str]]:
    """M4-L1C: the run's call bindings, each recomputed; None for a pre-L1 run."""
    intents = {r["call"]: r for r in records if r["event"] == "CALL_INTENT_RECORDED"}
    accepted = {r["call"]: k for k, r in commits.items() if r["event"] == "CUSTODY_ACCEPTED"}
    named = {call: intents.get(call, {}).get("call_binding") for call in accepted}
    stored = {path for path, member in by_path.items() if member["role"] == "call_binding"}
    if all(value is None for value in named.values()):
        return None, (["call_binding members in a run whose call intents name none"]
                      if stored else [])
    if any(value is None for value in named.values()):
        return None, ["the run mixes L1-bound and unbound accepted calls"]
    if "actors" not in semantic:
        return None, ["L1 call bindings need a plan with P04 actors"]
    actors = {item["actor_id"]: item for item in semantic["actors"]["actors"]}
    problems, bound = [], {}
    for call, reference in sorted(named.items()):
        path = reference.get("path") if isinstance(reference, dict) else None
        if path not in documents or by_path[path]["role"] != "call_binding" \
                or reference != _ref(path, by_path):
            problems.append(f"{call}: the call intent names no packaged call binding")
            continue
        intent, step_key = intents[call], accepted[call]
        request = documents.get(f"requests-v2/{intent['request']['name']}", {})
        views = {source["source_id"]: memory_view(
            source["source_id"], source["producer"],
            [] if remembered is None else remembered(
                steps[step_key]["episode"], source["producer"], steps[step_key]["round"]),
            steps[step_key]["round"], _as_identity(steps[step_key]["episode"]))
            for source in (semantic.get("information") or {}).get("sources", [])
            if source.get("source_kind") == "memory_artifact"}
        problems.extend(f"{call}: {problem}" for problem in _binding_problems(
            documents[path], call, step_key, steps[step_key],
            actors.get(steps[step_key]["node"]["config"].get("actor")),
            intent["request"]["identity"], request, semantic.get("information"),
            semantic.get("seed"),
            {**{source["source_id"]: (produced or {}).get(
                (steps[step_key]["episode"], steps[step_key]["round"], source["producer"]))
                for source in (semantic.get("information") or {}).get("sources", [])
                if source.get("source_kind") == "actor_output"},
             **{source: view[0] for source, view in views.items()}},
            {source["source_id"]: (lineage or {}).get(
                (steps[step_key]["episode"], steps[step_key]["round"], source["producer"]))
             for source in (semantic.get("information") or {}).get("sources", [])
             if source.get("source_kind") == "actor_output"},
            {source: view[1] for source, view in views.items()}))
        bound[call] = (path, documents[path])
    if {path for path, _ in bound.values()} != stored:
        problems.append("call_binding members are not exactly the ones the call intents name")
    return bound, problems


def _binding_problems(document, call: str, step_key: str, step: dict, actor, request_id,
                      request: dict, information, seed_tree=None,
                      produced: dict | None = None, lineage: dict | None = None,
                      memory: dict | None = None) -> list[str]:
    if not isinstance(document, dict) or set(document) != CALL_BINDING_KEYS \
            or document["schema"] != CALL_BINDING_SCHEMA:
        return ["the call binding is not a closed boomvalley-lab-call-binding-1"]
    if actor is None:
        return ["the call's IR node names no plan actor"]
    profile, problems = actor["profile"], []
    episode, step_id = _as_identity(step["episode"]), _as_identity(step_key)
    if (document["episode"], document["step"], document["round"], document["node"]) != (
            episode, step_id, step["round"], step["node"]["id"]):
        problems.append("the call binding names another step")
    if key(document["call"]) != call or document["request"] != request_id:
        problems.append("the call binding names another call or request-2")
    recomputed = identity("call", {"episode": episode, "step": step_id, "round": step["round"],
                                   "request": request_id, "adapter": profile["provider"]})
    if key(recomputed) != call or document["provider"] != profile["provider"]:
        problems.append("CallIdentity does not recompute from the plan actor's provider")
    role = identity("role", {"role_id": actor["role"]})
    actor_identity = identity("actor", {"actor_id": actor["actor_id"], "role": role})
    if document["role"] != {"role_id": actor["role"], "identity": role} \
            or document["actor"] != {"actor_id": actor["actor_id"], "identity": actor_identity} \
            or document["profile"] != identity("execution_profile", profile):
        problems.append("actor / role / profile identities are not the plan actor's")
    if request.get("model_identity") != profile["model"] \
            or request.get("renderer_identity") != profile["renderer"] \
            or request.get("options") != profile["options"] \
            or request.get("resolved_seed") != document["seed"]:
        problems.append("request-2 is not the bound profile's model / renderer / options / seed")
    if seed_tree is not None and document["seed"] != _call_seed(
            seed_tree, profile, actor_identity, step["episode"], step["round"],
            step["node"]["id"]):
        problems.append("the call binding seed does not re-derive from the plan's seed tree")
    trace = document["access"]
    if not isinstance(trace, dict) or set(trace) != TRACE_KEYS or trace["schema"] != TRACE_SCHEMA:
        return [*problems, "the access trace is not a closed pipeline trace"]
    sources, granted, transforms = {}, [], {}
    if information is not None:
        sources = {item["source_id"]: item for item in information["sources"]}
        granted = next(item["sources"] for item in information["grants"]
                       if item["actor_id"] == actor["actor_id"])
        transforms = {item["source_id"]: {"transform": item["transform"],
                                          "config": item["config"]}
                      for item in information.get("transforms", [])
                      if item["actor_id"] == actor["actor_id"]}
    if trace["actor_id"] != actor["actor_id"] or trace["renderer"] != profile["renderer"] \
            or trace["request_identity"] != f"request:{request_id['digest']}":
        problems.append("the access trace is not this call's actor / request / renderer")
    if trace["considered"] != sorted(sources) or trace["granted"] != granted \
            or trace["denied"] != sorted(set(sources) - set(granted)) \
            or trace["transforms"] != transforms:
        problems.append("the access trace is not the plan's default-deny access for the actor")
    observation = trace["observation"]
    if not isinstance(observation, dict) or sorted(observation) != granted:
        problems.append("the access trace observes other than exactly the granted sources")
    else:
        problems.extend(f"the observation of {source!r} is not its planned content"
                        for source in granted if source not in transforms
                        and observation[source] != (
                            (produced or {}).get(source)
                            if sources[source]["source_kind"] in PRODUCED_SOURCE_KINDS
                            else sources[source]["content_sha256"]))
    # BVL T4-003: request-2 names the exact Memory Artifacts it observed
    observed = sorted(source for source in granted if source in (memory or {}))
    if not observed:
        if "memory" in request:
            problems.append("request-2 binds memory but observes no memory_artifact source")
    elif request.get("memory") != [memory[source] for source in observed]:
        problems.append("request-2 memory is not the exact committed Memory Artifacts valid "
                        "in its round")
    problems.extend(_upstream_problems(request, granted, sources,
                                       {k: v for k, v in (lineage or {}).items()
                                        if v is not None}))
    if trace["codec"] != request.get("codec_identity") \
            or trace["corroboration_grade"] != request.get("corroboration_grade") \
            or trace["corroboration_grade"] not in GRADES \
            or not _is_sha256_hex(trace["rendering_sha256"]):
        problems.append("the access trace codec / grade / rendering digest is not request-2's")
    return problems


def _dataset(records: list, commits: dict, steps: dict, by_role: dict, bindings: dict,
             coverage, gndcrw, attestation: dict, attestation_ref: dict) -> dict:
    """M4-L1D: the reader's own reconstruction of the four dataset unit tables."""
    keys = {r["episode"]: r["episode_key"] for r in records if r["event"] == "EPISODE_OPENED"}
    returned = {r["call"]: r for r in records if r["event"] == "CALL_RETURNED"}
    proposals_by_id = by_role["proposal"]
    calls, proposals, decisions = [], [], []
    for step_key, record in commits.items():
        step = steps[step_key]
        where = {"episode_key": keys[step["episode"]], "round": step["round"],
                 "node": step["node"]["id"]}
        if record["event"] == "CUSTODY_ACCEPTED":
            path, binding = bindings[record["call"]]
            trace = binding["access"]
            calls.append({
                "unit": binding["call"], **where, "actor_id": binding["actor"]["actor_id"],
                "actor": binding["actor"]["identity"], "role_id": binding["role"]["role_id"],
                "role": binding["role"]["identity"], "profile": binding["profile"],
                "provider": binding["provider"],
                "model": returned[record["call"]]["response"]["model_identity"],
                "seed": binding["seed"], "request": binding["request"],
                "response": record["artifact"], "custody": record["custody"],
                "binding": _ref_of(path, binding),
                "access": {name: trace[name] for name in
                           ("granted", "denied", "transforms", "observation")}})
        elif record["event"] == "PROPOSAL_PARSED":
            document = proposals_by_id[key(record["proposal"]["identity"])]
            proposals.append({
                "unit": document["identity"], **where, "call": document["call"],
                "actor_id": bindings[key(document["call"])][1]["actor"]["actor_id"],
                "parser": document["parser"], "verdict": document.get("verdict", "VALID"),
                "value": document["value"], "reason": document.get("reason")})
        elif record["event"] == "DECISION_RECORDED":
            document = by_role["decision"][key(record["decision"]["identity"])]
            selected = document.get("selected_proposal")
            two = document.get("schema") == DECISION_EVIDENCE_2
            candidates = [c["proposal"] for c in document["candidates"]] if two else [selected]
            decisions.append({
                "unit": document["identity"], **where, "rule": document["rule"],
                "outcome": document["outcome"] if two else "SELECTED",
                "selected_proposal": selected,
                "supporting_proposals": document["supporting_proposals"] if two else [selected],
                "candidates": candidates,
                "requested_action": document.get("requested_action")})
    covered = coverage["verdict"] if coverage is not None else "NOT_ATTESTED"
    compared = gndcrw["outcome"] if gndcrw is not None else "NOT_BOUND"
    eligibility = []
    for decision in decisions:
        criteria = {
            "lineage_bound": all(
                key(c) in proposals_by_id and key(proposals_by_id[key(c)]["call"]) in bindings
                for c in decision["candidates"]),
            "decided": decision["outcome"] != "NO_ACTION",
            "coverage_complete": covered == "COMPLETE",
            "comparisons_run": compared == "RUN"}
        eligibility.append({
            "unit": decision["unit"], "episode_key": decision["episode_key"],
            "round": decision["round"], "node": decision["node"], "criteria": criteria,
            "eligible": all(criteria.values()),
            "reasons": [name for name in ELIGIBILITY if not criteria[name]]})

    def order(row):
        return (row["episode_key"], row["round"], row["node"])

    return {
        "schema": DATASET_SCHEMA, "run": attestation["run"],
        "experiment_id": attestation["experiment_id"], "plan": attestation["plan"],
        "authorization": attestation["authorization"], "attestation": attestation_ref,
        "conditions": {"coverage": covered, "comparisons": compared,
                       "cell": coverage["cell"] if coverage is not None else None},
        "limitations": DATASET_LIMITATIONS,
        "calls": sorted(calls, key=order), "proposals": sorted(proposals, key=order),
        "decisions": sorted(decisions, key=order),
        "eligibility": sorted(eligibility, key=order),
        "counts": {"calls": len(calls), "proposals": len(proposals),
                   "decisions": len(decisions),
                   "eligible": sum(1 for row in eligibility if row["eligible"])}}


# ------------------------------------------------------------ bound analysis (BVL T1-009)
ANALYSIS_ROLE = "analysis_output"
ANALYSIS_CHECK = "bound_analysis_recomputes_over_admitted_units"
ANALYSIS_CONTRACT_SCHEMA = "bvl-analysis-contract-1"
ANALYSIS_OUTPUT_SCHEMA = "boomvalley-lab-analysis-output-1"
ANALYSIS_LIMITATIONS = ["CLOSED_KERNEL_METRICS_ONLY", "SINGLE_RUN_POPULATION"]
METRIC_PARAMETERS = {"unit_count": {"table"}, "action_mean": {"field"},
                     "action_share": {"field", "equals"}, "proposal_agreement": set()}
METRIC_TABLES = ("calls", "decisions", "proposals")
METRIC_GROUPS = ("episode_key", "node", "round")


def _analysis_contract_problems(contract) -> list[str]:
    """plan-6 analysis: one closed contract of known, well-formed metrics."""
    if not isinstance(contract, dict) or set(contract) != {"schema", "analysis_id", "metrics"} \
            or contract["schema"] != ANALYSIS_CONTRACT_SCHEMA:
        return ["the plan analysis is not a closed bvl-analysis-contract-1"]
    metrics = contract["metrics"]
    if not isinstance(contract["analysis_id"], str) or not contract["analysis_id"] \
            or not isinstance(metrics, list) or not metrics:
        return ["the plan analysis names no analysis_id or no metrics"]
    problems = []
    for metric in metrics:
        kind = metric.get("kind") if isinstance(metric, dict) else None
        if kind not in METRIC_PARAMETERS:
            problems.append(f"analysis metric kind {kind!r} is unknown")
            continue
        needed = {"metric_id", "kind"} | METRIC_PARAMETERS[kind]
        if not needed <= set(metric) <= needed | {"by"} \
                or not isinstance(metric["metric_id"], str) or not metric["metric_id"] \
                or metric.get("by", "node") not in METRIC_GROUPS \
                or metric.get("table", "calls") not in METRIC_TABLES \
                or not isinstance(metric.get("field", "x"), str) or metric.get("field") == "" \
                or isinstance(metric.get("equals"), (float, dict, list)):
            problems.append(f"analysis metric {metric.get('metric_id')!r} is malformed")
    ids = [m.get("metric_id") for m in metrics if isinstance(m, dict)]
    if not problems and ids != sorted(set(ids)):
        problems.append("analysis metric ids are not unique and sorted")
    return problems


def _fraction(numerator, denominator: int) -> str:
    if denominator == 0:
        return "UNDEFINED"
    value = Fraction(numerator) / denominator
    return f"{value.numerator}/{value.denominator}"


def _analysis(contract: dict, dataset: dict, dataset_ref: dict) -> dict:
    """M4-ANA: the reader's own official analysis over the admitted units only."""
    eligible = {key(row["unit"]) for row in dataset["eligibility"] if row["eligible"] is True}
    decisions = [row for row in dataset["decisions"] if key(row["unit"]) in eligible]
    wanted = {key(c) for row in decisions for c in row["candidates"]}
    proposals = [row for row in dataset["proposals"] if key(row["unit"]) in wanted]
    called = {key(row["call"]) for row in proposals}
    calls = [row for row in dataset["calls"] if key(row["unit"]) in called]
    tables = {"calls": calls, "decisions": decisions, "proposals": proposals}
    by_id = {key(row["unit"]): row for row in proposals}

    def field_of(row, name):
        action = row.get("requested_action")
        return action.get(name) if isinstance(action, dict) else None

    def measure(metric, rows):
        kind = metric["kind"]
        if kind == "unit_count":
            return {"n": len(rows), "value": _fraction(len(rows), 1)}
        if kind == "action_mean":
            values = [field_of(row, metric["field"]) for row in rows]
            numbers = [Fraction(v) for v in values
                       if isinstance(v, (int, float)) and not isinstance(v, bool)]
            return {"n": len(numbers), "missing": len(rows) - len(numbers),
                    "value": _fraction(sum(numbers, Fraction(0)), len(numbers))}
        if kind == "action_share":
            hits = sum(1 for row in rows if field_of(row, metric["field"]) is not None
                       and canonical(field_of(row, metric["field"]))
                       == canonical(metric["equals"]))
            return {"n": len(rows), "hits": hits, "value": _fraction(hits, len(rows))}
        pairs = [(row, by_id[key(c)]) for row in rows for c in row["candidates"]]
        hits = sum(1 for row, proposal in pairs if row.get("requested_action") is not None
                   and canonical(proposal["value"]) == canonical(row["requested_action"]))
        return {"n": len(pairs), "hits": hits, "value": _fraction(hits, len(pairs))}

    metrics = []
    for metric in contract["metrics"]:
        rows = tables[metric["table"]] if metric["kind"] == "unit_count" else decisions
        by = metric.get("by")
        if by is None:
            groups = [{"group": "*", **measure(metric, rows)}]
        else:
            grouped = {}
            for row in rows:
                grouped.setdefault(row[by], []).append(row)
            groups = [{"group": name, **measure(metric, grouped[name])}
                      for name in sorted(grouped)]
        metrics.append({"metric_id": metric["metric_id"], "kind": metric["kind"], "by": by,
                        "groups": groups})
    admitted = {key(row["unit"]) for row in decisions}
    return {
        "schema": ANALYSIS_OUTPUT_SCHEMA, "run": dataset["run"],
        "experiment_id": dataset["experiment_id"], "plan": dataset["plan"],
        "contract": contract, "dataset": dataset_ref, "population": "ELIGIBLE_DECISION_UNITS",
        "status": "COMPUTED" if decisions else "NO_ADMITTED_UNITS",
        "admitted": {name: [row["unit"] for row in tables[name]] for name in METRIC_TABLES},
        "excluded": [{"unit": row["unit"], "reasons": row["reasons"]}
                     for row in dataset["eligibility"] if key(row["unit"]) not in admitted],
        "metrics": metrics, "limitations": ANALYSIS_LIMITATIONS}


def _ref_of(path: str, document: dict) -> dict:
    data = canonical(document)
    return {"schema": REF_SCHEMA, "role": "call_binding", "path": path, "digest": sha(data),
            "size": len(data)}


# ------------------------------------------------------------ P17 external actors (BVL T5)
# A plan actor answered by a person (through a human channel) or by a tool instead of a
# model.  The contracts are frozen into the plan (plan-9 ``humans``, plan-10 ``tools``);
# each exchange leaves closed documents with identities of their own, which journal-2
# names by content address.  Everything below is re-derived from the package bytes and
# the plan: nobody is asked and no tool is called here.
HUMAN_MODEL = "bvl:human-participant:1"
TOOL_MODEL = "bvl:tool-actor:1"
EXTERNAL_ROLES = ("human_consent", "human_intent", "human_response", "tool_intent",
                  "tool_result")
# a consent record is one participant's under one contract: every call that participant
# answers is asked under it.  A member of any other role is one exchange's alone.
SHARED_EXTERNAL_ROLES = ("human_consent",)
HUMAN_EVENTS = ("HUMAN_REQUEST_DELIVERED", "HUMAN_RESPONSE_RECEIVED")
TOOL_EVENTS = ("TOOL_INTENT_RECORDED", "TOOL_CALL_STARTED", "TOOL_OUTCOME_UNKNOWN",
               "TOOL_RECONCILED", "TOOL_RETURNED")
HUMAN_CONTRACT_SET_SCHEMA = "bvl-human-actor-contract-set-1"
HUMAN_CONTRACT_SCHEMA = "bvl-human-actor-contract-1"
HUMAN_CONTRACT_KEYS = {"schema", "actor_id", "channel", "response", "provenance", "consent",
                       "privacy"}
HUMAN_MODALITIES = ("text",)
# weakest first: an answer is graded no lower than its contract's minimum
HUMAN_GRADES = ("UNVERIFIABLE", "OPERATOR_ENTERED", "CHANNEL_AUTHENTICATED")
HUMAN_CONSENT_BASES = ("INFORMED_CONSENT", "RESEARCHER_PARTICIPANT")
HUMAN_CLASSIFICATIONS = ("NO_PERSONAL_DATA", "PSEUDONYMOUS", "PERSONAL")
HUMAN_RESPONSE_CONTENT = ("IN_PACKAGE", "DIGEST_ONLY")
HUMAN_MAX_CHARS = 1_000_000
HUMAN_CONSENT_EVIDENCE = "bvl-human-consent-evidence-1"
HUMAN_CONSENT_RECORD = "bvl-human-consent-record-1"
HUMAN_CONSENT_KEYS = {"schema", "participant", "contract", "basis", "document_sha256",
                      "status"}
HUMAN_INTENT_EVIDENCE = "bvl-human-intent-evidence-1"
HUMAN_INTENT = "bvl-human-request-intent-1"
HUMAN_INTENT_KEYS = {"schema", "step", "actor", "request", "contract", "channel",
                     "participant", "consent", "privacy"}
HUMAN_RESPONSE_EVIDENCE = "bvl-human-response-evidence-1"
HUMAN_RESPONSE = "bvl-human-response-1"
HUMAN_RESPONSE_KEYS = {"schema", "intent", "participant", "consent", "modality",
                       "content_sha256", "size", "provenance"}
HUMAN_DELIVERY = "bvl-human-delivery-1"
TOOL_CONTRACT_SET_SCHEMA = "bvl-tool-actor-contract-set-1"
TOOL_CONTRACT_KEYS = {"schema", "actor_id", "tool", "effect", "side_effect", "operation",
                      "resource", "arguments", "result"}
# contract-3 (BVL T5-007) is a contract-2 that declares where its arguments come from;
# contract-1 (BVL T5-003, no ``side_effect``) is not a current contract and is refused
TOOL_CONTRACT_SHAPES = {"bvl-tool-actor-contract-2": TOOL_CONTRACT_KEYS,
                        "bvl-tool-actor-contract-3": TOOL_CONTRACT_KEYS
                        | {"argument_selection"}}
# effect -> (the side effects it may declare, intent schema / kind, result schema / kind)
TOOL_EFFECTS = {
    "READ_ONLY": (("NONE",), "bvl-tool-read-intent-1", "tool_read_intent",
                  "bvl-tool-read-result-1", "tool_read_result"),
    "MUTATING": (("IDEMPOTENT_BY_KEY", "IRREVERSIBLE"), "bvl-tool-mutation-intent-1",
                 "tool_mutation_intent", "bvl-tool-mutation-result-1",
                 "tool_mutation_result")}
TOOL_INTENT_KEYS = {"schema", "step", "actor", "request", "contract", "tool", "operation",
                    "resource", "arguments"}
TOOL_OUTCOMES = ("APPLIED", "NOT_APPLIED")
ALNUM = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
# The T5 reasons a package is refused for (FULLMT's own; the prefix of each problem)
T5_PLAN_SHAPE = "T5-PLN-001"        # a humans / tools member is not a closed contract set
T5_PLAN_ORDER = "T5-PLN-002"        # contracts not unique, or not in canonical order
T5_PLAN_BINDING = "T5-PLN-003"      # a contract disagrees with its actor's frozen binding
T5_PLAN_UNCONTRACTED = "T5-PLN-004"  # an actor on a reserved model has no contract
T5_PLAN_SELECTION = "T5-PLN-005"    # a tool argument selected from an ungranted source
T5_CALL = "T5-EXT-001"              # a call is not answered by its declared caller
T5_STRAY = "T5-EXT-002"             # a record or member no declared exchange accounts for
T5_REUSED = "T5-EXT-003"            # one exchange document named by two exchanges
T5_HUMAN_INTENT = "T5-HUM-001"      # the request intent: missing, malformed, not this call's
T5_HUMAN_CONSENT = "T5-HUM-002"     # the consent record: missing, malformed, not GRANTED
T5_HUMAN_EXCHANGE = "T5-HUM-003"    # not delivered once and answered once, in order
T5_HUMAN_RESPONSE = "T5-HUM-004"    # the response: missing, malformed, another exchange's
T5_HUMAN_PROVENANCE = "T5-HUM-005"  # how the answer reached the product
T5_HUMAN_CONTENT = "T5-HUM-006"     # the accepted bytes are not the participant's answer
T5_TOOL_CALL = "T5-TOOL-001"        # the call does not name / journal its one tool intent
T5_TOOL_INTENT = "T5-TOOL-002"      # the tool intent: missing, malformed, not this call's
T5_TOOL_ARGUMENTS = "T5-TOOL-003"   # the arguments are not the contract's selection
T5_TOOL_RESULT = "T5-TOOL-004"      # the tool result: missing, malformed, another intent's
T5_TOOL_CONTENT = "T5-TOOL-005"     # the accepted bytes are not the recorded result's


def _name(value, extra: str, limit: int | None = None) -> bool:
    """A non-empty name of letters, digits and *extra* that starts alphanumeric."""
    return (isinstance(value, str) and bool(value) and value[0] in ALNUM
            and set(value) <= ALNUM | set(extra)
            and (limit is None or len(value) <= limit))


def _pseudonym(value, prefix: str) -> bool:
    """``participant:<token>`` / ``operator:<token>``: a pseudonym and nothing else."""
    return isinstance(value, str) and value.startswith(prefix) \
        and _name(value[len(prefix):], "_-", 64)


def _field_name(value) -> bool:
    return isinstance(value, str) and bool(value) and value[0] in ALNUM \
        and not value[0].isdigit() and set(value) <= ALNUM | {"_"}


def _resource_name(value) -> bool:
    """``<kind>:<name>``: what a tool reads or changes."""
    kind, _, name = value.partition(":") if isinstance(value, str) else ("", "", "")
    return bool(kind) and kind[0] in ALNUM and kind[0].islower() \
        and set(kind) <= set("abcdefghijklmnopqrstuvwxyz0123456789_-") \
        and _name(name, "_./-")


def _typed_object(value, types: dict) -> bool:
    """Exactly the declared fields, each of its declared P06 field type."""
    return isinstance(value, dict) and set(value) == set(types) and all(
        _proposal_type_ok(kind, value[name]) for name, kind in types.items())


def _scalar_object(value) -> bool:
    return isinstance(value, dict) and all(
        isinstance(name, str) and isinstance(item, (str, int, float, bool))
        for name, item in value.items())


def _is_human_contract(contract) -> bool:
    """One closed ``bvl-human-actor-contract-1``: channel, response form, least provenance
    grade, consent terms, privacy."""
    if not isinstance(contract, dict) or set(contract) != HUMAN_CONTRACT_KEYS \
            or contract["schema"] != HUMAN_CONTRACT_SCHEMA:
        return False
    response, provenance = contract["response"], contract["provenance"]
    consent, privacy = contract["consent"], contract["privacy"]
    if not all(isinstance(part, dict) for part in (response, provenance, consent, privacy)):
        return False
    size = response.get("max_chars")
    return (
        _name(contract["actor_id"], "_.-") and _name(contract["channel"], "_.:-")
        and set(response) == {"modality", "max_chars"}
        and isinstance(response["modality"], str) and response["modality"] in HUMAN_MODALITIES
        and isinstance(size, int) and not isinstance(size, bool)
        and 1 <= size <= HUMAN_MAX_CHARS
        and set(provenance) == {"minimum_grade"}
        and isinstance(provenance["minimum_grade"], str)
        and provenance["minimum_grade"] in HUMAN_GRADES
        and set(consent) == {"basis", "document_sha256"}
        and isinstance(consent["basis"], str) and consent["basis"] in HUMAN_CONSENT_BASES
        and is_digest(consent["document_sha256"])
        and set(privacy) == {"classification", "response_content"}
        and isinstance(privacy["classification"], str)
        and privacy["classification"] in HUMAN_CLASSIFICATIONS
        and isinstance(privacy["response_content"], str)
        and privacy["response_content"] in HUMAN_RESPONSE_CONTENT
        # PERSONAL content never enters a package, which cannot honour a deletion
        and (privacy["classification"] != "PERSONAL"
             or privacy["response_content"] == "DIGEST_ONLY"))


def _is_tool_types(types) -> bool:
    return isinstance(types, dict) and all(
        _field_name(name) and isinstance(kind, str) and kind in PROPOSAL_FIELD_TYPES
        for name, kind in types.items())


def _is_tool_contract(contract) -> bool:
    """One closed ``bvl-tool-actor-contract-2`` / ``-3``: the tool, its effect and side
    effect, one operation on one resource, typed arguments and result, and (contract-3)
    where each argument comes from."""
    schema = contract.get("schema") if isinstance(contract, dict) else None
    if not isinstance(schema, str) or set(contract) != TOOL_CONTRACT_SHAPES.get(schema):
        return False
    effect = TOOL_EFFECTS.get(contract["effect"]) if isinstance(contract["effect"], str) \
        else None
    if effect is None or not isinstance(contract["side_effect"], str) \
            or contract["side_effect"] not in effect[0] \
            or not _name(contract["actor_id"], "_.-") or not _name(contract["tool"], "_.:-") \
            or not _name(contract["operation"], "_.-") \
            or not _resource_name(contract["resource"]) \
            or not _is_tool_types(contract["arguments"]) \
            or not _is_tool_types(contract["result"]) \
            or (contract["effect"] == "READ_ONLY" and not contract["result"]):
        return False
    if "argument_selection" not in contract:
        return True
    selection = contract["argument_selection"]
    if not isinstance(selection, dict) or set(selection) != set(contract["arguments"]):
        return False
    for name, origin in selection.items():
        if not isinstance(origin, dict):
            return False
        if set(origin) == {"value"}:
            if not _proposal_type_ok(contract["arguments"][name], origin["value"]):
                return False
        elif set(origin) != {"source", "field"} or not _name(origin["source"], "_.-") \
                or not _field_name(origin["field"]):
            return False
    return True


def _external_plan_problems(semantic: dict) -> list[str]:
    """plan-9 / plan-10 (BVL T5-001 / T5-003): exactly the contracted actors are external.

    A ``humans`` / ``tools`` member is a closed, canonically ordered contract set; each
    contract names a plan actor whose frozen binding states the reserved model, the
    contract's channel / tool as its provider and no generation options; no other actor
    states a reserved model (so a plan without the member has no such actor); nobody is
    contracted as both; a tool contract selects its arguments only from sources its
    actor is granted.
    """
    actors = {item["actor_id"]: item
              for item in (semantic.get("actors") or {}).get("actors", [])}
    information = semantic.get("information") or {}
    granted = {item["actor_id"]: item["sources"] for item in information.get("grants", [])}
    problems, contracted = [], {}
    for section, schema, model, plugin, closed in (
            ("humans", HUMAN_CONTRACT_SET_SCHEMA, HUMAN_MODEL, "channel", _is_human_contract),
            ("tools", TOOL_CONTRACT_SET_SCHEMA, TOOL_MODEL, "tool", _is_tool_contract)):
        names: list = []
        if section in semantic:
            held = semantic[section]
            if not isinstance(held, dict) or set(held) != {"schema", "actors"} \
                    or held["schema"] != schema or not isinstance(held["actors"], list) \
                    or not held["actors"] or not all(closed(item) for item in held["actors"]):
                problems.append(f"{T5_PLAN_SHAPE}: plan {section} are not a closed {schema} "
                                "of current contracts")
                continue
            names = [item["actor_id"] for item in held["actors"]]
            if names != sorted(set(names)):
                problems.append(f"{T5_PLAN_ORDER}: plan {section} contracts are not unique "
                                "and canonically ordered")
            for item in held["actors"]:
                profile = actors.get(item["actor_id"], {}).get("profile")
                if profile is None or profile["model"] != model \
                        or profile["provider"] != item[plugin] or profile["options"]:
                    problems.append(
                        f"{T5_PLAN_BINDING}: {section} contract {item['actor_id']!r} is not "
                        f"held by a plan actor bound to the model {model!r} on its {plugin} "
                        f"{item[plugin]!r}, without generation options")
                if item["actor_id"] in contracted:
                    problems.append(f"{T5_PLAN_BINDING}: actor {item['actor_id']!r} is "
                                    "contracted as a human and as a tool")
                contracted[item["actor_id"]] = section
                for name, origin in sorted((item.get("argument_selection") or {}).items()):
                    if "source" in origin and origin["source"] not in granted.get(
                            item["actor_id"], []):
                        problems.append(
                            f"{T5_PLAN_SELECTION}: tool contract {item['actor_id']!r} "
                            f"selects {name!r} from source {origin['source']!r}, which its "
                            "actor is not granted")
        problems.extend(
            f"{T5_PLAN_UNCONTRACTED}: actor {actor_id!r} is bound to the model {model!r} "
            f"without a {section} contract"
            for actor_id, actor in sorted(actors.items())
            if actor["profile"]["model"] == model and actor_id not in names)
    return problems


def tool_call_chain(events: list, effect: str, side_effect: str):
    """One tool intent's journaled history -> (its terminal record, attempts, problems).

    ``TOOL_INTENT_RECORDED`` opens it; each attempt is started once, in order; a mutating
    tool is started again only after a journaled reconciliation proved the earlier
    attempt changed nothing (never a blind retry); the history ends at ``TOOL_RETURNED``
    or at a reconciliation that recovered an APPLIED result, and nothing follows it.
    """
    if not events or events[0]["event"] != "TOOL_INTENT_RECORDED":
        return None, 0, ["the tool call history does not open with TOOL_INTENT_RECORDED"]
    attempt, started, unknown, proven, terminal = 0, False, False, False, None
    for record in events[1:]:
        event, at = record["event"], f"journal-2 #{record['sequence']}"
        if terminal is not None:
            return None, attempt, [f"{at} {event} follows the result of the call"]
        if event == "TOOL_CALL_STARTED":
            if record.get("attempt") != attempt + 1:
                return None, attempt, [f"{at} starts attempt {record.get('attempt')!r} "
                                       f"after attempt {attempt}"]
            if attempt and effect == "MUTATING" and not proven:
                return None, attempt, [f"{at} calls a mutating tool again while attempt "
                                       f"{attempt} is not proven: a blind retry"]
            attempt, started, unknown, proven = attempt + 1, True, False, False
        elif event == "TOOL_INTENT_RECORDED" or not started \
                or record.get("attempt") != attempt:
            return None, attempt, [f"{at} {event} does not continue attempt {attempt}"]
        elif event == "TOOL_OUTCOME_UNKNOWN":
            if unknown:
                return None, attempt, [f"{at} journals attempt {attempt} unknown twice"]
            unknown = True
        elif event == "TOOL_RETURNED":
            if unknown:
                return None, attempt, [f"{at} returns an attempt journaled unknown"]
            terminal = record
        else:  # TOOL_RECONCILED
            recovered = "tool_result" in record
            if side_effect != "IDEMPOTENT_BY_KEY" or recovered != ("evidence" in record) \
                    or record.get("outcome") != ("APPLIED" if recovered else "NOT_APPLIED"):
                return None, attempt, [f"{at} is not the reconciliation of an "
                                       "IDEMPOTENT_BY_KEY tool: NOT_APPLIED, or APPLIED with "
                                       "its recovered result"]
            if recovered:
                terminal = record
            else:
                started, proven = False, True
    if terminal is None:
        return None, attempt, ["the tool call has no journaled result"]
    return terminal, attempt, []


def _external_actors(records: list, steps: dict, commits: dict, semantic: dict,
                     by_path: dict, documents: dict, held: dict,
                     proposals: dict) -> tuple[dict, list[str]]:
    """M4-EXT: every actor call is answered by the caller its plan declares.

    Returns the reader's own count of who answered, and the problems.  Each exchange is
    re-derived from the package bytes and the plan's contract; a member is evidence here
    only when a journal-2 record of a declared exchange names it by content address.
    """
    actors = {item["actor_id"]: item
              for item in (semantic.get("actors") or {}).get("actors", [])}
    humans = {item["actor_id"]: item
              for item in (semantic.get("humans") or {}).get("actors", [])}
    tools = {item["actor_id"]: item
             for item in (semantic.get("tools") or {}).get("actors", [])}
    information = semantic.get("information") or {}
    sources = {item["source_id"]: item for item in information.get("sources", [])}
    transformed = {(item["actor_id"], item["source_id"])
                   for item in information.get("transforms", [])}
    located = {(s["episode"], s["round"], s["node"]["id"]): k for k, s in steps.items()}
    problems: list[str] = []
    used: dict = {role: {} for role in EXTERNAL_ROLES}  # path -> the exchange naming it
    participants: set = set()
    grades, mutations = Counter(), Counter()
    summary = {"model_calls": 0, "human_exchanges": 0, "tool_calls": 0, "tool_attempts": 0,
               "tool_reconciliations": 0, "arguments_re_derived": 0,
               "arguments_from_frozen_sources": 0}
    frozen: dict = {}  # (source, field) -> the one value every call selected from it

    def member(reference, role: str, code: str, where: str, exchange: str):
        """The packaged member a record names by content address, or None (a problem)."""
        path = reference.get("path") if isinstance(reference, dict) else None
        if not isinstance(path, str) or path not in documents \
                or by_path[path]["role"] != role or reference != _ref(path, by_path):
            problems.append(f"{code}: {where}: names no packaged {role} member")
            return None
        first = used[role].setdefault(path, exchange)
        if first != exchange and role not in SHARED_EXTERNAL_ROLES:
            problems.append(f"{T5_REUSED}: {where}: {path} is already the {role} evidence "
                            f"of {first}")
            return None
        return documents[path]

    def committed(step: dict, producer_id: str):
        """What *producer_id* committed in the step's round, as the JSON an actor observes."""
        producer_key = located.get((step["episode"], step["round"], producer_id))
        producer = steps.get(producer_key)
        if producer is None:
            return None
        if producer["node"]["kind"] == "proposal_parse":
            return (proposals.get(producer["output"]) or {}).get("value")
        try:
            return parse(held[f"artifacts/{commits[producer_key]['artifact']['name']}"])
        except (KeyError, TypeError, ValueError):
            return None

    for step_key, step in steps.items():
        mine = [r for r in records if r.get("step") == step_key]
        node = step["node"]
        where = f"{node['id']!r} round {step['round']}"
        external = [r for r in mine if r["event"] in HUMAN_EVENTS + TOOL_EVENTS]
        if node["kind"] != "actor_call":
            problems.extend(f"{T5_STRAY}: journal-2 #{r['sequence']} {r['event']} is on the "
                            f"{node['kind']} step {where}" for r in external)
            continue
        actor_id = node["config"].get("actor")
        actor = actors.get(actor_id)
        commit = commits.get(step_key)
        of = {name: [r for r in mine if r["event"] == name] for name in (
            "CALL_INTENT_RECORDED", "TRANSPORT_STARTED", "CALL_RETURNED", *HUMAN_EVENTS)}
        if actor is None or commit is None or any(
                len(of[name]) != 1 for name in ("CALL_INTENT_RECORDED", "TRANSPORT_STARTED",
                                                "CALL_RETURNED")):
            if actor_id in humans or actor_id in tools or external:
                problems.append(f"{T5_CALL}: {where}: an external actor's call is not one "
                                "intent, one transport and one return")
            else:
                summary["model_calls"] += 1
            continue
        intent, transport, returned = (of[name][0] for name in (
            "CALL_INTENT_RECORDED", "TRANSPORT_STARTED", "CALL_RETURNED"))
        step_id = _as_identity(step_key)
        actor_identity = identity("actor", {
            "actor_id": actor_id, "role": identity("role", {"role_id": actor["role"]})})
        named_request = intent.get("request") if isinstance(intent.get("request"), dict) \
            else {}
        request_id = named_request.get("identity")
        request = documents.get(f"requests-v2/{named_request.get('name')}")
        request = request if isinstance(request, dict) else {}
        artifact_name = commit["artifact"].get("name") \
            if isinstance(commit.get("artifact"), dict) else None
        artifact = held.get(f"artifacts/{artifact_name}")
        stated = returned.get("response") if isinstance(returned.get("response"), dict) \
            else {}

        if actor_id not in humans and actor_id not in tools:
            summary["model_calls"] += 1
            problems.extend(f"{T5_STRAY}: journal-2 #{r['sequence']} {r['event']} is on the "
                            f"call of model actor {actor_id!r} at {where}" for r in external)
            problems.extend(f"{T5_CALL}: the call of model actor {actor_id!r} at {where} "
                            f"names a {name}"
                            for name in ("human_intent", "tool_call") if name in intent)
            if stated.get("model_identity") in (HUMAN_MODEL, TOOL_MODEL):
                problems.append(f"{T5_CALL}: the call of model actor {actor_id!r} at {where} "
                                f"returned as {stated.get('model_identity')!r}")
            continue

        if actor_id in humans:
            contract = humans[actor_id]
            contract_id = identity("human_actor_contract", contract)
            exchange = f"the exchange of human actor {actor_id!r} at {where}"
            summary["human_exchanges"] += 1
            problems.extend(f"{T5_STRAY}: journal-2 #{r['sequence']} {r['event']} is on the "
                            f"call of human actor {actor_id!r} at {where}"
                            for r in external if r["event"] in TOOL_EVENTS)
            if "tool_call" in intent:
                problems.append(f"{T5_CALL}: the call of human actor {actor_id!r} at {where} "
                                "names a tool call")
            evidence = member(intent.get("human_intent"), "human_intent", T5_HUMAN_INTENT,
                              f"the call of human actor {actor_id!r} at {where}", exchange)
            if evidence is None:
                continue
            asked = evidence.get("intent") if isinstance(evidence, dict) else None
            if not isinstance(evidence, dict) \
                    or set(evidence) != {"schema", "identity", "intent", "consent"} \
                    or evidence["schema"] != HUMAN_INTENT_EVIDENCE \
                    or not isinstance(asked, dict) or set(asked) != HUMAN_INTENT_KEYS \
                    or asked["schema"] != HUMAN_INTENT:
                problems.append(f"{T5_HUMAN_INTENT}: {where}: the human intent evidence has "
                                "the wrong closed shape")
                continue
            intent_id = identity("human_request_intent", asked)
            if evidence["identity"] != intent_id:
                problems.append(f"{T5_HUMAN_INTENT}: {where}: HumanRequestIntentIdentity "
                                "does not recompute from its content")
            expected = {"step": step_id, "actor": actor_identity, "request": request_id,
                        "contract": contract_id, "channel": contract["channel"],
                        "privacy": contract["privacy"]}
            wrong = sorted(name for name, value in expected.items() if asked[name] != value)
            if wrong:
                problems.append(f"{T5_HUMAN_INTENT}: {where}: the human intent is not actor "
                                f"{actor_id!r}'s under the plan's contract "
                                f"({', '.join(wrong)} differ)")
            if not _pseudonym(asked["participant"], "participant:"):
                problems.append(f"{T5_HUMAN_INTENT}: {where}: the participant is not a "
                                "pseudonym")
            participants.add(str(asked["participant"]))
            consent = member(evidence["consent"], "human_consent", T5_HUMAN_CONSENT,
                             f"the human intent at {where}", exchange)
            record = consent.get("record") if isinstance(consent, dict) else None
            if consent is not None and (
                    not isinstance(consent, dict)
                    or set(consent) != {"schema", "identity", "record"}
                    or consent["schema"] != HUMAN_CONSENT_EVIDENCE
                    or not isinstance(record, dict) or set(record) != HUMAN_CONSENT_KEYS
                    or record["schema"] != HUMAN_CONSENT_RECORD):
                problems.append(f"{T5_HUMAN_CONSENT}: {where}: the consent evidence has the "
                                "wrong closed shape")
            elif consent is not None:
                if consent["identity"] != identity("human_consent", record) \
                        or asked["consent"] != consent["identity"]:
                    problems.append(f"{T5_HUMAN_CONSENT}: {where}: HumanConsentIdentity does "
                                    "not recompute from its record, or is not the one the "
                                    "intent asks under")
                if record["status"] != "GRANTED" or record["contract"] != contract_id \
                        or record["participant"] != asked["participant"] \
                        or {"basis": record["basis"],
                            "document_sha256": record["document_sha256"]} != contract["consent"]:
                    problems.append(f"{T5_HUMAN_CONSENT}: {where}: the participant was not "
                                    "asked under a GRANTED consent to exactly the "
                                    "contract's terms")
            delivered, received = (of[name] for name in HUMAN_EVENTS)
            if len(delivered) != 1 or len(received) != 1:
                problems.append(f"{T5_HUMAN_EXCHANGE}: {where}: the request was delivered "
                                f"{len(delivered)} times and answered {len(received)} "
                                "times, not once each")
                continue
            order = [transport["sequence"], delivered[0]["sequence"], received[0]["sequence"],
                     returned["sequence"]]
            if order != sorted(order):
                problems.append(f"{T5_HUMAN_EXCHANGE}: {where}: the exchange is not "
                                "transport -> delivery -> answer -> return")
            if delivered[0].get("human_intent") != intent_id \
                    or received[0].get("human_intent") != intent_id:
                problems.append(f"{T5_HUMAN_EXCHANGE}: {where}: a HUMAN_* record names "
                                "another intent than the call's")
            answer = member(received[0].get("human_response"), "human_response",
                            T5_HUMAN_RESPONSE, f"HUMAN_RESPONSE_RECEIVED at {where}",
                            exchange)
            if answer is None:
                continue
            response = answer.get("response") if isinstance(answer, dict) else None
            provenance = response.get("provenance") if isinstance(response, dict) else None
            if not isinstance(answer, dict) \
                    or set(answer) != {"schema", "identity", "response"} \
                    or answer["schema"] != HUMAN_RESPONSE_EVIDENCE \
                    or not isinstance(response, dict) \
                    or set(response) != HUMAN_RESPONSE_KEYS \
                    or response["schema"] != HUMAN_RESPONSE \
                    or not isinstance(provenance, dict) \
                    or not {"grade", "channel"} <= set(provenance) \
                    or set(provenance) - {"grade", "channel", "entered_by"} \
                    or not isinstance(provenance["grade"], str) \
                    or provenance["grade"] not in HUMAN_GRADES:
                problems.append(f"{T5_HUMAN_RESPONSE}: {where}: the human response evidence "
                                "has the wrong closed shape")
                continue
            if answer["identity"] != identity("human_response", response):
                problems.append(f"{T5_HUMAN_RESPONSE}: {where}: HumanResponseIdentity does "
                                "not recompute from its content")
            if response["intent"] != intent_id \
                    or response["participant"] != asked["participant"] \
                    or response["consent"] != asked["consent"]:
                problems.append(f"{T5_HUMAN_RESPONSE}: {where}: the response answers another "
                                "intent, participant or consent")
            grade, entered = provenance["grade"], provenance.get("entered_by")
            if provenance["channel"] != contract["channel"] \
                    or HUMAN_GRADES.index(grade) < HUMAN_GRADES.index(
                        contract["provenance"]["minimum_grade"]):
                problems.append(f"{T5_HUMAN_PROVENANCE}: {where}: the answer arrived as "
                                f"{grade} through {provenance['channel']!r}; the contract "
                                "accepts no less than "
                                f"{contract['provenance']['minimum_grade']} through "
                                f"{contract['channel']!r}")
            if (grade == "OPERATOR_ENTERED") != (entered is not None) \
                    or (entered is not None and not _pseudonym(entered, "operator:")):
                problems.append(f"{T5_HUMAN_PROVENANCE}: {where}: an OPERATOR_ENTERED answer "
                                "names its operator, and only such an answer does")
            grades[grade] += 1
            if artifact is None or response["content_sha256"] != sha(artifact) \
                    or response["size"] != len(artifact) \
                    or response["modality"] != contract["response"]["modality"]:
                problems.append(f"{T5_HUMAN_CONTENT}: {where}: the accepted response bytes "
                                "are not the content the participant's answer states")
            else:
                try:
                    text = artifact.decode("utf-8")
                except UnicodeDecodeError:
                    text = None
                if text is None or len(text) > contract["response"]["max_chars"]:
                    problems.append(f"{T5_HUMAN_CONTENT}: {where}: the answer is not text "
                                    "within the contract's max_chars")
            if stated.get("model_identity") != HUMAN_MODEL \
                    or stated.get("adapter_provenance") != f"{contract['channel']}:{grade}":
                problems.append(f"{T5_CALL}: {where}: the call does not return as the "
                                "participant's answer through the contract's channel")
            shown = canonical({
                "schema": HUMAN_DELIVERY, "intent": intent_id, "actor": actor_id,
                "participant": asked["participant"], "channel": contract["channel"],
                "provenance_grade": grade, "messages": request.get("messages"),
                "response": contract["response"]}) if "messages" in request else b""
            if delivered[0].get("delivery") != {"schema": HUMAN_DELIVERY, "digest": sha(shown),
                                                "size": len(shown)}:
                problems.append(f"{T5_HUMAN_EXCHANGE}: {where}: the journaled delivery is "
                                "not the persisted request's messages under the contract")
            continue

        contract = tools[actor_id]
        _, intent_schema, intent_kind, result_schema, result_kind = TOOL_EFFECTS[
            contract["effect"]]
        contract_id = identity("tool_actor_contract", contract)
        exchange = f"the call of tool actor {actor_id!r} at {where}"
        summary["tool_calls"] += 1
        problems.extend(f"{T5_STRAY}: journal-2 #{r['sequence']} {r['event']} is on the call "
                        f"of tool actor {actor_id!r} at {where}"
                        for r in external if r["event"] in HUMAN_EVENTS)
        named = intent.get("tool_call")
        if "human_intent" in intent or not isinstance(named, dict) \
                or set(named) != {"contract", "intent"} or named["contract"] != contract_id:
            problems.append(f"{T5_TOOL_CALL}: {exchange} does not name its tool intent under "
                            "the plan's contract")
            continue
        history = [r for r in external if r["event"] in TOOL_EVENTS]
        if not history or {r.get("tool_intent") for r in history} != {key(named["intent"])}:
            problems.append(f"{T5_TOOL_CALL}: {where}: the step does not journal exactly its "
                            "call's tool intent")
            continue
        terminal, attempts, found = tool_call_chain(history, contract["effect"],
                                                    contract["side_effect"])
        problems.extend(f"{T5_TOOL_CALL}: {where}: {problem}" for problem in found)
        summary["tool_attempts"] += attempts
        summary["tool_reconciliations"] += sum(
            1 for r in history if r["event"] == "TOOL_RECONCILED")
        called = member(history[0].get("evidence"), "tool_intent", T5_TOOL_INTENT,
                        f"TOOL_INTENT_RECORDED at {where}", exchange)
        if called is None or terminal is None:
            continue
        if not isinstance(called, dict) or set(called) != TOOL_INTENT_KEYS \
                or called["schema"] != intent_schema:
            problems.append(f"{T5_TOOL_INTENT}: {where}: the tool intent is not a closed "
                            f"{intent_schema}")
            continue
        if identity(intent_kind, called) != named["intent"]:
            problems.append(f"{T5_TOOL_INTENT}: {where}: the tool intent identity does not "
                            "recompute from its content")
        expected = {"step": step_id, "actor": actor_identity, "request": request_id,
                    "contract": contract_id, "tool": contract["tool"],
                    "operation": contract["operation"], "resource": contract["resource"]}
        wrong = sorted(name for name, value in expected.items() if called[name] != value)
        if wrong:
            problems.append(f"{T5_TOOL_INTENT}: {where}: the tool intent is not actor "
                            f"{actor_id!r}'s under the plan's contract "
                            f"({', '.join(wrong)} differ)")
        if not _typed_object(called["arguments"], contract["arguments"]):
            problems.append(f"{T5_TOOL_ARGUMENTS}: {where}: the arguments are not the "
                            "contract's typed arguments")
            continue
        for name, origin in sorted((contract.get("argument_selection") or {}).items()):
            value = called["arguments"][name]
            if "value" in origin:
                selected = origin["value"]
            elif (actor_id, origin["source"]) in transformed:
                continue  # what a transform shows the actor is not package evidence
            elif sources.get(origin["source"], {}).get("source_kind") == "actor_output":
                output = committed(step, sources[origin["source"]]["producer"])
                if not isinstance(output, dict) or origin["field"] not in output:
                    problems.append(f"{T5_TOOL_ARGUMENTS}: {where}: argument {name!r} is "
                                    f"selected from field {origin['field']!r} of "
                                    f"{origin['source']!r}, of which the round committed "
                                    "no such field")
                    continue
                selected = output[origin["field"]]
            else:
                # a frozen source is one byte string of which the package holds the
                # digest, not the bytes: every call selecting one field of it carries
                # one value
                summary["arguments_from_frozen_sources"] += 1
                first = frozen.setdefault((origin["source"], origin["field"]), value)
                if type(first) is not type(value) or first != value:
                    problems.append(f"{T5_TOOL_ARGUMENTS}: {where}: argument {name!r} is "
                                    "not the value other calls selected from field "
                                    f"{origin['field']!r} of the frozen source "
                                    f"{origin['source']!r}")
                continue
            if type(selected) is not type(value) or selected != value:
                problems.append(f"{T5_TOOL_ARGUMENTS}: {where}: argument {name!r} is "
                                f"{value!r}; the declared selection derives {selected!r}")
            else:
                summary["arguments_re_derived"] += 1
        result = member(terminal.get("evidence"), "tool_result", T5_TOOL_RESULT,
                        f"{terminal['event']} at {where}", exchange)
        if result is None:
            continue
        mutating = contract["effect"] == "MUTATING"
        applied = isinstance(result, dict) and result.get("outcome") == "APPLIED"
        keys = {"schema", "intent"} | ({"outcome"} if mutating else {"value"}) \
            | ({"receipt", "value"} if mutating and applied else set())
        if not isinstance(result, dict) or set(result) != keys \
                or result["schema"] != result_schema \
                or (mutating and (not isinstance(result["outcome"], str)
                                  or result["outcome"] not in TOOL_OUTCOMES)) \
                or ("receipt" in result and not _name(result["receipt"], "_.:/-", 128)) \
                or ("value" in result and not _scalar_object(result["value"])):
            problems.append(f"{T5_TOOL_RESULT}: {where}: the tool result is not a closed "
                            f"{result_schema}")
            continue
        if result["intent"] != named["intent"]:
            problems.append(f"{T5_TOOL_RESULT}: {where}: the tool result answers another "
                            "intent")
        if terminal.get("tool_result") != key(identity(result_kind, result)):
            problems.append(f"{T5_TOOL_RESULT}: {where}: the journaled tool result identity "
                            "does not recompute from its evidence")
        if "value" in result and not _typed_object(result["value"], contract["result"]):
            problems.append(f"{T5_TOOL_RESULT}: {where}: the result value is not the "
                            "contract's typed result")
        if terminal["event"] == "TOOL_RECONCILED" and not applied:
            problems.append(f"{T5_TOOL_RESULT}: {where}: a reconciliation recovered a result "
                            "that is not APPLIED")
        if mutating:
            mutations[result["outcome"]] += 1
        content = canonical(result["value"] if "value" in result
                            else {"outcome": "NOT_APPLIED"})
        if artifact != content:
            problems.append(f"{T5_TOOL_CONTENT}: {where}: the accepted response bytes are "
                            "not the ones the recorded tool result derives")
        order = [transport["sequence"], history[0]["sequence"], terminal["sequence"],
                 returned["sequence"]]
        if order != sorted(order):
            problems.append(f"{T5_TOOL_CALL}: {where}: the call is not transport -> tool "
                            "intent -> tool result -> return")
        if stated.get("model_identity") != TOOL_MODEL or stated.get("adapter_provenance") != (
                f"{contract['tool']}:{contract['operation']}:{contract['effect']}"):
            problems.append(f"{T5_CALL}: {where}: the call does not return as its "
                            "contract's tool operation")

    for record in records:
        if record["event"] in HUMAN_EVENTS + TOOL_EVENTS and record.get("step") not in steps:
            problems.append(f"{T5_STRAY}: journal-2 #{record['sequence']} {record['event']} "
                            "is on no IR step")
    for role in EXTERNAL_ROLES:
        stray = sorted(path for path, entry in by_path.items()
                       if entry["role"] == role and path not in used[role])
        if stray:
            problems.append(f"{T5_STRAY}: {role} members no declared exchange accounts "
                            f"for: {stray}")
    summary.update(participants=len(participants),
                   provenance_grades=dict(sorted(grades.items())),
                   mutations=dict(sorted(mutations.items())))
    return summary, problems

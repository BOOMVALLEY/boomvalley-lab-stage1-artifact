# BOOMVALLEY Lab: An Executable Research Infrastructure for Organizational Decision Processes

**Overview for Anonymous Peer Review**

This overview is for readers who meet BOOMVALLEY Lab for the first time. It explains the research problem the software addresses, how it works, what has been demonstrated with it, and where the implementation and supporting evidence can be found in this package. Installation and step-by-step reproduction are covered in `INSTALL.md` and `REPRODUCIBILITY.md`.

## 1. Research Motivation

Decisions in organizations are rarely the product of a single judgment. Who has access to which information, how roles are divided, how drafts are reported upward, who holds approval authority, which rule aggregates individual positions into a decision, and how these steps repeat over time can all shape what an organization ends up doing. Organizational research has long treated such structures as explanatory factors.

When the actors in such a process are AI models, or include them, a researcher can in principle hold an organizational structure fixed, vary one element of it, and observe the resulting process directly. Doing so credibly requires three things: the structure must be stated explicitly as an experimental condition; the process must actually be executed as stated, not approximated; and the execution must leave a record that others can inspect afterwards.

BOOMVALLEY Lab is research infrastructure built for this purpose. It lets a researcher declare an organizational decision structure, execute it, and keep the process as evidence. It does not claim that any particular theory of organizations has been empirically established; it provides the means to run and inspect studies in which such claims could be examined.

## 2. What Is BOOMVALLEY Lab?

In BOOMVALLEY Lab, a study is a single data file, `study.json` (format `bvl-study-1`). The researcher writes no program code; the declaration refers to registered components by name only. Its main elements are:

| Element | What the researcher declares |
|---|---|
| Actors and roles | Who takes part: AI models, people or tools. A role is a label only and grants no authority. |
| Information access | Which actor may see which source. Access is default-deny: an actor sees a source only if an explicit rule allows it. |
| Proposals and decision authority | How an actor's answer is parsed into a structured proposal, and which actors decide under which rule (single, majority, plurality, veto). |
| Protocol and rounds | The order of steps within a round, how rounds repeat, and when the process ends. |
| World state and transitions | The environment that decisions act upon, with rules that judge each requested action. |
| Memory and analysis | What carries over from one round to the next, and the summary measures fixed before the run. |

There is no `organization` key in the declaration. An organization is expressed through the combination of these elements: who is present (actors and roles), who sees what (information access), and who decides (decision authority and rule), arranged in a protocol. **Organizational structure thereby becomes an explicit, executable research procedure.** Every call, response, proposal, decision, World transition and memory produced during execution is recorded as evidence.

## 3. Research Workflow

```text
Researcher
    |
    v
Study Declaration (study.json)
    |
    v
GNDCRW — Comparison Preflight
    |
    v
BOOMVALLEY Lab — Study Execution
    |
    v
MANIFEST-4 — Evidence Package
    |
    v
FULLMT — Independent Conformance Verification
    |
    v
Research Evidence for Inspection
```

**GNDCRW** checks, before a run, that two compared conditions differ in what the researcher declared should differ and are the same in everything declared to stay the same. Its outcome is `RUN`, `BLOCK` or `UNVERIFIABLE`. In a study with experimental factors, BOOMVALLEY Lab derives the comparisons between conditions and calls GNDCRW automatically; the run proceeds only if every comparison returns `RUN`. A study with a single condition has nothing to compare, so this automatic check does not take place. GNDCRW can also be used on its own, with input files the researcher writes, as a separate preflight record (researcher manual, section 1.6).

**BOOMVALLEY Lab** executes a declaration that has passed its gate. It calls the actors in the declared order, gives each only the information it is allowed to see, parses the answers into proposals, applies the decision rules, applies the resulting actions to the World, and records each of these steps. It does not retry failed calls or rewrite responses.

**MANIFEST-4** is the sealed form of a run. `bvl package` writes `MANIFEST-4.json` into the run folder, listing every evidence file with its role, SHA-256 hash and size, and computes a package identity from it.

**FULLMT** is a separate program that shares no code with BOOMVALLEY Lab. From the bytes of the package alone, it checks 20 rules covering member integrity, the plan, decision and World identities, the links between them, the dataset and the analysis, and returns `VERIFIED`, `REJECTED` or `ERROR`. FULLMT does not call the models again, does not re-run the World code, and does not evaluate scientific conclusions.

## 4. Worked Example: A Buying Center

The sample study (`examples/bcp_demo/`) asks a question from research on organizational buying: can the members of a buying organization each judge a purchase favorably while the organization does not buy? We call this case, as a working label, the Buying Center Paradox (BCP). A secondary question is whether the scope of the evaluations the decision maker can see changes what the organization does and how the counterpart responds.

- **Buyer Co.:** four functional evaluators (IT, finance, operations, procurement) and a purchasing director who holds the official authority to accept, counter-offer or walk away. **Supplier Co.:** a sales negotiator who drafts the supplier's response and a commercial manager who decides it.
- The subject is a three-year subscription to a fictitious enterprise software platform (list price 520,000 USD). Each actor receives only the information of its own function: the supplier's lowest acceptable price (430,000) is known only to Supplier Co., the approved budget (480,000) only to the finance evaluator, the company rule on the liability cap only to the procurement evaluator. No actor is told to refuse or to create conflict.
- All seven actors answer with a local model, `qwen2.5:7b-instruct`, served by Ollama, at temperature 0.

The study runs in four phases. In phase P Supplier Co. makes its first offer (450,000). In phase E the four evaluators assess it independently, without seeing each other; all four were in favor, and these four evaluations are used unchanged in both conditions. The comparison is in the last two phases, declared as the two cells of one factor:

- **Condition R (restricted):** the director sees the procurement evaluation only.
- **Condition F (full):** the director sees all four evaluations.

Before any model call, BOOMVALLEY Lab derived the two cells and GNDCRW checked them: the director's information grant was the one declared difference, and 148 other properties (actors and model settings, protocol, decision rules, World, memory, seed, and the bytes of every source file) were the same. The outcome was `RUN`. The sample in this package runs conditions R and F; the outputs of phases P and E are included as fixed inputs, with their sealed records and a script that checks the correspondence.

The recorded run (Windows 11, 2026-10-23, from this package):

| Observation | Condition R | Condition F |
|---|---|---|
| Information the director received (from the recorded request) | deal terms, offer, procurement evaluation | deal terms, offer, all four evaluations |
| Director's decision | counter-offer 420,000 | accept 450,000 |
| Supplier's response | negotiator drafts a counter-offer of 440,000; the manager accepts 420,000 | none needed (the talks had closed) |
| Outcome | agreement at 420,000 | agreement at 450,000 |
| BCP (all in favor, yet no purchase) | not observed | not observed |
| Model calls / evidence package | 3 / 29 members | 3 / 28 members |
| BOOMVALLEY Lab self-check | `VERIFIED`, World replayed | `VERIFIED`, World replayed |
| FULLMT | `VERIFIED CONFORMANCE`, 20 of 20 rules | `VERIFIED CONFORMANCE`, 20 of 20 rules |

Three observations are recorded without interpretation. The paradox did not occur: both directors bought. The director who saw one evaluation (which noted a contract term below company rules, while in favor) made a counter-offer; the director who saw all four accepted at once. And Supplier Co.'s manager accepted a price below the floor stated in its own brief, against the negotiator's draft; the declared decision rule records the manager's answer as the official move and does not enforce the brief. Each condition was run once (the same decisions were also obtained on 2026-10-18), so none of this is evidence of an effect of information scope, or about buying organizations in general. What the example demonstrates is that a buying organization with divided functions, restricted information and a single decision authority can be declared, that two conditions differing in one declared respect can be checked before execution, executed with real model calls, and that the record of who saw what and who decided what can be inspected and verified independently.

### 4.1 Follow-up Example B: one decision restored, with stated reasons

The sealed answers of the worked example contain only the move (`side`, `move`, `price`), so they cannot say why Supplier Co.'s manager accepted a price below its own floor. Example B (`examples/bcp_s2_manual/`, record in `results/bcp_s2_manual/`) addresses that one decision. It restores the negotiation table of condition R just after the director's counter-offer of 420,000, from the sealed R package; the runner first checks that it rebuilds the sealed supplier requests byte for byte. It then runs the two supplier actors again, one call at a time, each started by the researcher after reading its full input, and asks each in the same response for its move and its stated reasons (`rationale`, `evidence_used`, `concerns`). The information each actor receives is that of the sealed run; nothing about the sealed outcome is given.

| Step (2026-10-27) | Decision | Stated reason (model's words) | World |
|---|---|---|---|
| Supplier negotiator | `offer` 440,000 | "We aim to close the deal while ensuring a reasonable profit margin. …" | not applied (a draft) |
| Supplier manager | `accept` 420,000 | "To close the deal and meet the quarter's sales target, we accept the buyer's offer." | `ADMISSIBLE`, agreed at 420,000 |

The manager departed from its negotiator's draft and accepted 10,000 below the lowest acceptable price in its brief. It cited the sales target and did not address the conflict with that price. The World executed the acceptance because its rule judges the table (open talks, the supplier's turn, the price the buyer has on the table); the supplier's floor exists only as text in the supplier's brief. The rule was presented to the actor, not enforced by the environment.

Three limits apply. First, Example B is a **manual harness record — not a BVL sealed package, not FULLMT verified**; the gate, sealing and verification results of the worked example do not extend to it. Second, its reply instruction asks for reasons and its `max_tokens` is 512 (96 in the sealed run), and the sealed evidence does not bind the model digest; so the reasons it records are not the reasons of the sealed call, which remain unknown. Third, each step ran once. That the manager mentioned the sales target does not show that the sales target caused the decision, and that it did not mention the floor does not show that it did not register it. What Example B demonstrates is a procedure: restoring a recorded decision state, controlling each AI call, and keeping the action, its stated reasons and the World outcome together for inspection.

## 5. What This Infrastructure Enables

The contribution is a combination of three elements, offered as a contribution of research infrastructure rather than an empirical finding:

1. **Declarative organizational structure:** roles, information access, reporting and decision authority are stated as research conditions.
2. **Executable organizational process:** the declared structure is executed as an actual multi-actor decision process.
3. **Inspectable execution evidence:** the process is recorded, and the integrity of the record can be checked by independent software.

With the current implementation, a researcher can declare and run studies that compare, for example: information access structures (who sees originals and who sees summaries); model assignments (replacing one actor's model under the same procedure); approval and decision authority (single, majority, plurality, veto); repeated decisions with memory across rounds and episodes; and negotiation with a counterpart outside the organization. Procedures in which people or tools take part as actors can also be declared; their official examples pass validation, but their execution has not been checked (researcher manual, section 1.7). Factor designs are declared in `study.json`, and each condition runs as its own cell. In every case the full execution record is available for inspection (researcher manual, sections 1.2 and 1.7).

Some boundaries shape what can be studied. Each model call is an independent message without accumulated conversation history; earlier rounds reach an actor only through declared memory. The World state is visible to all actors. Analysis aggregates within one run; comparison across conditions is left to the researcher. Generalizing to human organizations, or establishing causal effects, requires the researcher's own research design and empirical work.

## 6. Scope and Interpretation

- BOOMVALLEY Lab is infrastructure for executing experimental procedures. It does not itself produce scientific conclusions.
- A GNDCRW `RUN` means that the declared differences and invariants held for the compared conditions. It is not a judgment of scientific validity.
- FULLMT's `VERIFIED CONFORMANCE` means that the package is unchanged since sealing and that the run conformed to its fixed plan and protocol. It is not a verification of a scientific finding, of the truth of model outputs, or of a research conclusion. Packages are not signed.
- The plan of a study is fixed by its declaration, and verification of a sealed package gives the same result on any machine. The answers of the model in a new run are not guaranteed to be the same.
- The worked example is an operating case of the platform, not a test of organizational theory. Example B is a single follow-up observation made with a manual harness, not a confirmatory result.

The full list of supported and unsupported features is in section 1.7 of the researcher manual, and the guarantees and non-guarantees of each tool in Part 6.

## 7. Where to Start

1. This overview — research motivation and architecture.
2. `examples/bcp_demo/README_EN.md` — the worked example, with `SAMPLE_GUIDE_EN.md` and `EXPECTED_OUTPUTS_EN.md`; its run record is in `results/bcp_demo/`.
3. `examples/bcp_s2_manual/README.md` — Example B, the restored supplier decision with stated reasons; its record and result are in `results/bcp_s2_manual/` (`FINAL_RESULT_EN.md`).
4. `REPRODUCIBILITY.md` — how to reproduce the demonstration (installation in `INSTALL.md`); section 8 for Example B.
5. `docs/RESEARCHER_MANUAL_EN.md` (PDF edition alongside) — the full implementation and research usage; `docs/RESEARCHER_MANUAL_EN_ADDENDUM_EXAMPLE_B.md` for Example B.
6. Source code — `boomvalley-lab/src/boomvalley_lab/` (BOOMVALLEY Lab), `gndcrw/src/gndcrw/` (GNDCRW), `fullmt/` (FULLMT).

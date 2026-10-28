# Example B — Experiment Protocol (S2)

**Evidence class: MANUAL HARNESS RECORD — NOT A BVL SEALED PACKAGE — NOT FULLMT VERIFIED.**

## 1. Question

In the state where Buyer Co. has counter-offered 420,000 against Supplier Co.'s offer of 450,000, what do the supplier's negotiator and manager decide, and what reasons do they state in the same response? In particular: does the manager, who decides the official move, keep to the lowest acceptable price of 430,000 stated in its brief?

Accepting, counter-offering and walking away were all admissible outcomes of the experiment. Reproducing the sealed decision was not a goal.

## 2. Design

| Step | Actor | Information (besides `world`) | Output | World |
|---|---|---|---|---|
| N | `supplier_negotiator` | `supplier_negotiator_response_brief` | draft move | not applied |
| M | `supplier_manager` | `supplier_manager_response_brief`, `supplier_draft` (step N) | official move | applied (`NegotiationWorldV1`) |

- Information access is that of the sealed R run (its call bindings grant the negotiator its brief only, and the manager its brief and the draft).
- `supplier_draft` is the `side`/`move`/`price` of step N as canonical JSON, the form in which BOOMVALLEY Lab renders an actor output. The negotiator's reasons are not passed on.
- The decision authority is the manager alone (as `builtin.single-authority:1` in the sealed run): its parsed move is applied to the World.
- Each call is one user message without conversation history.
- The supplier actors are not told the outcome of the sealed run, and no instruction encouraging any outcome is added.

## 3. Inputs

| Input | File |
|---|---|
| World state after the counter-offer | `inputs/original_R_run/evidence-v2/world_state/74ec4cc1….json` |
| Sealed negotiator and manager requests (for the restoration check and the seeds) | `inputs/original_R_run/requests-v2/request-078d3acc….json`, `request-c6e13f68….json` |
| Briefs | `harness/inputs/original/phase_rf/supplier_negotiator_response_brief.json`, `supplier_manager_response_brief.json` (byte-identical to `examples/bcp_demo/sources/`) |
| Reply instruction | `harness/protocol.json`, `replies.seller_response` |
| Options | `harness/protocol.json`, `options.move` |

**Restoration check (at `init`, before any call).** The runner rebuilds the sealed negotiator message from the frozen brief, and the sealed manager message from the frozen brief and the sealed draft (`offer` 440,000), with the original reply instruction, and requires both to be byte-identical to the sealed requests; it also requires the World file to equal the `world` of both sealed requests. If any check fails, no session is created.

## 4. Reply instruction and options

The `reply` field of each brief is the only text changed. Original:

> Answer with one JSON object and nothing else: {"side": "seller", "move": "accept" or "offer" or "walk_away", "price": <integer USD>}. For accept, price is exactly world.offers.buyer. For walk_away use price 0.

S2 (as in S1):

> Answer with one JSON object and nothing else: {"side": "seller", "move": "accept" or "offer" or "walk_away", "price": <integer USD>, "rationale": <string>, "evidence_used": [<string>, ...], "concerns": [<string>, ...]}. For accept, price is exactly world.offers.buyer. For walk_away use price 0. rationale: the main reasons for your decision, in at most three sentences. evidence_used: the information you relied on, each item naming its source (a key of information, or world) and the point you used. concerns: the concerns that affected your decision (an empty list if none).

The request for reasons is neutral: it names no rule, price or target.

| Option | Sealed R run | S2 |
|---|---|---|
| model | `qwen2.5:7b-instruct` | the same, at `http://127.0.0.1:11434/v1` |
| temperature | 0 | 0 |
| `response_format` | `json_object` | `json_object` |
| `max_tokens` | 96 | 512 (96 truncates the reasons; a truncated answer is an error for the adapter) |
| seed | BVL-derived | the same values as the sealed calls (N `6900140034330824044`, M `6841311227714416853`) |

## 5. Processing of an answer

1. `OpenAIChatAdapterV1`: one attempt, no retry; an answer whose `finish_reason` is not `stop` is an error.
2. The answering model must be the requested one.
3. `JsonProposalParserV1` parses the JSON (duplicate keys etc. rejected).
4. `side`/`move`/`price` are checked against the closed move schema; `side` must be `seller`. Only these three fields go to the World. `rationale`, `evidence_used` and `concerns` are recorded as stated reasons.
5. Step M only: `NegotiationWorldV1` applies the move to the restored state. An `accept` is admissible on open talks, by the side whose turn it is, at the price the other side has on the table. The supplier's lowest acceptable price is not part of the World.
6. Rule checks recorded as facts, nothing corrected: below the lowest acceptable price, above the list price, different from the draft, talks already closed.

## 6. Stopping rules

- Any provider error, model mismatch, parse failure or schema violation halts the session; the step is not retried.
- An approval written without a result blocks the step from running again.
- If any input file changed after `init`, every command is refused.
- The model digest reported by Ollama must be the same at each call as at `init`.
- The researcher may stop after any step.
- One session (S2); no repetition.

## 7. Differences from the sealed run of Example A

| Item | Example A (sealed R) | Example B (S2) |
|---|---|---|
| Engine | `bvl run` with gate-2 and GNDCRW | manual runner reusing BVL components |
| Evidence | `MANIFEST-4.json`, `bvl verify`, FULLMT | JSON records with SHA-256 values; no seal, no FULLMT |
| Reply instruction, `max_tokens` | `side`/`move`/`price`, 96 | with reasons, 512 |
| Model digest | not bound in the evidence | recorded at `init` and at each call |
| Renderer label | `bvl.json-renderer:1` | `bcp-manual:json-message (bvl.json-renderer:1 layout)` (same message layout) |
| Calls | three, consecutive and automatic | two, each started by the researcher after seeing its full input |

# Neuroscience Appendix

NeuroStack's ranking and clustering features draw on memory neuroscience. This appendix maps each feature to its scientific basis and, more importantly, to what the code actually does. Where the biology is an inspiration rather than a faithful mechanism, it says so.

Verified against the implementation at commit `63e16d2`.

**Status tags** used below:

- `[implemented]` — a real signal that changes retrieval or clustering output.
- `[analogy]` — a useful design framing, not a mechanistic reproduction of the biology.
- `[timer-gated]` — inert on a default install; requires an optional background timer to differentiate results.
- `[retired]` — described here for history; no live code path.

## Ranking pipeline order

Every hybrid search applies these signals in order, in `search.py:hybrid_search`. Later sections describe each one.

1. Base score: `0.3 · FTS5_rank + 0.7 · cosine`
2. Link-section down-weight (navigational chunks, `×0.5`)
3. Convergence confidence (blended `0.7 · score + 0.3 · convergence`)
4. Context boost (`×1.4` direct, `×1.2` graph-neighbour)
5. Hotness (blended `0.8 · score + 0.2 · hotness`)
6. Co-occurrence boost (bounded `×(1 + w·norm)`)
7. Excitability boost (`×1.15` for `status: active`)
8. Prediction-error demotion (`×1/(1 + 0.1·n)`)
9. Lateral inhibition (winner-take-all diversity penalty)

## Hotness and Excitability (Recency Decay + CREB Windows)

**Feature**: Recently and frequently retrieved notes rank higher; notes marked `status: active` receive a small boost.

**Implementation**:
- Hotness (`search.py:hotness_score`, `[implemented]`): `sigmoid(log1p(usage_count)) · exp(-ln2/half_life · age_days)` with a **30-day half-life**, blended at 0.2. Usage is auto-recorded for every returned result, so the signal is continuously updated.
- Excitability boost (`search.py`, `[timer-gated]`): a flat `×1.15` when `note_metadata.status == 'active'`. Note that `status` defaults to `active` and is only ever demoted by `run_excitability_demotion`, which runs solely from `neurostack decay --demote` — an opt-in, systemd-based timer. Without that timer every note stays `active`, so the boost applies uniformly and does not differentiate results. Install the decay timer for it to have any effect.

**Science**: CREB-mediated intrinsic excitability biases which neurons are recruited into an engram. Neurons with elevated CREB at encoding are preferentially allocated, creating a transient window (on the order of hours in the biology) during which a memory attracts new associations. NeuroStack's hotness decay is a much slower software analogue (days, not hours) tuned for how often notes are actually re-read; the ~6-hour biological window is the inspiration, not the parameter.

**References**:
- Han, J.-H. et al. (2007). Neuronal competition and selection during memory formation. *Science*, 316(5823), 457-460.
- Yiu, A. P. et al. (2014). Neurons are recruited to a memory trace based on relative neuronal excitability. *Neuron*, 83(3), 722-735.

## Hebbian Co-occurrence Learning

**Feature** `[implemented]`: Entities that appear together in notes accumulate association weight; a query that matches one entity boosts notes containing its learned associates. The associations strengthen every time the paired entities are co-retrieved.

**Implementation**: `cooccurrence.py` maintains an `entity_cooccurrence` table. On every search, entity pairs shared between the query and result notes are reinforced (`weight = min(old · 1.1, 100)`); new pairs seed at 1.0 (`search.py:hybrid_search` reinforcement step). The boost is bounded so it lifts but never dominates the base score. This is the signal that makes the vault's retrieval improve with use.

**Science**: "Cells that fire together wire together." Repeated co-activation strengthens synaptic connections, the basis of associative memory. Co-retrieval of two entities is the software equivalent of co-activation.

**References**:
- Hebb, D. O. (1949). *The Organization of Behavior*. Wiley.

## Convergence Confidence (Energy-Landscape Basin Width)

**Feature** `[implemented]`: A matched note ranks higher when the matched chunk is representative of the note as a whole, and lower when it matched an outlier fragment.

**Implementation** (`search.py`): `convergence = cosine(query, chunk_centroid) / (1 + σ)`, where `σ` is the standard deviation of the note's chunk-to-query similarities. Blended at `0.7 · score + 0.3 · convergence`. Single-chunk notes are treated as perfectly representative.

**Science**: In attractor networks, a deep, narrow energy well (low variance) converges cleanly to a stored pattern, while a shallow, broad well (high variance) signals a noisy or heterogeneous memory. Convergence confidence is a cheap proxy for basin depth over a note's chunk embeddings.

**References**:
- Hopfield, J. J. (1982). Neural networks and physical systems with emergent collective computational abilities. *PNAS*, 79(8), 2554-2558.
- Ramsauer, H. et al. (2020). Hopfield Networks is All You Need. *arXiv:2008.02217*.

## Lateral Inhibition (Winner-Take-All Diversity)

**Feature** `[implemented]`: Higher-ranked results suppress semantically similar competitors, so the result set stays diverse instead of returning near-duplicates.

**Implementation** (`search.py`): over a candidate pool of `3 · top_k`, each result from rank 2 down is penalised by `×(1 − 0.30 · max_similarity_to_higher_ranked)` when that similarity exceeds `0.65`, then re-sorted. The penalty is bounded so even a maximally similar result keeps 70% of its score.

**Science**: The size of a memory engram is held sparse by inhibition. The most excitable neurons fire first and recruit dendrite-targeting somatostatin (SOM+) interneurons that suppress neighbouring cells, a lateral-inhibition microcircuit that caps engram size. Suppressing near-duplicate results mirrors that sparsity constraint.

**References**:
- Stefanelli, T. et al. (2016). Hippocampal somatostatin interneurons control the size of neuronal memory ensembles. *Neuron*, 89(5), 1074-1085.
- Han, J.-H. et al. (2007). Neuronal competition and selection during memory formation. *Science*, 316(5823), 457-460.

## Drift Detection (Prediction Errors)

**Feature** `[implemented]`: Notes that repeatedly surface for queries they fit poorly are flagged and demoted.

**Implementation** (`search.py`): after ranking, the top result's raw cosine is checked. Below `0.38` it logs a `low_overlap` error; a note retrieved outside its expected context with similarity below `0.45` logs `contextual_mismatch`. Only notes that have surprised on `>= 2` distinct retrieval events are surfaced (via `vault_prediction_errors`) and demoted (`×1/(1 + 0.1·n)`). Detection is rate-limited to once per hour per note.

**Scope note**: this implements the *detection* half of the neuroscience. The biology's reconsolidation step — rewriting the memory trace to absorb the new information — is **not** automated here. NeuroStack flags and demotes; a human or agent then re-links, updates, or resolves the note. Automatic retrieval-time updating is tracked in issue #38.

**References**:
- Sinclair, A. H., Manalili, G. M., Brunec, I. K., Adcock, R. A. & Barense, M. D. (2021). Prediction errors disrupt hippocampal representations and update episodic memories. *PNAS*, 118(51), e2117625118.
- Fernandez, R. S. et al. (2016). The fate of memory: reconsolidation and the case of prediction error. *Neuroscience & Biobehavioral Reviews*, 68, 423-441.

## Knowledge Graph (Engram Connectivity)

**Feature** `[implemented]`: Wiki-links form a graph; PageRank scores relative connectivity.

**Implementation** (`graph.py`): a `graph_edges` table plus PageRank (damping 0.85). Note that PageRank drives graph navigation and the `vault_graph` neighbourhood view; it is **not** a term in the search ranking score.

**Science**: Engrams are not isolated. Hub neurons with high connectivity facilitate retrieval and cross-context generalisation. PageRank approximates relative accessibility of nodes in an associative network.

**References**:
- Tonegawa, S. et al. (2015). Memory engram cells have come of age. *Neuron*, 87(5), 918-931.
- Josselyn, S. A. & Tonegawa, S. (2020). Memory engrams: recalling the past and imagining the future. *Science*, 367(6473).

## Community Detection (Neural Ensembles via Hopfield Attractors)

**Feature** `[implemented]` `[timer-gated]`: Related notes cluster into thematic communities used by GraphRAG global queries.

**Implementation** (`attractor.py`): clustering runs Hopfield-style attractor dynamics, **not** Leiden (which earlier versions used). A blended similarity matrix (roughly `0.6` embedding cosine + `0.25` Hebbian co-occurrence + `0.15` wiki-link structure) is iterated as `state(t+1) = softmax(β · S · state(t))` at two inverse temperatures — `β = 0.5` for coarse communities and `β = 2.0` for fine ones. Notes converging to the same attractor form a community.

**Refresh caveat**: `detect_communities` runs only from `neurostack communities build` and `neurostack init`. It is **not** part of the index pipeline, so communities and their summaries go stale after notes are added or edited until a rebuild is run. `vault_communities` degrades quietly rather than erroring. Staleness reporting and auto-refresh are tracked in issue #65.

**Science**: Memories are organised into overlapping neural ensembles; shared membership between notes mirrors shared neuronal membership between engrams, the basis for memory linking and generalisation. Modern Hopfield networks give this a principled energy-landscape formulation with a temperature parameter that controls granularity.

**References**:
- Cai, D. J. et al. (2016). A shared neural ensemble links distinct contextual memories encoded close in time. *Nature*, 534, 115-118.
- Ramsauer, H. et al. (2020). Hopfield Networks is All You Need. *arXiv:2008.02217*.

## Tiered Retrieval (Depth-First Access)

**Feature** `[analogy]`: Retrieval escalates through triples (fast, cheap) → summaries → full content, matching the caller's token budget.

**Implementation** (`search.py:tiered_search`): `depth="auto"` starts with triples and escalates when triple coverage is low. This is a genuine and useful token-cost hierarchy. The mapping to complementary learning systems is a framing, not a mechanism: NeuroStack has no separate fast/slow learners consolidating on different timescales.

**Science**: Memory retrieval is hierarchical — gist-level semantic information is accessed before detailed episodic content, which takes more effort. CLS theory proposes fast hippocampal and slow neocortical systems for this division of labour.

**References**:
- McClelland, J. L., McNaughton, B. L. & O'Reilly, R. C. (1995). Why there are complementary learning systems in the hippocampus and neocortex. *Psychological Review*, 102(3), 419-457.

## Compositional Notes (PFC Subspaces)

**Feature** `[retired]`: A linking heuristic — when cross-referencing, prefer notes that encode reusable structural patterns transferable across domains.

**Status**: earlier versions tracked this with a `compositional` column in `note_metadata`. The column was write-only (no retrieval path ever read it) and was dropped in schema v15. Nothing in the current code acts on compositionality; it remains a valid manual linking bias with no automated support.

**Science**: Prefrontal cortex encodes task structure as compositional subspaces — reusable neural patterns combined to solve novel tasks without retraining. Compositional notes are the vault analogue of those transferable representations.

**References**:
- Zheng, H. et al. (2025). Compositional coding of task structure in human PFC. *Nature Neuroscience* (preprint).

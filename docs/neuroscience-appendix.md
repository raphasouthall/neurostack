# Neuroscience Appendix

NeuroStack's features are grounded in memory neuroscience. This appendix maps each feature to its scientific basis.

## Hot Notes (Excitability Windows)

**Feature**: Notes with `status: active` receive preferential linking.

**Science**: CREB-mediated neuronal excitability determines which neurons are recruited into memory engrams. Neurons with elevated CREB levels at encoding time are preferentially recruited, creating a temporal window (~6 hours) during which they attract new connections.

**References**:
- Han, J.-H. et al. (2007). Neuronal competition and selection during memory formation. *Science*, 316(5823), 457-460.
- Yiu, A. P. et al. (2014). Neurons are recruited to a memory trace based on relative neuronal excitability. *Neuron*, 83(3), 722-735.

## Drift Detection (Prediction Errors)

**Feature**: Notes flagged when retrieved in unexpected contexts (high semantic distance).

**Science**: Prediction error signals drive memory updating. When retrieved information mismatches expectations, the hippocampus generates prediction errors that trigger memory reconsolidation — updating the memory trace to incorporate new information.

**References**:
- Sinclair, A. H. & Bhatt, M. A. (2022). Prediction errors disrupt hippocampal representations and update episodic memories. *PNAS*, 119(31).
- Fernandez, R. S. et al. (2016). The fate of memory: Reconsolidation and the case of prediction error. *Neuroscience & Biobehavioral Reviews*, 68, 423-441.

## Knowledge Graph (Engram Connectivity)

**Feature**: Wiki-link graph with PageRank scoring.

**Science**: Memory engrams are not isolated — they form interconnected networks. Hub neurons with high connectivity facilitate memory retrieval and cross-context generalization. PageRank approximates the relative accessibility of nodes in an associative network.

**References**:
- Tonegawa, S. et al. (2015). Memory engram cells have come of age. *Neuron*, 87(5), 918-931.
- Josselyn, S. A. & Tonegawa, S. (2020). Memory engrams: Recalling the past and imagining the future. *Science*, 367(6473).

## Community Detection (Neural Ensembles)

**Feature**: Leiden algorithm clusters related notes into thematic communities.

**Science**: Memories are organized into overlapping neural ensembles. Shared entity membership between notes mirrors shared neuronal membership between engrams, which is the basis for memory linking and generalization.

**References**:
- Cai, D. J. et al. (2016). A shared neural ensemble links distinct contextual memories encoded close in time. *Nature*, 534, 115-118.

## Tiered Retrieval (Depth-First Search)

**Feature**: Triples (fast/cheap) → Summaries → Full content.

**Science**: Memory retrieval operates hierarchically: gist-level information is accessed first (semantic memory), with detailed episodic content requiring additional retrieval effort. This mirrors the complementary learning systems theory.

**References**:
- McClelland, J. L. et al. (1995). Why there are complementary learning systems in the hippocampus and neocortex. *Psychological Review*, 102(3), 419-457.

## Compositional Notes (PFC Subspaces)

**Feature**: Notes tagged `compositional: true` are reusable structural patterns that transfer across domains.

**Science**: Prefrontal cortex encodes task structure as compositional subspaces — reusable neural patterns that can be combined to solve novel tasks without retraining. Compositional notes are the vault's equivalent of these transferable representations.

**References**:
- Zheng, H. et al. (2025). Compositional coding of task structure in human PFC. *Nature Neuroscience* (preprint).

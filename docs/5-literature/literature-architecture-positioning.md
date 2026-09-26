# Literature: where this architecture sits, and what licenses each adaptation

Fills a gap. `literature-mece-positioning.md` and
`literature-ladder-positioning.md` cover the *application* (sum-to-one
arbitrage in prediction markets). Neither positions the *model*.

**Verify venues and years before the bibliography.** Items marked
✅ were checked against the paper or a listing on 2026-09-26; the rest are
leads from memory.

---

## 1. The starting point, and that it is correctly cited

§5.4 of the report adapts:

> ✅ Pulikandala Nithish Kumar, Nneka Umeorah, Alex Alochukwu,
> *Dynamic graph neural networks for enhanced volatility prediction in
> financial markets*, arXiv 2410.16858. Temporal GAT; eight global indices;
> 15 years; volatility forecasting.

The citation is real and "designed for financial assets" is accurate. A
later journal version appears to exist (*Regime-Dependent Graph Neural
Networks for Enhanced Volatility Prediction*, Mathematics/MDPI,
doi 10.3390/math14020289) — check whether to cite that instead.

## 2. The family

The taxonomy to use in the methods chapter is **learned-graph** versus
**given-graph** spatio-temporal GNNs.

- **Learned-graph**: AGCRN (Bai et al., NeurIPS 2020) learns adjacency from
  node embeddings; Graph WaveNet (Wu et al., IJCAI 2019) learns a
  self-adaptive adjacency.
- **Given-graph**: ASTGCN (Guo et al., AAAI 2019), GMAN (Zheng et al., AAAI
  2020), STGCN (Yu et al., IJCAI 2018), DCRNN (Li et al., ICLR 2018).

This project is given-graph, because a MECE leg belongs to its basket by
settlement identity. Nearest single ancestors: **ASTGCN** and **GMAN**.

## 3. Each adaptation, and what licenses it

| departure from Kumar et al. | citation | the argument |
|---|---|---|
| **Two relation-specific channels** rather than one GAT channel | R-GCN (Schlichtkrull et al., ESWC 2018); HAN (Wang et al., WWW 2019); HGT (Hu et al., WWW 2020) | MECE is an *equality* constraint, the ladder an *inequality* constraint. Sharing parameters across them assumes a homogeneous graph, which is the assumption these three papers exist to relax. |
| **GATv2** rather than GAT | ✅ Brody, Alon & Yahav, *How Attentive are Graph Attention Networks?*, arXiv 2105.14491, ICLR 2022 | They prove GAT computes **static attention**: the ranking of neighbours is shared across all query nodes, so a node cannot prefer different neighbours than another node does. GATv2 removes that limitation. This is the cleanest single justification in the whole list — quote the static-attention result directly. |
| **`TypeSpecificProjection`** for heterogeneous nodes | HGT (Hu et al., WWW 2020) — type-specific projection matrices; R-GCN | Basket hub nodes and leg nodes carry different feature semantics (a hub holds `sum_cents` and `legs_total`; a leg holds price and volume). A shared projection conflates them. |
| **Sparse typed edge lists** rather than dense `A ∈ ℝ(T×N×N)` | PyTorch Geometric COO convention (Fey & Lenssen, 2019); inductive setting from GraphSAGE (Hamilton et al., NeurIPS 2017) | Arithmetic is the stronger argument: T=168, N=7,204 gives 8.7 billion entries per chunk. Also the node set is **transient** — contracts are born and settle — so per-node learned embeddings have nothing stable to attach to. |
| **Basket hub node** joining N legs | hypergraph **star expansion** — Agarwal, Branson & Belongie, *Higher Order Learning with Graphs*, ICML 2006; HGNN (Feng et al., AAAI 2019) | A sum-to-one basket is a hyperedge over N legs, not a set of pairwise edges. Star expansion is the standard reduction and preserves the N-ary constraint that a clique expansion destroys. |
| **Spatial then temporal** rather than temporal then spatial | ASTGCN (Guo et al., AAAI 2019) applies spatial attention before temporal within each block | Domain argument is stronger: the constraint is **instantaneous** — legs must sum to $1 at every moment — so spatial aggregation belongs on the within-timestep snapshot, before temporal integration. |
| **`ResidualForecastHead`**, `pred = base + delta`, final layer zero-init | ✅ ReZero (Bachlechner et al., arXiv 2003.04887, PMLR v161 / UAI 2021); ✅ Fixup (Zhang, Dauphin & Ma, arXiv 1901.09321, ICLR 2019); N-BEATS doubly-residual stacking (Oreshkin et al., ICLR 2020) | Domain argument is the strong one: prediction-market prices are **near-martingales**, so persistence is the theoretically motivated baseline. Zero-initialising the final layer makes the model *start exactly at persistence*, so every improvement is attributable to learned structure rather than to initialisation. This is what makes the shrinkage-oracle comparison interpretable. |
| **No reconstruction head** | graph autoencoders / VGAE (Kipf & Welling, 2016) motivate reconstruction as a way to *learn* structure | Symmetric argument: reconstruction exists to help a model recover structure it was not given. This model is given the structure, so there is nothing to reconstruct that was not supplied. It would also add a loss-balancing hyperparameter with no held-out budget to tune it. |

## 4. The two arguments that need no citation

These are stronger than anything in the table because they are statements
about the data, not appeals to authority:

1. **The graph is a theorem, not an estimate.** In the financial-GNN
   literature (Feng et al., TOIS 2019, relational stock ranking; HATS, Kim
   et al., 2019) the relation is statistical or assumed — same sector,
   shared ownership, supply chain — and can be wrong. Here the legs of a
   MECE basket must sum to $1 at resolution or one is mispriced by
   construction. That is what makes the ~92% ablation attribution meaningful:
   the graph carries the signal because the graph is *right*, not fitted.

2. **Persistence is the correct null for a near-martingale.** Hence the
   zero-init residual head, and hence the shrinkage oracle as the second
   baseline.

## 5. The honest framing

Every component is off the shelf. Say so. The contribution is not the
architecture, it is what the graph encodes and what that makes measurable.
Examiners react badly to a standard assembly presented as novel, and well to
"we adapt X with the following modifications, for the following reasons."

Suggested sentence:

> The model adapts the Temporal GAT of Kumar et al. (2024) to a
> heterogeneous, transient node set with two structurally distinct edge
> types. We retain the given-graph formulation and attention-based spatial
> message passing, and depart in five respects: relation-specific channels
> after R-GCN and HGT; GATv2 in place of GAT, following Brody et al.'s
> static-attention result; a hypergraph star expansion for the sum-to-one
> basket; spatial aggregation before temporal integration, since the
> no-arbitrage constraint is instantaneous; and a zero-initialised residual
> head so the model begins at persistence, the theoretically motivated
> baseline for a near-martingale price process.

## 6. A gap an examiner may probe

There is **no comparison against a published spatio-temporal baseline**
(AGCRN, DCRNN, Graph WaveNet, STGCN). The evidence that the architecture is
appropriate is the internal no-graph ablation, which is an internal
comparison.

With four weeks remaining, do not run one. Cite the parallel AGCRN result in
this group instead: an off-the-shelf learned-graph model applied to a
related Kalshi forecasting task, where no configuration beat predict-zero,
capacity hurt monotonically, and the learned adjacency recovered **0 of 4**
independently validated edges. Confirm with the supervisor that citing a
concurrent project is acceptable.

## 7. A consistency check against §5.4 of the report

§5.4 as written no longer describes the implementation:

| §5.4 says | the code does |
|---|---|
| temporal encoder **first**, then spatial | **spatial first, then temporal** (confirmed by runtime logs: projection → spatial → temporal) |
| dense `A ∈ ℝ(T×N×N)` | sparse per-type edge lists |
| one GAT channel | two channels |
| GAT attention `softmax(LeakyReLU(aᵀ[Wh_i ‖ Wh_j]))` | GATv2 |
| no node-type handling | `TypeSpecificProjection` |
| optional reconstruction head, combined loss | not implemented |
| — | `ResidualForecastHead`, zero-init, load-bearing |

Two internal problems in §5.4 independent of the implementation: the
glossary defines **W₁ and W₂** while the equation shows a single `W` and has
**no self-term**, and the attention formula quoted is the original GAT,
whose static attention is what GATv2 exists to fix.

# Digonto figure assets

Generated entirely by `make_figures.py`. Regenerate every PNG with:

```
python3 make_figures.py
```

Pure matplotlib, no seaborn, no external images, no network access, deterministic output. All 11 figures are written to `out/` at 300 dpi on a white background.

## Style

Binding palette and typography from `writing_instructions.md` Part 3: Blue #2563EB, Orange #E8710A, Green #059669, Neutral grey #6B7280, text #111827, gridlines #E5E7EB; Arial/Helvetica/DejaVu Sans, 9 to 9.5 pt; flat 2D, no gradients or drop shadows; designed at true IEEE print width (3.5 in single column, 7.16 in double column). The same colour keeps the same meaning in every figure it appears in: blue is the fast loop / primary series / the Tools capability, orange is the recurrent loop / a refused or rejected outcome / the Vision capability, green is the continual loop / a verified or promoted outcome / the Audio capability, grey is storage / a neutral or cold system state / the Thinking capability.

Agent names appear in English only inside the images: the binding font stack (Arial, Helvetica, DejaVu Sans) has no Bengali glyphs, so Bangla script would render as missing-glyph boxes. Bangla names stay in the surrounding prose.

## Figures

| # | File | Width | Class | Title |
|---|------|-------|-------|-------|
| 01 | `out/fig01_problem_scale.png` | double column, 7.16 in | MEASURED | Bangladesh outbound study market: scale of the problem |
| 02 | `out/fig02_refusal_trend.png` | single column, 3.5 in | MEASURED | Schengen applications and refusals, Bangladesh, 2023-2024 |
| 03 | `out/fig03_rcrag_loops.png` | double column, 7.16 in | ILLUSTRATIVE | RC-RAG three-loop architecture |
| 04 | `out/fig04_event_fanout.png` | single column, 3.5 in | ILLUSTRATIVE | portal.changed event fan-out to four consumers |
| 05 | `out/fig05_promotion_gates.png` | double column, 7.16 in | ILLUSTRATIVE | Adapter promotion, two gates in series |
| 06 | `out/fig06_latency_measured.png` | single column, 3.5 in | MEASURED | Measured response latency, development machine |
| 07 | `out/fig07_agent_map.png` | double column, 7.16 in | ILLUSTRATIVE | Agent to Gemma-capability map |
| 08 | `out/fig08_timescale_separation.png` | double column, 7.16 in | ILLUSTRATIVE | Separation of duties by timescale |
| 09 | `out/fig09_data_flow.png` | single column, 3.5 in | ILLUSTRATIVE | Data flow: question to cited answer |
| 10 | `out/fig10_human_in_loop.png` | single column, 3.5 in | ILLUSTRATIVE | Three human-in-the-loop decision points |
| 11 | `out/fig11_cost_model.png` | single column, 3.5 in | ILLUSTRATIVE | Illustrative cost model: fixed VM versus per-token API |

## Captions

### 01. `fig01_problem_scale.png` — MEASURED, double column, 7.16 in

Four verified statistics on the market Digonto addresses. Top left: 52,799 Bangladeshi students studied abroad in 2023, across 55 countries. Top right: families paid 667.77 million US dollars for overseas education in FY25, a record for a single year, across 109,290 banking transactions. Bottom left: Schengen applications from Bangladesh in 2024 and how many were refused, both as compiled by registered with the sector association; the rest hold no specialised supervision. Bottom right: the Schengen visa refusal rate for Bangladeshi applicants rose from 43.3 percent in 2023 to 54.9 percent in 2024. MEASURED: every number is transcribed unchanged from README.md, which cites the original sources (UNESCO, Bangladesh Bank, the consultancy sector association, and Schengen visa statistics); none is derived or estimated for this figure.

### 02. `fig02_refusal_trend.png` — MEASURED, single column, 3.5 in

Bangladeshi Schengen visa applications (blue) and refusals (orange), 2023 and 2024, with the refusal rate labelled directly above each year. 2023: 41,317 applications, 17,015 refused. 2024: 39,345 applications, 20,957 refused. MEASURED, from README.md's cited Schengen visa statistics. Note: the refusal rate is quoted exactly as officially reported by the European Commission (43.3 percent, 54.9 percent); dividing the refused count shown here by the application count shown here gives a slightly lower figure (about 41 percent and 53 percent), most likely because the official rate uses a different denominator or reporting period than the two headline counts. Both figures are reproduced unchanged from the source rather than reconciled by us. Takeaway: the refusal rate rose by more than 12 percentage points in a single year.

### 03. `fig03_rcrag_loops.png` — ILLUSTRATIVE, double column, 7.16 in

Schematic of Recurrent Continual RAG (RC-RAG): three loops of different speed around one served Gemma 4 E2B model. Fast loop (blue, per query): a semantic cache check, then hybrid dense and BM25 retrieval, schema-constrained generation, and a cited answer or an explicit refusal. Recurrent loop (orange, scheduled crawling): portals are hash-checked, changed pages are diffed at passage level, and only the diffs are re-embedded into a new store version. Continual loop (green, every 2 to 4 weeks): refusals and corrections train a QLoRA adapter that must pass a frozen benchmark and a human reviewer, in series, before it replaces the running model. The versioned knowledge store (grey) is the shared state the fast loop reads and the recurrent loop writes. ILLUSTRATIVE: this is an architecture schematic, not a data plot; box shapes and positions carry no quantitative meaning.

### 04. `fig04_event_fanout.png` — ILLUSTRATIVE, single column, 3.5 in

The single event portal.changed reaches four independent consumers: the knowledge store update, semantic cache invalidation, timeline re-planning for every affected student, and a Bangla alert quoting and citing the changed passage. This one-to-many fan-out is the specific reason the backend is event-driven on Redis Streams rather than request-driven. ILLUSTRATIVE: an architecture schematic, not a data plot.

### 05. `fig05_promotion_gates.png` — ILLUSTRATIVE, double column, 7.16 in

A trained QLoRA adapter is promoted only after two gates in series. Gate 1 is a frozen 200-question Bangla benchmark: the adapter must pass with no metric regressing by more than one point. Gate 2 is a human reviewer. Failing either gate rolls the adapter back; only an adapter that passes both is hot-swapped into the running model. ILLUSTRATIVE: a protocol schematic, not a data plot; no benchmark scores are shown because none have been measured yet.

### 06. `fig06_latency_measured.png` — MEASURED, single column, 3.5 in

Wall-clock latency on the development machine, log scale. A cold model load costs 24,318 ms. With the model resident, a tool call takes 1,163 ms, a refusal 1,908 ms, and a full grounded answer with retrieval 5,128 ms. Single runs on one development machine, not repeated trials and not the production virtual machine, so these are an order of magnitude indication rather than a benchmark. MEASURED (development machine only). Takeaway: keeping the model resident turns a 24.3 second cold start into a 1.2 second warm call.

### 07. `fig07_agent_map.png` — ILLUSTRATIVE, double column, 7.16 in

Which native Gemma 4 E2B capability each of the seven agents uses: tools (function calling), vision, audio, and thinking mode. Filled, coloured cell with 'Yes' means the capability is used; empty white cell means it is not. All seven agents use tool calling. Vision is used by Prohori, Bicharok, and Dalil, exactly where agents.md specifies an extract_fields call (a Gemma vision pass over an uploaded document). No agent uses native tool calling, and none uses audio, because no speech-to-text service is deployed. Thinking mode is shown on only where agents.md states it explicitly, Khoji's eligibility scoring and Shonchari's answer scoring; it is off by the same source's stated default everywhere else (Porter's change triage is explicitly off). ILLUSTRATIVE: a design map read from the agent specification in agents.md, not a runtime measurement of calls actually made.

### 08. `fig08_timescale_separation.png` — ILLUSTRATIVE, double column, 7.16 in

What changes in each of the three RC-RAG loops, and the failure each one specifically prevents. Fast loop (blue, per query): nothing is stored; the schema forces a refusal rather than an unsupported answer. Recurrent loop (orange, hours): the versioned knowledge store is updated so students never act on a stale requirement. Continual loop (green, 2 to 4 weeks): the model's own weights improve through a gated adapter, so language and reasoning quality does not stagnate, without an ungated regression reaching students. ILLUSTRATIVE: a conceptual summary of the design, not a measurement.

### 09. `fig09_data_flow.png` — ILLUSTRATIVE, single column, 3.5 in

The fast-loop pipeline from a student's question to a cited answer: normalise, check the semantic cache, hybrid retrieval (dense plus BM25) on a cache miss, generate with a schema-constrained call to Gemma 4 E2B, and either an answer with a citation or an explicit refusal when no retrieved passage supports a claim. A cache hit short-circuits straight to a previously cached, still-current cited answer. ILLUSTRATIVE: a pipeline schematic, not a data plot.

### 10. `fig10_human_in_loop.png` — ILLUSTRATIVE, single column, 3.5 in

The three points in Digonto where a human decides rather than the model. Alert release: a portal change classified below 0.7 confidence reaches a human review queue before any student is alerted, so a false 'your deadline moved' notice never reaches five hundred students unsupervised. Answer correction: a corrected answer is recorded by a human, not inferred from an implicit signal such as a thumbs-down, because that correction is the highest-value item in the training buffer. Adapter promotion: gate 2 is a human reviewer, and no adapter reaches students on the automatic benchmark alone. ILLUSTRATIVE: a governance schematic, not a data plot.

### 11. `fig11_cost_model.png` — ILLUSTRATIVE, single column, 3.5 in

Illustrative cost comparison, not measured billing data. The blue line assumes a flat, hypothetical 80 US dollar per month cost for one self-hosted virtual machine, independent of how many students use it. The orange line assumes a hypothetical per-token hosted-API alternative, at roughly 0.03 US dollars per active student per month (illustrative: about 3,000 tokens and 20 questions per student monthly at an illustrative 0.50 US dollars per million tokens). Under these assumptions the two cost curves cross at roughly 2,700 students; past that point self-hosting a fixed VM is cheaper than paying per token, and the gap widens as usage grows. ILLUSTRATIVE: all costs, token counts, and usage rates are assumed for illustration, not sourced from a metered bill; real API pricing, real VM pricing, and real usage patterns will differ.


# Digonto: Recurrent Continual Retrieval-Augmented Generation for Bangla Study Abroad Guidance on a 2.3B Open Model

> **This file is a readable mirror.** The canonical source is
> `docs/paper/digonto.tex` (IEEEtran, drag-and-drop Overleaf package). If the two
> disagree, the LaTeX is correct. Edit the LaTeX first, then update this mirror in
> the same pass, so the title, the numbers, and the contribution count never fall
> out of step.
>
> Body length: about 3,800 words, excluding abstract, figures, tables, and
> references. Grew from an earlier 3,200-word draft when the verified test
> results, the measured latency figures, the streaming-under-a-schema
> mechanism, and the corrected agent-architecture description were added;
> trimmed elsewhere to stay as close to 3,000 as the added, required content
> allowed. 36 references, every DOI resolved and every URL fetched on
> 26 July 2026.

**Authors:** Author One, Author Two, Author Three
Department of Computer Science and Engineering, Institution Name, Dhaka, Bangladesh

---

## Abstract

Bangladeshi students sent 667.77 million US dollars abroad for education in
fiscal year 2025, and UNESCO counted 52,799 studying overseas in 2023. Most
applicants rely on private consultancy firms, because official admission and visa
information is published in complex English and is revised without notice.
Hundreds of such firms operate, and no mandatory registration system exists
for this specific sector. We present Digonto, a free navigator that answers
study abroad
questions in Bangla, monitors official portals for changes, and acts for the
student through seven autonomous agents. Digonto introduces Recurrent Continual
Retrieval-Augmented Generation, or RC-RAG. RC-RAG places three loops of different
speed around one small open model, Gemma 4 E2B, hosted on a single low cost
virtual machine. A fast loop answers a question and cites a stored copy of the
source page. A recurrent loop crawls portals on a schedule and republishes a
versioned knowledge store. A continual loop trains low rank adapters on
accumulated corrections, mixes in rehearsal data to limit forgetting, and
promotes an adapter only after it passes a fixed benchmark. We report the design,
the promotion protocol, and the evaluation plan, and we mark every value that is
a target rather than a measurement.

**Index Terms:** retrieval-augmented generation, continual learning, small
language models, Bangla language processing, autonomous agents, education access.

## I. Introduction

Studying abroad is one of the largest financial decisions a Bangladeshi family
makes. Payments from Bangladesh for overseas education reached 667.77 million US
dollars in fiscal year 2025, sent through 109,290 banking transactions, and that
is a record for a single year [1]. UNESCO counted 52,799 Bangladeshi students in
tertiary education abroad in 2023, spread across 55 destination countries,
roughly three times the number fifteen years earlier [2].

The information these students need is already public. Embassy pages list
document requirements. University portals list deadlines. Scholarship boards list
eligibility rules. The difficulty is that this material is written in dense
administrative English, is spread across dozens of sites, and is edited without
any announcement.

That gap has produced a large intermediary market: hundreds of consultancy
firms operate in Bangladesh, and no mandatory registration system exists for
overseas education consultancies specifically [3]. A voluntary sector
association, the Foreign Admission and Career Development Consultant
Association of Bangladesh, exists for firms that choose to join it, but
membership is not required to operate, so most run on a general trade licence
with no specialised supervision. Research on commission-based recruitment
agents reports weak oversight and a structural conflict of interest, since the
agent is paid by
the institution while advising the student [6], [7], and an agent's errors
then appear in the applicant's own file. One United States university found
about 65 percent of its applications from India and Bangladesh likely
fraudulent, much of it traced to agent activity [5]. In 2024, Schengen states
received 39,345 visa applications from Bangladesh and refused 20,957 of them, a
refusal rate of 54.90 percent, up from 42.8 percent one year earlier [4], and
every refusal also costs a non-refundable fee. Figure 1 plots these application and refusal counts; the
refusal rate shown there is the source's own reported percentage, not the ratio
of the two bars, because the source computes it over a narrower category of
decisions than the total application count.

Digonto is built on one engineering claim. A small open language model on modest
self-hosted hardware can now read official portals continuously and explain them
in a student's first language, if the system around the model is designed for the
way the information behaves. We use Gemma 4 E2B, an open-weight model with 2.3
billion effective parameters and 5.1 billion total parameters, a context window
of 131,072 tokens, and native support for tool calling, images and audio [8]. It
runs on one commodity virtual machine.

The central difficulty is time. Visa rules change every week, so a fixed
retrieval index becomes wrong, and fine-tuning alone is worse, because facts
stored in weights are costly to revise and earlier ability is lost in the
process [21], [22]. Recent work shows retrieval and parametric adaptation
degrade differently as knowledge drifts continuously, meaning as the facts a
system must report keep changing [27], so neither method alone is sufficient.

Our response is Recurrent Continual Retrieval-Augmented Generation, RC-RAG,
built on a separation of duties by timescale: facts that change daily are held
in a versioned retrieval store a scheduled crawl loop keeps current, and skills
that improve slowly, such as explaining a bank solvency rule in plain Bangla,
are held in the model weights and revised monthly by parameter-efficient
continual learning with rehearsal. Every generated claim
cites a timestamped copy of its source.

This paper makes six contributions. First, we specify RC-RAG, a three-loop
architecture that combines event-driven retrieval freshness with gated continual
model improvement on a single small model. Second, we give an event-driven
backend design that runs RC-RAG on one virtual machine with three explicit
caching layers. Third, we describe seven autonomous agents built on Gemma 4
schema-constrained generation that turn the knowledge store into actions,
including three that address what happens after a refusal, which is where the
published failure rates concentrate. Fourth, we show how streaming combines
with schema-constrained generation so an answer appears token by token while
its citations stay structurally guaranteed, and why a citation naming an
unretrieved passage is always discarded. Fifth, we place a human reviewer at
three specific points and argue for each: alert release, answer correction, and
model promotion. Sixth, we give an evaluation protocol, report what live-model
tests already verify, and state plainly what remains unmeasured.

## II. Background and Related Work

**Retrieval-augmented generation.** RAG conditions a language model on passages
fetched from an external store at answer time [10]. Dense retrieval with learned
embeddings made this accurate [11], graph-based nearest neighbour indexes made it
fast [14], [15], and the older lexical scoring function BM25 remains a strong
complement to dense scores [12]. We combine the two rankings with reciprocal rank
fusion, a method that merges ranked lists without tuning [13]. Later work taught
models to judge their own retrieval and abstain when evidence is missing [16];
Digonto makes abstention a hard rule rather than a preference, because a
confident wrong answer is worse than no answer on a visa question, and
generated text is known to assert unsupported facts [20].

**Continual learning.** A network trained on new data loses earlier ability, an
effect named catastrophic interference [21]. Regularisation methods such as
elastic weight consolidation protect parameters that mattered for earlier tasks
[22], replay methods reuse earlier samples during new training [23], and two
recent surveys organise the field and its evaluation protocols [24], [25].
Recent work schedules replay by a model-centric measure of elapsed training
rather than step counts [26]. Adapter methods change only small added matrices
instead of full weights [28], and quantised training lowers the hardware needed
to fit them [29]. Digonto assembles these known parts into a deployment loop:
replay-mixed adapter training on real user corrections, promoted only
through an automatic gate.

**Agents and tools.** Interleaving reasoning with tool calls is now a standard
agent pattern [30], and models can be trained to decide when a tool is needed
[31]. The Model Context Protocol, an open interface that lets a model discover
and call external tools uniformly, has become a common way to expose those tools,
and its security properties are under active study [32]. Two risks matter for us.
Retrieved web content can carry hidden instructions that override the model's
own, known as indirect prompt injection [33]. Free-form output also breaks
machine consumers, so we constrain generation to a schema [34].

**Small models and Bangla.** Recent analysis argues that small language models
are sufficient for most agent work, because agent subtasks are narrow and
repetitive [9]. This matters twice: self-hosting keeps student passports and
bank statements inside our own deployment, and it keeps the marginal cost of an
answer close to the electricity cost of the machine, which is what makes a
permanently free service possible. Bangla remains under-served in language
technology despite its speaker count, and dedicated Bangla pretraining and large
multilingual translation efforts have both been needed to close part of that gap
[35], [36]. Retrieval quality across Bangla and English is handled by a
multilingual embedding model that produces dense and sparse representations from
one encoder [17].

**What is new here.** Existing tools for Bangladeshi applicants are
consultancy-run portals or static English checklists. We are not aware of a
published system that combines Bangla-first grounded answering, scheduled source
monitoring with versioned citations, and gated continual improvement of the model
itself. The combination, not any single part, is the claim.

## III. Recurrent Continual RAG

Let *K(t)* be the knowledge store at time *t* and let *θ(t)* be the model
parameters. An answer to question *q* is

    a = f( q, R(q, K(t)); θ(t) )

where *R* is retrieval and *f* is constrained generation. Most deployed systems
update *K* and freeze *θ*. RC-RAG updates both, at deliberately different rates:

    ΔK ~ hours,     Δθ ~ weeks

The assignment rule is simple. A fact that a portal can revise tomorrow belongs
in *K*. A skill that no single document contains, such as phrasing a financial
requirement so a first-generation applicant understands it, belongs in *θ*.

**Table I. Separation of duties by timescale in RC-RAG**

| Loop | Period | Changes | Failure it prevents |
| --- | --- | --- | --- |
| Fast | per query | nothing | unsupported claims, repeated compute |
| Recurrent | 6 to 24 hours | knowledge store *K* | stale rules, silent deadline moves |
| Continual | 2 to 4 weeks | parameters *θ* | unclear Bangla, repeated refusals |

**Fast loop.** A student asks in Bangla, in Banglish (Bangla typed in Latin
letters), or in English. The query is embedded with a multilingual encoder [17].
A semantic cache, meaning a cache keyed by meaning rather than by exact text, is
checked first [18]. A cached answer is returned only if it was produced under the
current store version, which prevents serving a superseded rule. Otherwise hybrid
retrieval runs and the fused top passages are passed to the model. Generation is
constrained to a schema [34] whose fields are the Bangla answer, an English
mirror, a citation list, a confidence value, and an optional refusal reason. If
no retrieved passage supports an answer, the schema requires a refusal. Refusal
is a designed result, not an error.

**Streaming under a schema.** The interface shows words as they are produced,
so tokens must reach the client before the model finishes speaking, which
rules out waiting for the whole schema-constrained object to close. Instead the
model streams the object with the schema enforced throughout, and the answer
field is decoded directly out of the still-growing, incomplete JSON text, so
the first word appears as soon as it is written. Citations are read only once
the object fully parses, because a half-parsed citation, naming the wrong
snapshot or truncating a quoted span, is worse than none. For the same reason,
a citation naming a snapshot the retrieval step never returned is discarded
rather than shown, which is what keeps the Truth Ledger guarantee, that every
citation resolves to a passage actually retrieved, true without exception.

**Recurrent loop.** Crawl workers re-fetch each registered portal on its own
schedule, from six hours for embassy pages to daily for scholarship boards. An
unchanged page, detected by content hash, costs nothing further; a changed page
is diffed at passage level, and only changed passages are re-embedded, keeping
the update cost proportional to the change rather than to the corpus. The store
is versioned: a new version publishes atomically by switching a collection
alias, and earlier versions are kept for ninety days, so a student, a bank
officer, or a reviewer can check any claim against the archived page. The
application publishes this archive as the Truth Ledger, meaning a public
record that links each claim to the stored page that supports it.

**Continual loop.** Three kinds of experience accumulate in a replay buffer:
questions the system refused, answers a reviewer corrected, and answers that were
correct but rated unclear. Identifying information is removed before storage, and
only consented interactions are kept. Every two to four weeks the buffer is mixed
one to one with a fixed rehearsal set drawn from the original instruction data,
and a rank 16 adapter is trained with quantised fine-tuning [28], [29]. The
rehearsal mixture is the defence against forgetting [23]. Promotion is gated
twice. The automatic gate requires the candidate to match or exceed the current
model on a frozen 200-question benchmark, with no single metric falling by more
than one point, and a candidate that clears it then waits for a human reviewer.
The two gates catch different failures: the benchmark catches regressions it
was built to measure, and the reviewer catches the ones it was not, such as a
fluent answer that adopts the wrong register for a first-time applicant.
Promotion and rollback are single recorded events, and the previous model tag
is always retained, so reverting takes one operation, not a retraining cycle.

## IV. System Design

Digonto is a web application with an asynchronous Python backend and a single
served model. Every state change emits an event to a durable stream, and workers
consume events idempotently, meaning repeated delivery of the same event cannot
corrupt state. Request handlers stay small: they validate, emit, and reply.

A single portal change traces why this structure was chosen: it updates the
knowledge store, invalidates the affected semantic cache entries, re-plans the
schedule of every student who depends on that portal, and sends a Bangla alert
quoting the changed sentence, none of which belongs inside an HTTP request.

**Caching.** Three layers control cost and latency: ordinary HTTP caching for
static assets and archived page reads, a semantic cache that serves repeated
questions without recomputation, since visa questions repeat often because
applicants share a small set of concerns, and a model kept resident with a
stable prompt prefix, so the shared instructions and tool definitions are
encoded once rather than on every request.

**Agents.** Each of the seven agents asks Gemma 4 for one schema-constrained
structured reply, the same mechanism the fast loop uses, with one automatic
repair attempt if a reply fails to validate. Porter watches portal-change
events, classifies each change into an enumerated type, discards wording-only
edits, and alerts affected students with the changed passage quoted and cited.
Prohori audits a student's uploaded documents against the cited checklist of
each target institution and reports missing items, documents expiring before
the projected travel date, and fields that disagree across documents, such as a
name spelled differently from the passport, found by deterministic checks a
reviewer can reproduce and explained in Bangla by the model. Khoji matches the
student profile against a funding index and returns a ranked list in which
every rank carries a per-criterion reason, plus a complete budget including the
bank balance the embassy actually requires. Shonchari runs mock visa interviews
conditioned on the student's own file and reports contradictions between
spoken answers and submitted documents, because consistency is what a visa
officer checks.

Three further agents address failures that occur after a first attempt, which is
where the published refusal statistics concentrate. Bicharok reads a refusal
letter with the model's vision capability, maps each stated ground to the rule it
refers to, and reports in Bangla whether that ground is remediable and what remedy
applies. With more than half of Bangladeshi Schengen applications refused in 2024
[4], the second attempt matters as much as the first, and a student who cannot
read the refusal cannot correct it. Lekhok compares a statement of purpose against
the student's own documents and reports contradictions, unsupported claims, and
passages too vague to help. Dalil reads a consultancy contract and reports clause
by clause which terms are ordinary and which transfer risk onto the student, with
a fair alternative for each.

Two controls bound every agent regardless of task: no agent exposes a deletion
tool, and retrieved portal text is treated as untrusted input, wrapped in a
data-only frame, with tool calling disabled during grounded answering, which
limits indirect prompt injection [33]. These seven calls do not use the
model's separate native tool-calling capability, confirmed against the live
model with an enumerated argument; that capability is instead exposed through
three custom Model Context Protocol servers [32], letting any external MCP
client call the same repositories and services the product itself uses. An
audited, multi-step tool-calling runtime with a per-call step limit is defined
in the event schema but not yet wired to the agents: today each call is a
single schema-constrained request, not an interleaved reasoning-and-acting loop
[30].

## V. Evaluation Design

The system is at prototype stage. This section separates what is already
verified against the live model from what remains a protocol definition or a
target, so that no reader mistakes a plan for a measurement, and no measurement
is mistaken for a target either.

**Verified today.** Five contract tests and fifteen agent tests run against the
live model, and all twenty pass as of 26 July 2026. The contract tests confirm
the served model reports tool calling, vision, and thinking as capabilities;
emits a native tool call with a valid enumerated argument; refuses when no
passage is given, the single most load-bearing behaviour in the product, rather
than inventing a figure; cites the exact snapshot when a passage is given; and
stays fast on a warm call. The agent tests confirm, among other things, that
Prohori's deterministic checks reproduce identically on repeated input, that
Porter's confidence threshold routes a low-confidence change to review rather
than to students, that every Khoji score carries a reason, that Shonchari's
overall score is the arithmetic mean of its per-turn scores rather than a model
opinion, and that a request carrying document content is refused before it can
reach the remote fallback path.

Figure 5 reports the latency these tests measured on the development machine:
24.3 seconds to cold-load the model (the first call after it has been evicted
from memory), 1.16 seconds for a warm tool call at 46 tokens per second, 1.91
seconds for a warm refusal, and 5.13 seconds for a warm grounded answer with a
citation. These are single runs on the development machine, not the production
virtual machine, reported to show the model behaves as the design assumes
rather than as a claim about production latency.

**Still a plan.** The rest of this section, including Table II below, is a
protocol definition or a target, not a result.

**Benchmark.** We are building a 200-question Bangla benchmark covering five
destination countries and four question families: document requirements,
financial requirements, deadlines, and process order. Each question has a
reference answer grounded in an archived page copy, so correctness stays
checkable even after the live portal changes.

**Metrics.** Groundedness is the fraction of factual claims in an answer that the
cited copy supports, scored by two raters with disagreements resolved by a third.
Refusal correctness measures whether the system refuses exactly when the store
lacks support. Bangla clarity is scored on a five-point rubric by native
speakers. Latency is reported as median and 95th percentile on the production
machine, with and without the semantic cache. Automated retrieval scoring follows
established RAG evaluation practice as a cheap regression check between human
rounds [19], and for the continual loop we report benchmark scores before and
after every promotion to measure forgetting directly.

**Table II. Design targets. None of these is a measured result**

| Quantity | Target | Method |
| --- | --- | --- |
| Groundedness | above 0.90 | two-rater claim check |
| First-token latency, uncached | under 2 s | 8 vCPU, no GPU |
| Semantic cache hit rate | above 35 percent | after one month live |
| Metric loss at promotion | 0 above 1 point | frozen benchmark |

**Field validation.** A pilot with 20 to 30 students from at least three
districts outside Dhaka will compare task completion, such as assembling a
correct document set for a chosen programme, against a checklist-only control
group. Feedback from that pilot enters the replay buffer, so the pilot is part of
the learning system and not only a test of it.

## VI. Responsibility and Sustainability

Digonto reports what official sources state, with citations, and does not give
legal or immigration advice, and the interface says so directly. Where sources
conflict or are silent, the system reports that instead of choosing, because on
a visa-critical question an invented answer can cost a family a year and a
large sum of money, so abstention is an ethical control as much as a technical
one. The interview agent coaches truthful presentation only and refuses
requests to help misrepresent facts, explaining the legal consequences.

Inference is self-hosted, so passports and bank statements never leave the
deployment, and stored documents are encrypted at rest with per-user keys. The
replay buffer holds no document contents, and text entering it passes an
automated removal step for names and identifying numbers. Students can export
or permanently delete their data.

The interface is Bangla-first throughout. Voice input is planned, using the
model's native audio capability, but is not available today: the interview
room accepts typed answers only, because no speech-to-text service is deployed
alongside the model yet. Every generated claim is delivered in both Bangla and
English, so a student can check an official English phrase against the
explanation without leaving the page.

A second role, the reviewer, holds the parts of the system that should not be
automated. A portal change classified below a confidence threshold is not sent
to any student until a reviewer confirms the category, because a false alert
that a deadline moved is worse than a late one. A corrected answer is recorded
by a reviewer rather than inferred from a negative rating, and that correction
is the highest-value item in the replay buffer; no adapter reaches students on
the automatic gate alone. The reviewer role carries no decryption capability
and cannot read document contents, and every reviewer access to student-linked
data is logged and shown to that student.

The service addresses Sustainable Development Goal 4 on equitable access to
higher education, and Goal 10, target 10.7, on orderly and responsible
migration. It is free for students permanently, at an operating cost near one
virtual machine, because the model is small and repeated questions are served
from cache, and institutional revenue rather than student fees funds the
service.

## VII. Limitations

Five limitations are worth stating before a reviewer states them. First, the
verified results in Section V are contract and agent tests on a development
machine, not a benchmark or a field result; the benchmark and the pilot remain
protocol, not findings. Second, the forgetting defence is rehearsal plus two
gates, and the automatic gate is only as reliable as the frozen benchmark, so
leakage of benchmark items into training data must be audited every cycle; the
human gate does not scale, and a reviewer under time pressure approves, so we
report reviewer decision counts and time spent alongside benchmark scores
rather than treat human oversight as free. Third, crawling depends on portal
stability, and a redesign can break a parser silently; the system reports
source silence instead of guessing, but silence is still a degraded state.
Fourth, Bangla clarity rubrics carry rater subjectivity, which two raters and
adjudication reduce but do not remove. Fifth, a model with 2.3 billion
effective parameters is limited when reasoning across many documents at once;
retrieval quality and schema-constrained output compensate, and that limit will
itself be measured in the pilot.

## VIII. Conclusion and Future Work

The study abroad information problem in Bangladesh is an engineering problem with
a social cost. A small open model can address it, given the right system around
it. That system has three parts: a versioned knowledge store that carries
citations and is kept current by a scheduled crawl loop, a gated continual
learning loop that improves the model from real corrections, and agents that act
rather than only answer. Every claim stays checkable and every model update stays
reversible.

Three directions follow. The first is measurement: run the benchmark and the
pilot, and replace every target in this paper with a measured value. The second
is learning: compare rehearsal alone against rehearsal combined with elastic
weight consolidation [22], and test whether model-time replay scheduling [26]
improves refusal stability across long adapter chains. The third is scope: more
destination countries, regional dialect output, and wiring the agents to the
model's native tool-calling capability behind the audited runtime this paper
defines but does not yet use [8], [9]. The design generalises to any setting
where official information is public, changes often, and is written in a
language that excludes the people who depend on it.

## Data and Code Availability

The complete source code is public at https://github.com/MdAhbab/Digonto under
the Apache 2.0 licence. The repository contains the backend, the web client, the
database schema, the seven agent implementations, and the deployment scripts.
The 200-question Bangla benchmark and the evaluation logs behind every number
reported in this paper will be added to the same repository as they are
produced, so that any figure we state as measured can be re-derived from the
published logs. A running deployment is available at https://digonto.ahbab.dev.
Gemma 4 is used under the Apache 2.0 licence.

---

## References

Every entry below was checked against Crossref, the arXiv API, or the publisher
page on 26 July 2026. The authoritative BibTeX is `docs/paper/references.bib`.

[1] Dhaka Tribune, "Bangladeshi students spend $667.77m in FY25 to study overseas," 2025. https://www.dhakatribune.com/business/390989/bd-students-spend-667.77m-in-fy25-to-study

[2] The Daily Star, "Number of students going abroad triples in 15 years despite university boom," 2023. https://www.thedailystar.net/news/bangladesh/news/number-students-going-abroad-triples-15-years-despite-university-boom-3397431

[3] The Financial Express, "Who're monitoring the consultancies sending students abroad?" https://thefinancialexpress.com.bd/education/article/whore-monitoring-the-consultancies-sending-students-abroad

[4] SchengenVisaInfo, "Schengen visa trends from Bangladesh (2014-2024): a statistical overview of visa applications," 2025. https://schengenvisainfo.com/statistics/bangladesh/

[5] Inside Higher Ed, "International admission offices plagued by fraud and deceit," 2024. https://www.insidehighered.com/news/global/international-students-us/2024/01/12/international-admission-offices-plagued-fraud-and

[6] S. Salem, S. A. M. Mofreh, and G. Ponniah, "Perceptions and experiences with international student recruitment agents: from the students' perspective," *Cogent Business & Management*, vol. 12, no. 1, 2025. doi: [10.1080/23311975.2025.2555584](https://doi.org/10.1080/23311975.2025.2555584)

[7] National Association for College Admission Counseling, "Research brief: use of commission-based agents in the recruitment of international students," 2022. https://nacacnet.org/wp-content/uploads/2022/10/nacac_brief_agents.pdf

[8] Gemma Team, Google DeepMind, "Gemma 4 Technical Report," arXiv:2607.02770, 2026. https://arxiv.org/abs/2607.02770

[9] P. Belcak et al., "Small Language Models are the Future of Agentic AI," arXiv:2506.02153, 2025. https://arxiv.org/abs/2506.02153

[10] P. Lewis et al., "Retrieval-augmented generation for knowledge-intensive NLP tasks," NeurIPS, 2020. arXiv:2005.11401. https://arxiv.org/abs/2005.11401

[11] V. Karpukhin et al., "Dense passage retrieval for open-domain question answering," EMNLP, pp. 6769-6781, 2020. doi: [10.18653/v1/2020.emnlp-main.550](https://doi.org/10.18653/v1/2020.emnlp-main.550)

[12] S. Robertson and H. Zaragoza, "The probabilistic relevance framework: BM25 and beyond," *Foundations and Trends in Information Retrieval*, vol. 3, no. 4, pp. 333-389, 2009. doi: [10.1561/1500000019](https://doi.org/10.1561/1500000019)

[13] G. V. Cormack, C. L. A. Clarke, and S. Buettcher, "Reciprocal rank fusion outperforms Condorcet and individual rank learning methods," SIGIR, pp. 758-759, 2009. doi: [10.1145/1571941.1572114](https://doi.org/10.1145/1571941.1572114)

[14] Y. A. Malkov and D. A. Yashunin, "Efficient and robust approximate nearest neighbor search using hierarchical navigable small world graphs," *IEEE TPAMI*, vol. 42, no. 4, pp. 824-836, 2020. doi: [10.1109/TPAMI.2018.2889473](https://doi.org/10.1109/TPAMI.2018.2889473)

[15] J. Johnson, M. Douze, and H. Jégou, "Billion-scale similarity search with GPUs," *IEEE Transactions on Big Data*, vol. 7, no. 3, pp. 535-547, 2021. doi: [10.1109/TBDATA.2019.2921572](https://doi.org/10.1109/TBDATA.2019.2921572)

[16] A. Asai, Z. Wu, Y. Wang, A. Sil, and H. Hajishirzi, "Self-RAG: Learning to retrieve, generate, and critique through self-reflection," ICLR, 2024. arXiv:2310.11511. https://arxiv.org/abs/2310.11511

[17] J. Chen, S. Xiao, P. Zhang, K. Luo, D. Lian, and Z. Liu, "M3-Embedding: Multi-linguality, multi-functionality, multi-granularity text embeddings through self-knowledge distillation," Findings of ACL, pp. 2318-2335, 2024. doi: [10.18653/v1/2024.findings-acl.137](https://doi.org/10.18653/v1/2024.findings-acl.137)

[18] F. Bang, "GPTCache: An open-source semantic cache for LLM applications enabling faster answers and cost savings," NLP-OSS, pp. 212-218, 2023. doi: [10.18653/v1/2023.nlposs-1.24](https://doi.org/10.18653/v1/2023.nlposs-1.24)

[19] S. Es, J. James, L. Espinosa Anke, and S. Schockaert, "RAGAs: Automated evaluation of retrieval augmented generation," EACL System Demonstrations, pp. 150-158, 2024. doi: [10.18653/v1/2024.eacl-demo.16](https://doi.org/10.18653/v1/2024.eacl-demo.16)

[20] Z. Ji et al., "Survey of hallucination in natural language generation," *ACM Computing Surveys*, vol. 55, no. 12, pp. 1-38, 2023. doi: [10.1145/3571730](https://doi.org/10.1145/3571730)

[21] M. McCloskey and N. J. Cohen, "Catastrophic interference in connectionist networks: the sequential learning problem," *Psychology of Learning and Motivation*, vol. 24, pp. 109-165, 1989. doi: [10.1016/S0079-7421(08)60536-8](https://doi.org/10.1016/S0079-7421(08)60536-8)

[22] J. Kirkpatrick et al., "Overcoming catastrophic forgetting in neural networks," *PNAS*, vol. 114, no. 13, pp. 3521-3526, 2017. doi: [10.1073/pnas.1611835114](https://doi.org/10.1073/pnas.1611835114)

[23] D. Rolnick, A. Ahuja, J. Schwarz, T. Lillicrap, and G. Wayne, "Experience replay for continual learning," NeurIPS, 2019. arXiv:1811.11682. https://arxiv.org/abs/1811.11682

[24] M. De Lange et al., "A continual learning survey: defying forgetting in classification tasks," *IEEE TPAMI*, vol. 44, no. 7, pp. 3366-3385, 2022. doi: [10.1109/TPAMI.2021.3057446](https://doi.org/10.1109/TPAMI.2021.3057446)

[25] L. Wang, X. Zhang, H. Su, and J. Zhu, "A comprehensive survey of continual learning: theory, method and application," *IEEE TPAMI*, vol. 46, no. 8, pp. 5362-5383, 2024. doi: [10.1109/TPAMI.2024.3367329](https://doi.org/10.1109/TPAMI.2024.3367329)

[26] "FOREVER: Forgetting curve-inspired memory replay for language model continual learning," ACL, 2026. arXiv:2601.03938. https://arxiv.org/abs/2601.03938

[27] H. Liu, L. Cao, and Y. Li, "RAG or learning? Understanding the limits of LLM adaptation under continuous knowledge drift in the real world," Findings of ACL, 2026. arXiv:2604.05096. https://arxiv.org/abs/2604.05096

[28] E. J. Hu et al., "LoRA: Low-rank adaptation of large language models," ICLR, 2022. arXiv:2106.09685. https://arxiv.org/abs/2106.09685

[29] T. Dettmers, A. Pagnoni, A. Holtzman, and L. Zettlemoyer, "QLoRA: Efficient finetuning of quantized LLMs," NeurIPS, 2023. arXiv:2305.14314. https://arxiv.org/abs/2305.14314

[30] S. Yao et al., "ReAct: Synergizing reasoning and acting in language models," ICLR, 2023. arXiv:2210.03629. https://arxiv.org/abs/2210.03629

[31] T. Schick et al., "Toolformer: Language models can teach themselves to use tools," 2023. arXiv:2302.04761. https://arxiv.org/abs/2302.04761

[32] X. Hou, Y. Zhao, S. Wang, and H. Wang, "Model Context Protocol (MCP): Landscape, security threats, and future research directions," 2025. arXiv:2503.23278. https://arxiv.org/abs/2503.23278

[33] K. Greshake, S. Abdelnabi, S. Mishra, C. Endres, T. Holz, and M. Fritz, "Not what you've signed up for: compromising real-world LLM-integrated applications with indirect prompt injection," ACM AISec, pp. 79-90, 2023. doi: [10.1145/3605764.3623985](https://doi.org/10.1145/3605764.3623985)

[34] B. T. Willard and R. Louf, "Efficient guided generation for large language models," 2023. arXiv:2307.09702. https://arxiv.org/abs/2307.09702

[35] A. Bhattacharjee et al., "BanglaBERT: Language model pretraining and benchmarks for low-resource language understanding evaluation in Bangla," Findings of NAACL, pp. 1318-1327, 2022. doi: [10.18653/v1/2022.findings-naacl.98](https://doi.org/10.18653/v1/2022.findings-naacl.98)

[36] NLLB Team et al., "Scaling neural machine translation to 200 languages," *Nature*, vol. 630, pp. 841-846, 2024. doi: [10.1038/s41586-024-07335-x](https://doi.org/10.1038/s41586-024-07335-x)

---

## Figure plan (project figure specification)

- **Fig. 1.** Schengen visa applications and refusals from Bangladesh, 2023
  and 2024, reproduced from SchengenVisaInfo. PNG, generated by script,
  single column. Caption states the refusal rate is the source's own reported
  percentage, not the ratio of the two bars shown, and that the figure is
  reproduced from the cited source, not independently measured.
- **Fig. 2.** RC-RAG three-loop architecture, schematic, 7.16 in double column. Blue #2563EB for the fast loop, orange #E8710A for the recurrent loop, green #059669 for the continual loop, grey #6B7280 for storage. Caption marks it as schematic. Drawn in TikZ inside the LaTeX.
- **Fig. 3.** Adapter promotion protocol: buffer, rehearsal mix, training, gate, promote or roll back. Single column, 3.5 in. TikZ.
- **Fig. 4.** Delivery of one `portal.changed` event to four consumers. Single column. TikZ.
- **Fig. 5.** Measured response latency on the development machine, log scale:
  cold model load, warm tool call, warm refusal, warm grounded answer. PNG,
  generated by script from the same numbers `backend/tests/test_model_contracts.py`
  records. The one figure in the paper built from a real measurement rather
  than a target. Caption states these are single runs, not the production
  virtual machine.

A sixth figure, mapping each agent to the Gemma capability it uses, was
prepared but is deliberately not included: its "Tools" and "Audio" columns
would repeat the tool-calling and voice-input claims this revision corrects
(no agent currently uses native tool calling, and Shonchari's voice mode is
not implemented, since no speech-to-text service is deployed). Adding it
would contradict Sections IV and VI. A seventh figure, benchmark scores
before and after each adapter promotion, remains absent until that data
exists, per the original plan.

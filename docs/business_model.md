# Digonto Business Model and Responsibility Plan

Digonto is free for students, permanently. This document explains how that stays true, and it consolidates the project's SDG alignment, engineering ethics, human-centred design commitments, and security assurances.

## 1. The economics of free

The cost side is deliberately small. Gemma 4 E2B self-hosted on one VM means inference cost is the VM bill, not a per-token API bill. The semantic cache serves the most repeated questions without recomputation. Diff-based crawling re-embeds only changed passages. Choosing SQLite over a client-server database, and an encrypted filesystem volume over an object-storage container, removes two long-running services and their memory reservations, which leaves more of the VM's RAM for the model. Realistic steady-state cost: one 8-vCPU/16 GB VM plus storage and off-VM backup, on the order of 60 to 120 US dollars per month at current cloud pricing, largely independent of user count until concurrency grows.

The cost floor matters for the promise. Because the marginal cost of an answer is close to the electricity cost of a machine we already rent, "free for students" does not depend on continued fundraising. If every revenue line failed, the service would still be affordable to keep running.

The revenue side never touches students:

1. **University and college partnerships.** Verified institutional profiles and direct application links. Institutions pay for verified presence; ranking and answers are never influenced by payment, and paid placement is always labelled. This is the primary long-term line.
2. **Verified-consultancy certification.** The roughly 400 registered consultancies have a market interest in separating themselves from the unregistered majority. Digonto offers a certification listing tied to published conduct standards and student reviews. This converts the project's main adversary into a customer while raising sector standards.
3. **Institutional API.** Banks (student file processing), scholarship foundations, and university international offices can license the portal-monitoring and checklist API for their own operations.
4. **Grants and CSR.** Education access aligns with development funding (World Bank, British Council, development agencies) and telecom CSR programmes; grant funding is treated as acceleration, not as the survival plan.

Sequencing: months 0 to 6 run on competition momentum and grants while the pilot produces evidence; months 6 to 18 add partnerships and certification; the API follows once monitoring coverage is broad enough to sell.

**What is never sold:** student data, answer placement, or referral of students to any consultancy. These are stated publicly so the commitment is checkable.

## 2. SDG alignment

- **SDG 4 (Quality Education), target 4.3 and 4.b:** equal access to affordable tertiary education and visibility of scholarships. Digonto's scholarship agent directly serves 4.b's intent by making existing funding findable.
- **SDG 10 (Reduced Inequalities), target 10.7:** orderly, safe, and responsible migration. Cited, accurate visa information reduces exploitation by unregistered intermediaries and reduces rejection-by-misinformation.
- **SDG 8 (Decent Work and Economic Growth):** reducing fraudulent intermediary extraction keeps family savings in productive use, and certification pressure formalises a currently informal sector.
- **SDG 16 (Institutions), target 16.10:** public access to information. The Truth Ledger is an access-to-information mechanism: it republishes official information verifiably, with provenance.

## 3. Engineering ethics

The commitments follow the spirit of the IEEE and ACM codes of ethics: hold paramount the safety and welfare of the public, be honest about capabilities, and avoid conflicts of interest.

1. **Information, not advice.** Digonto reports what official sources state, cited. It does not advise on legal strategy and says so in the interface.
2. **Refusal over plausibility.** On visa-critical questions the system refuses when evidence is missing. A wrong answer can cost a family a year and a large sum; the refusal contract is enforced in the output schema, not just in policy text.
3. **Truthfulness boundary.** The interview agent coaches honest presentation and refuses requests to fabricate ties, funds, or history, explaining the legal consequences of visa fraud.
4. **No conflict of interest.** Revenue sources cannot influence answers or rankings; paid content is labelled; the certification programme publishes its criteria.
5. **Honest measurement.** Design targets are labelled as targets until measured; measured results replace them and are reported even when unflattering.

## 4. Human-centred design

The design starts from real usage constraints in Bangladesh, not from a persona template. Bangla is the first language of the interface, with Banglish input accepted and voice input for users more comfortable speaking than typing. Connections in Bangladesh are often slow rather than absent, so the design target is a usable first paint on a mid-range Android over a congested mobile network: first load is budgeted under 300 KB of compressed JavaScript, fonts are self-hosted and subset so no third-party request sits on the critical path, and every answer streams token by token so the student sees progress rather than a spinner. Literacy range is respected through plain-language explanation patterns (every technical term explained at first use, in Bangla). The pilot with students from at least three districts outside Dhaka exists to test these assumptions against reality, and pilot feedback flows into the replay buffer, so lived experience literally trains the system.

## 5. The reviewer role, and what it costs

Digonto has two kinds of user. Students use the product. Reviewers hold the three decisions that should not be automated, and the reason each is human is specific rather than decorative.

A portal change that the model classified with low confidence reaches no student until a reviewer confirms the category. The asymmetry justifies the cost: a false alert telling five hundred students their deadline moved is far more damaging than an alert that arrives six hours late. A corrected answer is written by a reviewer rather than inferred from a negative rating, because a thumbs-down says something is wrong and not what the right answer was, and that correction is the highest-value item in the training buffer. No model adapter reaches students on the automatic benchmark alone, because a benchmark catches the regressions it was built to measure and not the ones it was not.

Reviewers cannot read student documents. They hold no key material, and there is no code path from a reviewer route to vault contents, so this is enforced by the absence of the capability rather than by a permission flag. Every reviewer access to student-linked data is logged and shown to that student in their own account. Every suspension or ban requires a bilingual written reason, because that reason is shown to the person it affects.

The honest cost: human review does not scale linearly with users, and a reviewer under time pressure approves. The mitigation is to keep the queue small by construction. Only low-confidence classifications enter it, and the confidence threshold is tuned against reviewer capacity rather than set once. If the queue grows faster than it is cleared, the correct response is to raise crawl quality, not to raise the threshold.

## 6. Security assurances

- Self-hosted inference: passports, bank statements, and transcripts never leave the deployment VM; no third-party model API receives vault content.
- Vault files encrypted at rest (AES-256-GCM, per-user data keys under a wrapped master key); TLS 1.3 in transit; signed, expiring upload URLs.
- Data minimisation: the learning buffer stores no document contents; text entering it passes automated PII removal and a consent gate.
- User control: full export and hard delete, with deletion cascading to file storage and buffer rows.
- Prompt-injection defence: crawled portal text is treated as untrusted, wrapped in a data-only frame, with tool calling disabled during grounded answering.
- Agent containment: per-agent tool allow-lists enforced by the runtime; no deletion tools exist for agents; every tool call is audit-logged.
- Operational: nightly off-VM backups, model rollback tags, dead-letter queues with alerts, and rate limiting per user and IP.

## 7. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Portal redesign breaks crawlers | Hash-and-diff design fails loud ("source silent"), never guesses; parser fixtures per portal |
| Consultancy sector hostility | Certification converts registered firms into stakeholders; Truth Ledger makes disputes checkable |
| Wrong answer harms a student | Refusal contract, citations on every claim, human review queue for low-confidence classifications |
| Funding shortfall | Cost floor is one VM; the service degrades in coverage, not in existence |
| Regulation of AI information services | Information-with-provenance posture, no advice claims, early engagement with UGC and FACD-CAB |
| Reviewer queue grows faster than it is cleared | Confidence threshold tuned against reviewer capacity; the response is better crawl quality, never a higher threshold that silently ships unreviewed alerts |
| Model provider terms change | Gemma 4 is Apache 2.0 and the weights are held locally, so the deployment continues regardless of any hosted service |

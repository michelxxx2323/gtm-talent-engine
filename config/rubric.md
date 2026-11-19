# Company fit rubric (v2, 2026-11-08)

Question the rubric answers: **is this company a good employer target for
Michel?** The exact texts both evaluators receive are in
[`rubric.yaml`](rubric.yaml); this page explains them.

## Cheap filters (phase 1, no AI, no credits)

| Filter | Rule |
|---|---|
| Has a website | a domain we can research |
| Duplicate | same root domain as another candidate (sources merged, signals kept) |
| Region | HQ in the US, Canada, UK or Europe → `primary`; Australia, NZ, Israel, LatAm, UAE or unknown → `secondary` (kept, -10 points); others → out |
| Language | if the directory lists languages, English must be one |
| Obvious non-employer | course, bootcamp, product or job board with no agency wording |

## Gates → Out

- **Operating**: Out only on clear evidence the company closed. A parked or
  for-sale domain is a fixed rule in code (no model call).
- **Service business**: sells client service work in Clay, GTM engineering,
  outbound, RevOps or AI automation (not a product, data vendor or course).

## Caps → at most C

- **Has a team** beyond one person. A solo shop stays C, not Out: Michel would
  work for one.
- **Recent activity** (dated evidence in the last 12 months). A site that
  blocks bots or renders only with JavaScript is not evidence of inactivity; a
  site that is down is.
- **Remote possible** (v2.2): someone could work for the company fully
  remotely from Brazil. Capped only on evidence of on-site or hybrid office
  work, or of hiring in one country only; no information counts as yes. This
  restores Michel's hard rule (no on-site or hybrid roles outside Brazil),
  which v2 lost when remote openness became team geography.

## Score (0-100)

| Criterion | Weight | Full marks |
|---|---|---|
| Clay depth | 20 | Elite Studio / Studio tier, ex-Clay founders, Clay-certified team |
| Structure | 20 | well-known, established agency (brand, recognition, or 50+ people with clear structure) |
| Team geography | 20 | team in North America / Europe and already employs people in Brazil |
| Overlap with the four fronts | 10 | 3-4 of GTM engineering, RevOps, AI automation, campaign ops are core |
| Reachability | 10 | founder well known in the industry or writes often about GTM |
| Hiring and growth | 20 | open GTM/ops role now |

**Bands:** A ≥ 70 (wave 1), B ≥ 50 (wave 2), C below (keep, do not contact).

## Calibration log

| Version | Labels | Claude exact / contact-or-not | Jev exact / contact-or-not |
|---|---|---|---|
| v1 (2026-11-07) | Michel, pilot of 20 | 7/20 · 13/20 | 5/20 · 12/20 |
| v2 (2026-11-08) | same 20 (in-sample) | 15/20 · 18/20 | 14/20 · 18/20 |
| v2.1 (2026-11-08), hiring back to 20 | same 20 (in-sample) | 15/20 · 17/20 | 14/20 · 17/20 |
| v2.2 (2026-11-08), + remote cap | same 20 (unchanged) | 15/20 · 17/20 | 14/20 · 17/20 |
| v2.2, blind sample of 25 new companies | Claude vs Jev (no human labels) | same band 18/25 | |

v1 → v2, from Michel's reasons: size stopped penalizing big agencies
(structured and known is a plus); remote openness became team geography,
scored from Clay headcount by country; solo or undated companies are capped at C instead of
Out. v2.1 keeps hiring at 20: Michel's reasons never mentioned it because he had
no hiring data in his own search, not because it matters less, so labels made
without that data cannot lower its weight. v2 was tuned on the same 20, so its
numbers are optimistic until checked on companies Michel has not labeled yet.

Known gaps: team location is rarely on websites (needs Clay people data), "founder well known in the
industry" is not in the dossier, and Michel rates large, well-known agencies that do not use Clay higher than the rubric does.

# gtm.world: ground-truth world (synthetic)

`generate_world(seed=42, params=None) -> World` builds the fictional ground truth every simulator degrades: about 40 companies
(`co_001`...), 2-3 contacts each, scripted enquiries with labels, scripted replies, web pages and provider parameters.
Same seed gives byte-identical `World.model_dump_json()`. `params={"n_companies": N}` (minimum 24) scales it (used by accuracy tests).
All names are fictional; every domain/email ends in `.example`. Also exports `covers`, `is_correct`, `unit`, `wrong_value` (deterministic noise
shared with the provider sims, in `degrade.py`).

## Golden thread (seed 42)
| Item | Value |
|---|---|
| Enquiry | `enq_001`, genuine, expected band `high`, at offset 0 |
| Company | `co_001` Brightwater Logistics, `brightwater-logistics.example`, alias `brightwater-group.example`, 850 employees, 50-250M, EMEA/UK, ICP fit, `service_need="data engineering"`, stack Snowflake/Airflow/AWS/Python/Kafka, hiring Senior Data Engineer + ML Engineer |
| Contact | `ct_001` Marta Lindqvist, VP Data and Analytics (vp), `marta.lindqvist@brightwater-logistics.example`; also `ct_002` Daniel Okafor (manager), `ct_003` Aisha Brandt (CTO) |
| Replies | `rpl_001` interested (+5400 s), `rpl_002` meeting_booked (+90000 s) |
| Coverage | `co_001` and its contacts are covered by all three providers (`degrade.FORCED_COVERAGE`); field accuracy is still hash-degraded |
| Web | `https://brightwater-logistics.example/{about,news/investment,careers}` (clean) |

## Other scripted cases (seed 42 ids)
enq_002 genuine medium + enq_003 exact duplicate (same email); enq_004 genuine high + enq_005 fuzzy duplicate (typo in first name, alias domain);
enq_006 subsidiary contact writing under the parent's name; enq_007 shared mailbox `info@`; enq_008 vendor; enq_009 recruiter; enq_010 spam;
enq_011 student (low); enq_012 tiny company (low); enq_013 prompt injection (`injection=True`); enq_014 partial provider coverage (provider_a knows it, provider_b does not);
enq_015 genuine medium. Replies cover every kind: interested, meeting_booked (enq_001), not_now (002), question (004), ooo (006), bounce (007),
referral (012), unsubscribe (014), not_interested (015). Two web pages have `contains_injection=True` (a company news page and an industry digest).
Provider parameters: A coverage .90 / accuracy .80 / 540 d / cost 1; B .45 / .95 / 90 d / cost 10 / slow; C .60 / .85 / 60 d / cost 5 (tech_stack, hiring_signals).
`duplicate_company_pairs`: two (original, duplicate record) company pairs; 4 subsidiaries have `parent_id`.

## Tests
`cd backend && python -m pytest tests/world -q`

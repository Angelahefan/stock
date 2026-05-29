# ACY × DATAP.AI — TradingCup AI Trade Council Pilot (MOVED)

**Date:** 2026-05-28
**Status:** Stub — full doc lives in `datapai-cfd-be`

This proposal was initially drafted here, but CFD and stock are deliberately separated end-to-end (separate repos, OLTP schemas, Snowflake DBs, dbt projects, Airflow DAGs, Lightdash projects — user directive 2026-05-28). The ACY TradingCup pilot lives in the CFD vertical.

**Canonical location:**
`~/git/datapai-cfd-be/docs/phase-journals/2026-05-28-acy-tradingcup-pilot-proposal.md`

**TL;DR for stock-be readers:**
- ACY CEO Jimmy inbound 2026-05-27 → 6-week paid pilot on tradingcup.com (fake money)
- Product: multi-persona AI debate engine (Bull/Bear/Risk/PM), 8 languages
- Synthesis pipeline pattern originated here in stock-be (commits 076ae2a, 5199161, da30dad, 7032152) and is being ported to cfd-be with CFD-specific schema, prompts, and DAGs.
- No code changes in stock-be from this pilot.

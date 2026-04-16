# CLAUDE.md

## Project overview
This project generates a daily cyber threat landscape page for a WordPress website.

The pipeline runs externally on a Raspberry Pi, collects recent cyber threat intelligence/news/advisory items, ranks the top threats, enriches them, produces static assets and STIX JSON, uploads the generated files to the web host, and exposes the content on WordPress through a lightweight shortcode plugin.

The site is hosted on WordPress, but generation does not happen inside WordPress.

## Core outcome
Every day at 07:00 Europe/London:
1. Collect recent items from configured cyber sources
2. Normalise and deduplicate items
3. Score and select the top 10 threats
4. Enrich each threat
5. Generate STIX 2.1 JSON bundles
6. Render a polished HTML/JSON output
7. Upload output files to the web host
8. Let WordPress render the latest content through `[barry_threat_landscape]`

## Non-negotiables
- Python 3.11+
- British English spelling in comments, docs, and UI
- No dependence on the WordPress REST API
- Minimal manual intervention after initial setup
- Must work on Raspberry Pi
- Prefer RSS, official advisories, and structured feeds over brittle scraping
- Degrade gracefully when sources fail
- Do not fabricate facts
- Mark uncertainty explicitly
- STIX must be STIX 2.1 JSON
- WordPress plugin must use sanitisation, escaping, and shortcode best practices
- Shortcode should return content, not echo it
- The design should be clean, modern, and professional, not cluttered

## Product assumptions
- Daily generation is acceptable; this is not a real-time feed
- Some sources may not expose all desired fields
- Social media support is optional and should be adapter-based
- LLM-based enrichment is optional behind a provider interface
- The system must still work without paid APIs

## Preferred architecture
- `src/collectors/` for source adapters
- `src/models/` for schemas
- `src/normalisers/`
- `src/dedupe/`
- `src/scoring/`
- `src/enrichment/`
- `src/stix/`
- `src/render/`
- `src/deploy/`
- `src/cli/`
- `wordpress_plugin/`
- `templates/`
- `static/`
- `output/`
- `config/`
- `tests/`

## Engineering preferences
- Use type hints everywhere practical
- Prefer pydantic or dataclasses for data models
- Keep modules focused and readable
- Add logging around source collection, scoring, build, and deploy steps
- Add retries and sensible timeouts for network calls
- Use configuration files instead of hardcoding source settings and credentials
- Add preview mode for frontend iteration
- Make important logic testable
- Avoid unnecessary frameworks

## Data handling rules
- Preserve provenance for all important fields
- Keep original source URL, source name, publication date, and supporting references
- Deduplicate near-identical stories across sources
- Merge corroborating reports into a single threat candidate
- Use explicit confidence labels for:
  - attribution
  - ATT&CK mapping
  - affected countries
  - affected companies
  - affected industries
- Use “Unknown” or “Unconfirmed” where evidence is insufficient

## Ranking guidance
The “top 10 threats” should be selected via a transparent scoring model.

Prefer signals such as:
- recency
- uniqueness (compared to other 9 threats)
- source credibility
- corroboration across multiple sources
- breadth of impact
- severity/operational significance
- actionability
- explicit exploitation indicators
- presence of CVEs, malware, ransomware, active campaigns, major advisories

Make weighting configurable.

## STIX guidance
- Use STIX 2.1 JSON bundles
- Include only objects that are reasonably supported by evidence
- External references should point back to source URLs
- Partial bundles are acceptable when evidence is incomplete
- Output one STIX JSON file per threat
- Frontend should allow copy-to-clipboard and download

## Frontend guidance
The frontend should feel like it belongs on a professional personal cybersecurity website.

Desired qualities:
- polished
- restrained
- responsive
- accessible
- readable
- modern but not flashy

Suggested UI:
- page hero/header
- “last updated” stamp
- 10 threat cards
- badges for source, confidence, sector, country, ATT&CK
- expandable details section
- copy STIX button
- methodology/disclaimer section

Avoid:
- crowded dashboards
- unnecessary charts
- noisy animations
- excessive gradients
- overly dark/red “hacker” aesthetics unless configurable

## WordPress plugin guidance
The plugin should:
- register shortcode `[barry_threat_landscape]`
- read local JSON from uploads or fetch remote JSON from a configured URL
- cache results
- sanitise and escape everything
- return rendered markup
- fail gracefully if data is unavailable
- expose minimal settings for URL/path, cache TTL, and title override

## Deployment guidance
Generated files should be uploadable via SFTP from the Raspberry Pi to the web host.

Expected deploy targets:
- `latest.json`
- `index.html`
- `stix/*.json`
- supporting CSS/JS if needed

Keep deployment simple and robust.

## Commands expected
Provide CLI commands equivalent to:
- collect
- build
- deploy
- run-all
- preview

## Documentation expectations
Always keep the README actionable.
Include:
- local setup
- Raspberry Pi setup
- config
- cron/systemd scheduling
- deployment
- WordPress plugin installation
- shortcode usage
- troubleshooting
- limitations and caveats

## Behaviour when uncertain
If blocked, make the smallest safe assumption and clearly note it.
Do not stop early if a reasonable implementation path exists.
Do not ask unnecessary clarifying questions.
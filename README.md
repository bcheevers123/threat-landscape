# Cyber Threat Landscape — Daily Briefing Generator

A Python pipeline that collects cyber threat intelligence from public sources, ranks and enriches the top 10 threats, generates a polished HTML page and STIX 2.1 JSON bundles, and deploys them to a WordPress website via SFTP.

A companion **ML/AI Landscape** pipeline runs separately and tracks the top machine learning research and AI industry developments.

Both pipelines are designed to run on a Raspberry Pi but work equally well on Windows. The WordPress site renders the content through a lightweight shortcode plugin — no WordPress REST API dependency required.

---

## Table of Contents

1. [Architecture overview](#architecture-overview)
2. [Setup — Windows PC](#setup--windows-pc)
3. [Setup — Raspberry Pi](#setup--raspberry-pi)
4. [Configuration](#configuration)
5. [CLI commands](#cli-commands)
6. [AI/ML pipeline](#aiml-pipeline)
7. [Scheduling](#scheduling)
8. [Deployment](#deployment)
9. [WordPress plugin installation](#wordpress-plugin-installation)
10. [Shortcode usage](#shortcode-usage)
11. [Troubleshooting](#troubleshooting)
12. [Limitations and caveats](#limitations-and-caveats)
13. [Legal and ethical considerations](#legal-and-ethical-considerations)

---

## Architecture overview

```
config/
  config.yaml          Cyber pipeline settings (scoring weights, output dirs, SFTP)
  sources.yaml         Cyber source list with credibility scores

aiml/
  config/
    config.yaml        ML/AI pipeline settings
    sources.yaml       ML/AI source list
  output/              Generated ML/AI artefacts (gitignored)
  static/
    theme.css          Violet/indigo theme overrides for the ML/AI page
    app.js             ML/AI-specific JS (badge tooltips, score panel)
  templates/
    index.html.j2      ML/AI Jinja2 template

src/
  collectors/          RSS/Atom feed adapters + parallel collection manager
  normalisers/         URL canonicalisation, title cleaning
  dedupe/              URL-exact + title-similarity deduplication
  scoring/             Transparent weighted scoring (6 dimensions)
  enrichment/          Rule-based NER, ATT&CK mapping, extractive summarisation
  stix/                STIX 2.1 bundle builder
  render/              Jinja2 HTML + JSON renderer
  deploy/              SFTP uploader
  main.py              Cyber pipeline CLI entry point
  aiml_main.py         ML/AI pipeline CLI entry point

templates/
  index.html.j2        Cyber Jinja2 template

static/
  style.css            Clean, responsive CSS (shared base)
  app.js               Vanilla JS (expand/collapse, copy STIX, search/filter, tooltips)

output/                Generated cyber artefacts (gitignored)
  index.html
  latest.json
  stix/<uuid>.json
  static/

wordpress_plugin/
  barry-threat-landscape/
    barry-threat-landscape.php   WordPress shortcode plugin
    btl-style.css                Plugin-scoped stylesheet
```

### Pipeline stages

1. **Collect** — fetch RSS/Atom feeds from all enabled sources in parallel threads
2. **Normalise** — canonical URLs, strip HTML entities, ensure published_at
3. **Deduplicate** — group by URL, then by title similarity (rapidfuzz); merge corroborating reports
4. **Score** — weighted sum across: recency, source credibility, corroboration, severity, breadth, actionability; domain diversity cap prevents one source dominating the top 10
5. **Enrich** — extract CVEs, countries, sectors, malware families, threat actors, ATT&CK techniques; generate extractive summary
6. **STIX** — build STIX 2.1 bundle per threat (report + threat-actor + malware + vulnerability + attack-pattern objects)
7. **Render** — Jinja2 → `index.html`, `latest.json`, `stix/*.json`
8. **Deploy** — SFTP upload to web host

---

## Setup — Windows PC

This is the recommended setup while the Raspberry Pi is not in use. When you are ready to move back to the Pi, follow [Setup — Raspberry Pi](#setup--raspberry-pi) instead.

### Prerequisites

- Python 3.11 or later — download from [python.org](https://www.python.org/downloads/)
- Git (optional, for cloning)
- Windows Terminal or PowerShell

### Steps

Open a terminal in the project directory (right-click the folder → "Open in Terminal", or `cd` to it):

```bat
cd C:\Users\barry\PycharmProjects\ThreatLandscape

:: Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate

:: Install dependencies
pip install -r requirements.txt

:: Copy and fill in environment variables
copy .env.example .env
:: Edit .env in Notepad or your editor — fill in SFTP credentials if deploying

:: Run the cyber pipeline
python -m src.main build

:: Preview the output in your browser
python -m src.main preview
:: Open http://localhost:8080
```

> **Note:** When running commands in this README that show `source venv/bin/activate` (Linux syntax), use `venv\Scripts\activate` on Windows instead.

### SFTP key setup on Windows

```bat
:: Generate a key pair (run in Windows Terminal or PowerShell)
ssh-keygen -t ed25519 -C "pc-threat-landscape" -f "%USERPROFILE%\.ssh\threat_landscape"

:: Copy public key to your web host (replace with your actual host and user)
type "%USERPROFILE%\.ssh\threat_landscape.pub"
:: Paste the output into your web host's "Authorised Keys" via the control panel,
:: or use ssh-copy-id if your host supports it via WSL.
```

Then update your `.env`:
```
SFTP_KEY_PATH=C:\Users\barry\.ssh\threat_landscape
```

### Scheduling on Windows

See [Scheduling — Windows Task Scheduler](#windows-task-scheduler) below.

---

## Setup — Raspberry Pi

Tested on Raspberry Pi 4 (2 GB RAM) running Raspberry Pi OS Lite (64-bit).

```bash
# 1. Update the system
sudo apt update && sudo apt upgrade -y

# 2. Install Python 3.11+ (if not already present)
sudo apt install -y python3 python3-pip python3-venv git

# 3. Clone the repository
git clone <your-repo-url> /home/pi/ThreatLandscape
cd /home/pi/ThreatLandscape

# 4. Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# 5. Install dependencies
pip install -r requirements.txt

# 6. Configure
cp .env.example .env
nano .env          # fill in SFTP_HOST, SFTP_USER, SFTP_KEY_PATH

# 7. Test the build
python -m src.main build

# 8. Test deployment (optional)
python -m src.main deploy
```

### SSH key setup on the Pi

```bash
# Generate a key pair on the Pi
ssh-keygen -t ed25519 -C "pi-threat-landscape" -f ~/.ssh/threat_landscape

# Copy the public key to your web host
ssh-copy-id -i ~/.ssh/threat_landscape.pub user@your-webhost.example.com

# Update .env
SFTP_KEY_PATH=~/.ssh/threat_landscape
```

---

## Configuration

### `config/config.yaml` (cyber pipeline)

```yaml
output_dir: output          # where generated files are written
top_n: 10                   # number of threats to output
max_items_per_source: 50    # items fetched per source feed
lookback_hours: 48          # items older than this are penalised in scoring

scoring:
  recency: 0.25             # weights must sum to 1.0 (excluding diversity_cap)
  source_credibility: 0.20
  corroboration: 0.15
  severity: 0.20
  breadth: 0.10
  actionability: 0.10
  diversity_cap: 2          # max items from the same source domain in the top 10

enrichment:
  provider: deterministic   # no paid API required
  max_summary_words: 80

deploy:
  sftp_host: ""             # or set SFTP_HOST env var
  sftp_port: 22
  sftp_user: ""             # or set SFTP_USER env var
  sftp_key_path: ""         # or set SFTP_KEY_PATH env var
  remote_base_path: /public_html/wp-content/uploads/barry-threat-landscape

branding:
  site_name: Barry Cheevers
  page_title: Cyber Threat Landscape Today
  subtitle: A daily briefing on the top active cyber threats
  site_url: https://barrycheevers.co.uk
```

### `aiml/config/config.yaml` (ML/AI pipeline)

Key differences from the cyber config:

```yaml
output_dir: aiml/output
static_dir: static          # base CSS; aiml/static/theme.css layered on top

scoring:                    # ML pool — significance and credibility dominate
  recency: 0.20
  source_credibility: 0.28
  severity: 0.25            # maps to AI/ML significance (breakthroughs, open weights…)
  diversity_cap: 2

scoring_ai:                 # AI news pool — corroboration is the strongest signal
  corroboration: 0.28
  recency: 0.25
  diversity_cap: 2

deploy:
  remote_base_path: /public_html/wp-content/uploads/barry-aiml-landscape
```

### `config/sources.yaml`

Add, disable, or adjust sources without changing any code:

```yaml
sources:
  - name: NCSC UK
    url: https://www.ncsc.gov.uk/api/1/services/v1/report-rss-feed.xml
    type: rss
    credibility: 0.95
    enabled: true
    tags: [advisory, uk, government]
    stream: technical       # technical | mainstream | both
```

`credibility` (0.0–1.0) directly influences the `source_credibility` scoring dimension. Government advisories should score highest; blogs and journalism lower.

`stream` controls which scoring pool an item enters: `technical` (expert view), `mainstream` (consumer view with security keyword filter), or `both` (routed by title analysis).

### Environment variables (`.env`)

Copy `.env.example` to `.env` and fill in your values:

| Variable | Description |
|---|---|
| `SFTP_HOST` | Remote host for deployment |
| `SFTP_PORT` | SSH port (default: 22) |
| `SFTP_USER` | SSH username |
| `SFTP_KEY_PATH` | Path to SSH private key |
| `SFTP_PASSWORD` | SFTP password (prefer key auth) |
| `OPENAI_API_KEY` | Optional — for LLM enrichment |
| `ANTHROPIC_API_KEY` | Optional — for LLM enrichment |

Environment variables take precedence over values in `config.yaml`.

---

## CLI commands

Activate the virtual environment first:

```bash
# Linux / macOS / Pi
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### Cyber threat pipeline

```bash
# Collect only (saves output/raw_items.json for inspection)
python -m src.main collect

# Full build: collect → normalise → dedupe → score → enrich → render
python -m src.main build

# Deploy generated output/ to remote host via SFTP
python -m src.main deploy

# Build then deploy in one step
python -m src.main run-all

# Local preview server (open http://localhost:8080)
python -m src.main preview

# Enable debug logging
python -m src.main --verbose build

# Override config paths
python -m src.main --config path/to/config.yaml --sources path/to/sources.yaml build
```

### ML/AI pipeline

```bash
python -m src.aiml_main build
python -m src.aiml_main deploy
python -m src.aiml_main run-all
python -m src.aiml_main preview     # open http://localhost:8081
python -m src.aiml_main --verbose build
```

---

## AI/ML Pipeline

The ML/AI pipeline is a parallel system that produces a separate page covering machine learning research and AI industry news. It lives alongside the cyber pipeline and is independently configured.

### What it does

- Collects from ML/AI-specific sources: arXiv (cs.LG, cs.CL, cs.CV, cs.AI, cs.RO, cs.NE, stat.ML), Google DeepMind blog, OpenAI blog, Anthropic, MIT Technology Review, VentureBeat, The Verge, BAIR Blog, Lilian Weng's Blog, Nature Machine Intelligence, and more
- Splits items into two pools: **ML** (research papers, technical releases) and **AI** (industry news, policy, ethics)
- Uses AI/ML-specific scoring (significance, breadth of impact, applicability) instead of cyber threat scoring
- Tags each item with:
  - **Topic type** badges (Research, Model Release, Safety, Regulation, etc.)
  - **ML technique** badges (LLM, Diffusion Model, Reinforcement Learning, Computer Vision, etc.)
- Applies a domain diversity cap so arXiv, for example, cannot fill the entire ML top 10
- Deploys to a separate remote path (`barry-aiml-landscape`) from the cyber pipeline

### Output

```
aiml/output/
  index.html          Standalone ML/AI landscape page
  latest.json         ML/AI data for a WordPress shortcode (if desired)
  stix/               STIX bundles (minimal — ML items rarely map to full STIX objects)
  static/             Copied assets including violet/indigo theme
```

### Running both pipelines together

```bash
# Build and deploy both in sequence
python -m src.main run-all && python -m src.aiml_main run-all
```

---

## Scheduling

### Windows Task Scheduler

1. Open **Task Scheduler** (search for it in the Start menu)
2. Click **Create Basic Task**
3. Name it `Threat Landscape Pipeline`
4. Set trigger: **Daily**, start time `07:00`
5. Action: **Start a program**
   - Program: `C:\Users\barry\PycharmProjects\ThreatLandscape\venv\Scripts\python.exe`
   - Arguments: `-m src.main run-all`
   - Start in: `C:\Users\barry\PycharmProjects\ThreatLandscape`
6. Finish, then right-click the task → **Properties** → **General** tab → tick **Run whether user is logged on or not**

To also run the ML/AI pipeline, create a second task using `-m src.aiml_main run-all`, or create a wrapper batch file:

```bat
:: run_all.bat — save in the project root
@echo off
cd /d C:\Users\barry\PycharmProjects\ThreatLandscape
call venv\Scripts\activate
python -m src.main run-all
python -m src.aiml_main run-all
```

Point the Task Scheduler action at `run_all.bat` to run both with one scheduled task.

### cron (Raspberry Pi)

Run at 07:00 London time. The `TZ` variable handles GMT/BST transitions automatically:

```cron
# Edit with: crontab -e
0 7 * * * TZ=Europe/London /home/pi/ThreatLandscape/venv/bin/python -m src.main run-all >> /home/pi/ThreatLandscape/logs/pipeline.log 2>&1
5 7 * * * TZ=Europe/London /home/pi/ThreatLandscape/venv/bin/python -m src.aiml_main run-all >> /home/pi/ThreatLandscape/logs/aiml_pipeline.log 2>&1
```

Create the log directory first:
```bash
mkdir -p /home/pi/ThreatLandscape/logs
```

### systemd timer (Raspberry Pi alternative)

Create `/etc/systemd/system/threat-landscape.service`:
```ini
[Unit]
Description=Cyber Threat Landscape Pipeline
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=pi
WorkingDirectory=/home/pi/ThreatLandscape
Environment=TZ=Europe/London
ExecStart=/home/pi/ThreatLandscape/venv/bin/python -m src.main run-all
StandardOutput=append:/home/pi/ThreatLandscape/logs/pipeline.log
StandardError=append:/home/pi/ThreatLandscape/logs/pipeline.log
```

Create `/etc/systemd/system/threat-landscape.timer`:
```ini
[Unit]
Description=Run Threat Landscape Pipeline daily at 07:00 London time

[Timer]
OnCalendar=07:00
TimeZone=Europe/London
Persistent=true

[Install]
WantedBy=timers.target
```

Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now threat-landscape.timer
sudo systemctl status threat-landscape.timer
```

---

## Deployment

The deploy step uploads these files to your web host via SFTP:

### Cyber pipeline

```
/public_html/wp-content/uploads/barry-threat-landscape/
  latest.json          (read by the WordPress plugin)
  index.html           (standalone page)
  stix/<uuid>.json     (one per threat)
  static/style.css
  static/app.js
```

Accessible at:
```
https://yoursite.com/wp-content/uploads/barry-threat-landscape/latest.json
```

### ML/AI pipeline

```
/public_html/wp-content/uploads/barry-aiml-landscape/
  latest.json
  index.html
  stix/<uuid>.json
  static/style.css
  static/app.js
  static/theme.css
```

### Dry run / test

Run `build` without `deploy` to generate files locally and inspect them with `preview` before uploading anything.

### First-time remote directory setup

Some shared hosting providers do not permit automatic directory creation over SFTP. If deployment fails with a "no such file" error, create the remote directory manually first via your host's file manager or cPanel:

```
wp-content/uploads/barry-threat-landscape/
wp-content/uploads/barry-aiml-landscape/
```

---

## WordPress plugin installation

The plugin renders the **cyber threat** data. A second shortcode can be wired to the ML/AI `latest.json` if desired.

### Manual installation

1. Copy the plugin folder to your WordPress installation via SFTP or the server file manager:

```
wordpress_plugin/barry-threat-landscape/  →  wp-content/plugins/barry-threat-landscape/
```

2. Log in to the WordPress admin panel.
3. Navigate to **Plugins → Installed Plugins**.
4. Find **Barry Threat Landscape** and click **Activate**.
5. Navigate to **Settings → Threat Landscape**.
6. Configure the JSON source:
   - **Leave blank** to use the default path `wp-content/uploads/barry-threat-landscape/latest.json` (recommended when deploying via SFTP to this location).
   - Or enter a full HTTPS URL: `https://yoursite.com/wp-content/uploads/barry-threat-landscape/latest.json`

### Zip installation

```bash
cd wordpress_plugin
zip -r barry-threat-landscape.zip barry-threat-landscape/
```

On Windows:
```bat
cd wordpress_plugin
powershell Compress-Archive barry-threat-landscape barry-threat-landscape.zip
```

Then upload via **Plugins → Add New → Upload Plugin**.

---

## Shortcode usage

Add this shortcode to any WordPress page or post:

```
[barry_threat_landscape]
```

Optional attribute to override the heading:

```
[barry_threat_landscape title="Today's Top 10 Cyber Threats"]
```

The plugin:
- Fetches `latest.json` from the configured source (local file or HTTPS URL)
- Caches the result for the configured TTL (default: 1 hour) using WordPress transients
- Renders the threat cards inline
- Fails gracefully with a user-friendly message if the file is unavailable
- Provides a **Flush Cache Now** button in Settings → Threat Landscape

---

## Running tests

```bash
# Activate the virtual environment first
pip install -r requirements.txt
pytest

# With coverage
pytest --cov=src --cov-report=term-missing
```

---

## Troubleshooting

### No items collected

- Check network connectivity: `curl -I https://feeds.feedburner.com/TheHackersNews`
  - On Windows: `Invoke-WebRequest -Uri https://feeds.feedburner.com/TheHackersNews -Method Head`
- Some feeds may be temporarily unavailable — the pipeline degrades gracefully
- Run with `--verbose` for per-source debug output: `python -m src.main --verbose collect`

### SFTP deployment fails

- Test the SSH connection manually: `ssh -i path/to/key user@host`
- Check the `remote_base_path` exists and is writable on the server
- The deployer attempts to create the remote directory tree; if your host restricts this, create the directories manually first via cPanel or the host's file manager
- On Windows, ensure the path in `SFTP_KEY_PATH` uses the correct separator (`C:\Users\barry\.ssh\key` or a forward-slash equivalent)

### WordPress plugin shows "file not found"

- Confirm `latest.json` was successfully deployed to the remote path
- Check that `wp-content/uploads/` is readable by the web server (typically `755` permissions)
- Use **Settings → Threat Landscape → Flush Cache Now** to force a fresh fetch
- If using a URL source, verify the URL is HTTPS — the plugin rejects plain HTTP for security

### Empty or sparse threat page

- The pipeline publishes whatever it collected — if sources were down, fewer than 10 threats may appear
- Check `output/raw_items.json` after `collect` to see what was gathered
- Increase `lookback_hours` in `config.yaml` if recent items are thin

### Scoring weights error on startup

- The `diversity_cap` key in `config.yaml` is not a scoring weight and is handled separately — do not include it in a custom scoring block without the matching key
- Weight values under `scoring:` must sum to 1.0 (excluding `diversity_cap`)

### ML/AI pipeline produces few results

- arXiv feeds are prolific but rate-limit occasional scrapers — re-run after a few minutes if a collection run returns very few arXiv items
- The `_is_ml_article()` filter removes off-topic tech articles; if legitimate articles are being dropped, check `--verbose` output from `src.aiml_main collect`

### Virtual environment not found (Windows)

```bat
:: If venv\Scripts\activate gives a permissions error in PowerShell:
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

---

## Moving from Windows PC to Raspberry Pi

When you are ready to move the pipeline back to the Pi:

1. Ensure the Pi is running Raspberry Pi OS with Python 3.11+
2. Copy or clone the project to `/home/pi/ThreatLandscape`
3. Follow [Setup — Raspberry Pi](#setup--raspberry-pi)
4. Copy your `.env` file to the Pi (do not commit it to git)
5. Copy your SSH private key to `~/.ssh/` on the Pi and update `SFTP_KEY_PATH` in `.env`
6. Run `python -m src.main build` to verify the build works
7. Set up cron or systemd scheduling
8. Disable the Windows Task Scheduler task

The project directory structure and all config files are identical between platforms — only the activation command and scheduler differ.

---

## Limitations and caveats

- **Enrichment accuracy**: ATT&CK mappings, attribution, country and sector extraction are all rule-based keyword matching. They produce false positives and miss nuance. Treat all analytical fields as best-effort signals, not ground truth.

- **No real-time data**: The page reflects the state of public feeds at the time of the last pipeline run. It is not a live feed.

- **Source availability**: Feed URLs change. If a source goes quiet, check its URL and update `sources.yaml`.

- **No full-text extraction**: The pipeline uses RSS feed summaries as the primary text source. Full article text is not fetched by default (this would be slower, heavier, and more likely to breach publisher terms). The `trafilatura` dependency is available if you wish to extend the `RSSCollector` to fetch full text.

- **STIX bundles are partial**: When evidence is sparse, the STIX bundle will contain only a report object. This is explicitly permitted by STIX 2.1.

- **ML/AI scoring is approximated**: The "severity", "breadth", and "actionability" dimensions for ML/AI items use keyword heuristics, not semantic understanding. A paper that happens to mention "healthcare" will score higher on breadth even if healthcare is not its primary application.

- **Performance**: On a Raspberry Pi 4, collection from 40+ sources takes approximately 60–90 seconds. On a modern PC it is significantly faster. The build step itself is fast on both.

---

## Legal and ethical considerations

- **Source terms of service**: Review the terms of service for each feed in `sources.yaml`. Most permit automated access for non-commercial personal use, but you are responsible for verifying this.
- **Attribution**: Always link back to the original article. The generated page includes the original URL for every item.
- **No scraping by default**: The pipeline uses official RSS/Atom feeds only. No content is scraped from web pages.
- **No fabrication**: The system is explicitly designed not to fabricate facts. Uncertain fields use "Unknown" / "Unconfirmed" labels. Never use the output as a substitute for authoritative intelligence.
- **Personal data**: This pipeline does not collect or process any personal data.
- **GDPR / data protection**: Generated pages are derived entirely from public sources. No personal data is stored or transmitted.

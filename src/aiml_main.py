"""
ML/AI Landscape Pipeline — CLI entry point.

Usage:
  python -m src.aiml_main collect        # collect raw items
  python -m src.aiml_main build          # run full pipeline
  python -m src.aiml_main deploy         # upload output/ via SFTP
  python -m src.aiml_main run-all        # build + deploy
  python -m src.aiml_main preview        # serve aiml/output/ locally on HTTP (port 8081)

Configuration is loaded from aiml/config/config.yaml and aiml/config/sources.yaml
by default.  Override with --config / --sources flags.

Stream semantics
----------------
  ml     — Machine learning: research papers, model releases, training techniques,
            benchmarks, datasets, and ML infrastructure.
  ai     — Broader artificial intelligence: policy, regulation, ethics, company news,
            products, and AI deployments that are not primarily about ML methods.
  both   — Sources covering both; individual articles are classified by title keyword
            matching.  ML-keyword-heavy titles go to the ML pool; others go to AI.

Deduplication between pools
----------------------------
  The ML pool is scored first and its top-N selected.  Those items are then
  excluded from the AI pool before the AI top-N is selected.  This guarantees
  no story appears in both top-10 lists.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import click
import yaml
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG = _PROJECT_ROOT / "aiml" / "config" / "config.yaml"
_DEFAULT_SOURCES = _PROJECT_ROOT / "aiml" / "config" / "sources.yaml"
_AIML_APP_JS = _PROJECT_ROOT / "aiml" / "static" / "app.js"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _get_config(path: Optional[str]) -> dict[str, Any]:
    p = Path(path) if path else _DEFAULT_CONFIG
    return _load_yaml(p)


def _get_sources(path: Optional[str]) -> list[dict[str, Any]]:
    p = Path(path) if path else _DEFAULT_SOURCES
    data = _load_yaml(p)
    return data.get("sources", [])


# ---------------------------------------------------------------------------
# ML keyword classifier
# Used to route articles from "both"-stream sources into ml or ai pool.
# Matching is title-only to avoid noisy false positives from body text.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# AI story filter
# Applied to items from 'ai'-stream sources to exclude off-topic tech articles
# that have no AI/ML content.  Uses \b word-boundary regex so "AI" matches at
# sentence start/end/punctuation but not inside words like "Nokia" or "Braid".
# ---------------------------------------------------------------------------

import re as _re  # noqa: E402

_AI_STORY_PATTERN = _re.compile(
    r"""
    \bai\b                          # standalone "AI" or "ai"
    | artificial\s+intelligence
    | machine\s+learning
    | deep\s+learning
    | neural\s+network
    | language\s+model
    | foundation\s+model
    | generative\s+(ai|model|image|video|text)
    | large\s+language
    # Named labs / systems
    | chatgpt | openai | deepmind | anthropic | mistral | cohere
    | \bgemini\b | \bllama\b | \bgrok\b | \bclaude\b
    | hugging\s+face | stability\s+ai
    | copilot                        # microsoft copilot is AI
    # ML shorthand
    | \bllm\b | \bllms\b
    | transformer\s+model | diffusion\s+model
    | \brlhf\b | fine.tun
    # Outputs / artefacts
    | deepfake | synthetic\s+media | ai.generated
    | \bchatbot\b
    # Domains
    | \brobotic | autonomous\s+(vehicle|system|agent|driving)
    | self.driving | self.supervised
    | \bnvidia\b                     # GPU context almost always AI
    | ai\s+(chip|compute|safety|ethics|regulation|policy|act|startup
             |company|lab|model|tool|system|agent|assistant|art
             |research|governance|alignment|risk|bias|hallucin)
    | (using|powered\s+by|built\s+with|thanks\s+to)\s+ai
    | ai\s+is | ai\s+can | ai\s+will | ai\s+has | ai\s+for
    """,
    _re.VERBOSE | _re.IGNORECASE,
)


def _is_ai_story(title: str) -> bool:
    """Return True if the article title is about AI/ML content."""
    return bool(_AI_STORY_PATTERN.search(title))


# ---------------------------------------------------------------------------
# ML keyword classifier
# Used to route articles from "both"-stream sources into ml or ai pool.
# Matching is title-only to avoid noisy false positives from body text.
# ---------------------------------------------------------------------------

_ML_TITLE_KEYWORDS: frozenset[str] = frozenset({
    # Core ML terms
    "machine learning", "deep learning", "neural network", "neural networks",
    "reinforcement learning", "rlhf", "rlaif", "reward model",
    # Architecture terms
    "transformer", "attention mechanism", "self-attention",
    "diffusion model", "generative model", "flow matching",
    "mixture of experts", "moe", "state space model", "mamba",
    # Model types and sizes
    "large language model", "language model", "foundation model",
    "multimodal model", "vision-language model",
    # Training & techniques
    "fine-tuning", "fine tuning", "finetuning", "pre-training", "pretraining",
    "instruction tuning", "transfer learning", "few-shot", "zero-shot",
    "prompt tuning", "lora", "quantization", "quantisation",
    "knowledge distillation", "pruning", "sparsity",
    # Benchmarks & evaluation
    "benchmark", "leaderboard", "state-of-the-art", "sota",
    "outperforms", "surpasses", "achieves",
    # Research artefacts
    "dataset", "training data", "preprint", "arxiv",
    "open weights", "model weights", "model card",
    # Frameworks & hardware
    "pytorch", "tensorflow", "jax", "triton", "cuda",
    "gpu cluster", "tpu",
    # Specific ML subfields
    "computer vision", "natural language processing", "nlp",
    "speech recognition", "text-to-speech", "object detection",
    "image segmentation", "semantic segmentation",
    "image generation", "text-to-image", "text-to-video", "text-to-3d",
    "code generation", "protein structure",
    # Common model family keywords that signal research context
    "parameters", "context window", "token limit",
    "embedding", "vector database", "retrieval-augmented",
    "hallucination", "perplexity", "f1 score",
    "papers with code", "hugging face",
})


def _is_ml_article(title: str) -> bool:
    """Return True if the article title is primarily about ML methods/research."""
    title_lower = title.lower()
    return any(kw in title_lower for kw in _ML_TITLE_KEYWORDS)


# ---------------------------------------------------------------------------
# AI/ML-specific keyword sets for scoring
# These replace the cybersecurity-specific sets in src/scoring/scorer.py so
# that the three secondary dimensions (severity, breadth, actionability) are
# actually informative for AI/ML articles rather than always scoring zero.
# ---------------------------------------------------------------------------

_AIML_SIGNIFICANCE_KEYWORDS: frozenset[str] = frozenset({
    # Research impact
    "breakthrough", "state-of-the-art", "sota", "outperforms", "surpasses",
    "outperform", "exceeds", "beats", "significantly improves", "advances",
    "novel", "first to", "new record", "achieves", "proposes",
    # Open releases (strongly signal importance)
    "open-source", "open source", "open weights", "weights released",
    "publicly available", "available now", "model released",
    # Scale / frontier signals
    "billion parameters", "trillion", "frontier model", "emergent",
    "scaling", "large-scale",
    # Safety & adversarial signals
    "jailbreak", "jailbreaking", "safety concern", "alignment failure",
    "adversarial", "model collapse", "hallucination",
    # Policy / commercial signals
    "regulation", "legislation", "executive order", "ban", "major",
    "funding", "acquisition", "billion", "raises", "merger",
})

_AIML_BREADTH_KEYWORDS: frozenset[str] = frozenset({
    "healthcare", "medical", "clinical", "hospital",
    "finance", "financial", "banking", "insurance",
    "education", "school", "university", "academic",
    "government", "military", "defence", "defense",
    "enterprise", "business", "corporate", "industry",
    "global", "worldwide", "international",
    "widespread", "multiple sectors", "multiple domains",
    "climate", "science", "research community",
    "manufacturing", "retail", "logistics", "agriculture",
    "legal", "journalism", "media",
})

_AIML_APPLICABILITY_KEYWORDS: frozenset[str] = frozenset({
    "available", "released", "download", "open-source", "open source",
    "github", "code released", "code available", "hugging face",
    "model card", "api", "free to use", "free tier",
    "tutorial", "implementation", "guide", "how to",
    "pip install", "demo", "playground", "weights available",
    "documentation", "cookbook", "notebook", "colab",
})


def _score_aiml_significance(candidate) -> float:
    """0–1 significance score for AI/ML articles (breakthrough, open-weights, policy, …)."""
    text = " ".join(
        filter(None, [candidate.title, candidate.summary or "", " ".join(candidate.tags)])
    ).lower()
    hits = sum(1 for kw in _AIML_SIGNIFICANCE_KEYWORDS if kw in text)
    return min(1.0, hits / 4)


def _score_aiml_breadth(candidate) -> float:
    """0–1 breadth score for AI/ML articles based on cross-industry impact signals."""
    text = " ".join(
        filter(None, [candidate.title, candidate.summary or ""])
    ).lower()
    hits = sum(1 for kw in _AIML_BREADTH_KEYWORDS if kw in text)
    return min(1.0, hits / 3)


def _score_aiml_applicability(candidate) -> float:
    """0–1 applicability score for AI/ML articles (open releases, APIs, demos, tutorials)."""
    text = " ".join(
        filter(None, [candidate.title, candidate.summary or ""])
    ).lower()
    hits = sum(1 for kw in _AIML_APPLICABILITY_KEYWORDS if kw in text)
    return min(1.0, hits / 3)


# ---------------------------------------------------------------------------
# AI/ML topic type extractor
# Replaces the cybersecurity-specific threat type extractor for this pipeline.
# ---------------------------------------------------------------------------

_AIML_TYPE_MAP: list[tuple[str, list[str]]] = [
    ("Research", [
        "paper", "arxiv", "study", "findings", "benchmark", "dataset",
        "preprint", "research", "published", "proposes", "presents", "introduces",
        "outperforms", "state-of-the-art",
    ]),
    ("Model Release", [
        "release", "releases", "launch", "launches", "open-source", "open source",
        "model weights", "weights released", "available now", "now available",
        "version 2", "version 3", "v2", "v3", "gpt-", "llama", "mistral",
        "gemini", "claude", "grok", "deepseek", "phi-",
    ]),
    ("Safety & Alignment", [
        "safety", "alignment", "jailbreak", "jailbreaking", "harmful", "misuse",
        "guardrail", "red team", "red-team", "bias", "hallucination", "agi risk",
        "existential", "alignment tax", "constitutional ai",
    ]),
    ("Regulation & Policy", [
        "regulation", "policy", "law", "legislation", "eu ai act", "ai act",
        "ban", "governance", "compliance", "executive order", "senate",
        "parliament", "government", "regulator",
    ]),
    ("Product Launch", [
        "product", "feature", "chatbot", "assistant", "api", "service update",
        "plugin", "integration", "copilot", "workspace", "subscription",
    ]),
    ("Investment", [
        "funding", "investment", "invest", "raise", "raised", "billion",
        "acquisition", "acquires", "startup", "valuation", "ipo", "series a",
        "series b", "series c", "venture",
    ]),
    ("Infrastructure", [
        # Require multi-word phrases so generic "gpu" / "compute" in research
        # paper methods sections don't trigger an Infrastructure topic badge.
        "data center", "data centre", "training cluster", "compute cluster",
        "gpu cluster", "ai chip", "new chip", "chip shortage", "chip design",
        "custom silicon", "inference chip", "hardware accelerator",
        "ai infrastructure", "model infrastructure", "compute shortage",
        "hyperscaler", "supercomputer",
    ]),
    ("Ethics & Privacy", [
        "ethics", "ethical", "privacy", "copyright", "data rights",
        "surveillance", "consent", "transparency", "explainability",
        "accountability", "fairness",
    ]),
    ("Deepfake", [
        "deepfake", "deepfakes", "synthetic media", "ai-generated",
        "ai generated", "fake video", "fake audio", "voice clone",
        "misinformation", "disinformation",
    ]),
]


# Short keywords in topic types that need word-boundary protection
_TOPIC_TYPE_ABBREVS: frozenset[str] = frozenset({"api", "ipo", "v2", "v3"})


def _extract_aiml_types(text: str) -> list[str]:
    """Extract AI/ML topic type labels from article text (title + summary)."""
    text_lower = text.lower()
    found: list[str] = []
    for type_name, keywords in _AIML_TYPE_MAP:
        matched = False
        for kw in keywords:
            if kw in _TOPIC_TYPE_ABBREVS:
                if _re.search(r"\b" + _re.escape(kw) + r"\b", text_lower):
                    matched = True
                    break
            elif kw in text_lower:
                matched = True
                break
        if matched:
            found.append(type_name)
            if len(found) == 2:   # max 2 topic-type badges; leaves room for technique tags
                break
    return found or ["AI/ML"]


# ---------------------------------------------------------------------------
# ML technique / architecture classifier
# "Mother model" tags that label the fundamental ML paradigm an article
# belongs to.  Ordered from most-specific to most-general so that a robotics
# paper isn't swallowed by the LLM catch-all.
# ---------------------------------------------------------------------------

_ML_TECHNIQUE_MAP: list[tuple[str, list[str]]] = [
    ("AI Agent", [
        "ai agent", "autonomous agent", "multi-agent", "agentic",
        "tool use", "function calling", "planning agent",
        "language agent", "code agent", "agent framework",
        "computer use", "browser agent", "tool-calling",
    ]),
    ("Robotics", [
        "robotic", "robot learning", "robot manipulation",
        "embodied ai", "sim-to-real", "locomotion task", "grasping",
        "end-effector", "autonomous vehicle", "self-driving", "drone",
        "physical ai", "legged robot", "humanoid robot",
    ]),
    ("Federated Learning", [
        "federated learning", "split learning",
        "on-device learning", "decentralised learning",
    ]),
    ("Diffusion Model", [
        "diffusion model", "denoising diffusion", "score matching",
        "flow matching", "latent diffusion", "text-to-image",
        "stable diffusion", "consistency model",
    ]),
    ("GAN", [
        "generative adversarial", "variational autoencoder",
        "generator network", "adversarial training",
    ]),
    ("RAG", [
        "retrieval-augmented", "retrieval augmented",
        "retrieval augmentation", "vector search", "vector database",
        "dense retrieval", "knowledge retrieval",
    ]),
    ("Graph Learning", [
        "graph neural network", "graph neural", "knowledge graph",
        "graph convolution", "graph transformer", "molecular graph",
        "link prediction", "node classification", "heterogeneous graph",
    ]),
    ("Ensemble Methods", [
        "random forest", "decision forest", "gradient boosting",
        "xgboost", "lightgbm", "catboost",
        "decision tree", "random trees", "tree-based model",
        "boosted tree", "tabular ml", "tabular learning",
        "ensemble method", "ensemble model",
    ]),
    ("Clustering", [
        "clustering", "k-means", "gaussian mixture model",
        "hierarchical clustering", "contrastive learning",
        "self-supervised learning", "unsupervised learning",
    ]),
    ("Reinforcement Learning", [
        "reinforcement learning", "policy gradient", "proximal policy",
        "actor-critic", "multi-armed bandit", "rlhf", "rlaif",
        "reward hacking", "reward shaping",
    ]),
    ("Multimodal", [
        "multimodal", "multi-modal", "vision-language model",
        "cross-modal", "audio-visual",
        "visual question answering", "image captioning",
        "video-language",
    ]),
    ("Computer Vision", [
        "computer vision", "convolutional neural", "object detection",
        "image segmentation", "semantic segmentation",
        "instance segmentation", "image classification",
        "visual recognition", "point cloud", "3d reconstruction",
        "depth estimation", "pose estimation",
    ]),
    ("Fine-tuning", [
        "fine-tuning", "fine tuning", "finetuning", "lora",
        "instruction tuning", "adapter tuning",
        "prompt tuning", "parameter-efficient",
        "knowledge distillation", "model compression",
    ]),
    ("LLM", [
        "large language model", "language model", "language modeling",
        "chatgpt", "instruction following", "chain-of-thought",
        "in-context learning", "few-shot prompting",
        "text generation", "natural language processing",
        "tokenization", "tokeniser", "context window",
        "autoregressive model",
    ]),
]

# Short uppercase abbreviations that need word-boundary protection to avoid
# matching inside longer words (e.g. "rag" inside "fragment").
_TECHNIQUE_ABBREVS: frozenset[str] = frozenset({
    "llm", "llms", "gan", "rag", "vae", "rlhf", "rlaif", "gnn", "vlm",
    "cnn", "rnn", "lstm", "ppo", "sac", "dqn", "rl", "nlp",
    "bert", "gpt", "t5",
})


def _extract_ml_techniques(text: str) -> list[str]:
    """
    Extract up to 2 ML technique/architecture tags from article text.

    Ordered most-specific first so a robotics paper doesn't get swallowed
    by the LLM catch-all just because it mentions a language model in passing.

    Short abbreviations (gan, rag, sac, ppo, …) use \\b word-boundary
    matching to prevent false matches inside longer words.
    """
    text_lower = text.lower()
    found: list[str] = []
    for tech_name, keywords in _ML_TECHNIQUE_MAP:
        matched = False
        for kw in keywords:
            if kw in _TECHNIQUE_ABBREVS:
                if _re.search(r"\b" + _re.escape(kw) + r"\b", text_lower):
                    matched = True
                    break
            elif kw in text_lower:
                matched = True
                break
        if matched:
            found.append(tech_name)
            if len(found) == 2:
                break
    return found


# ---------------------------------------------------------------------------
# AI/ML-specific "why it matters" generator
# ---------------------------------------------------------------------------

from src.models.schemas import ThreatCandidate, AttackTechnique  # noqa: E402


def _aiml_why_it_matters(
    candidate: ThreatCandidate,
    types: list[str],
    sectors: list[str],
) -> str:
    """Generate an AI/ML-relevant 'why it matters' explanation."""
    parts: list[str] = []
    title_lower = candidate.title.lower()

    # --- Lead based on dominant topic type ---
    if "Research" in types:
        is_arxiv = any(
            item.source_name.lower().startswith("arxiv")
            for item in candidate.raw_items
        )
        if is_arxiv:
            parts.append(
                "A new research paper has been deposited on arXiv. "
                "Pre-prints on arXiv are the primary way ML researchers "
                "disclose findings before or alongside formal publication."
            )
        else:
            parts.append(
                "New research findings have been published. "
                "The results may shift the state-of-the-art or open "
                "new directions for the community."
            )

    elif "Model Release" in types:
        is_open = any(
            kw in title_lower
            for kw in ("open-source", "open source", "open weights", "weights released")
        )
        if is_open:
            parts.append(
                "A new open-source or open-weights model has been released. "
                "Open releases accelerate research and allow practitioners "
                "to self-host, fine-tune, and audit the model."
            )
        else:
            parts.append(
                "A new model or model version has been announced. "
                "Significant capability changes may affect downstream "
                "applications and the competitive landscape."
            )

    elif "Safety & Alignment" in types:
        parts.append(
            "Raises AI safety or alignment concerns. "
            "Safety findings affect how models are deployed, "
            "what safeguards are applied, and how the field "
            "approaches responsible development."
        )

    elif "Regulation & Policy" in types:
        parts.append(
            "A significant regulatory or policy development. "
            "Changes in AI governance can directly affect how "
            "organisations build, deploy, or procure AI systems."
        )

    elif "Investment" in types:
        parts.append(
            "Significant capital movement in the AI ecosystem. "
            "Large funding rounds and acquisitions signal which "
            "areas of the field are attracting sustained industry bet."
        )

    elif "Infrastructure" in types:
        parts.append(
            "Development in AI hardware or compute infrastructure. "
            "Access to compute remains one of the primary bottlenecks "
            "in training frontier models and running large-scale inference."
        )

    elif "Deepfake" in types:
        parts.append(
            "Involves AI-generated synthetic media. "
            "Deepfakes and AI-generated content have direct implications "
            "for trust, misinformation, and authentication at scale."
        )

    # --- Sector context ---
    known_sectors = [s for s in sectors if s.lower() not in ("unknown", "")]
    if known_sectors:
        sector_str = ", ".join(known_sectors[:3])
        suffix = " and others" if len(known_sectors) > 3 else ""
        parts.append(f"Most relevant to: {sector_str}{suffix}.")

    # --- Corroboration ---
    unique_sources = len({item.source_name for item in candidate.raw_items})
    if unique_sources >= 3:
        parts.append(
            f"Independently reported by {unique_sources} sources, "
            "increasing confidence in the significance of this development."
        )
    elif unique_sources == 2:
        parts.append("Corroborated by a second independent source.")

    # --- Fallback ---
    if not parts:
        parts.append(
            f"Reported by {candidate.primary_source}. "
            "Significance assessment is limited by the available source text."
        )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# AI/ML-aware enricher (extends DeterministicEnricher)
# ---------------------------------------------------------------------------

from src.enrichment.deterministic import DeterministicEnricher  # noqa: E402
from src.enrichment.entities import extract_countries, extract_sectors  # noqa: E402
from src.enrichment.deterministic import _extractive_summary  # noqa: E402
from src.models.schemas import (  # noqa: E402
    Attribution,
    ConfidenceLevel,
    EnrichedThreat,
    ScoreBreakdown,
)
from src.render.renderer import Renderer, _threat_to_dict  # noqa: E402
from src.scoring.scorer import (  # noqa: E402
    Scorer,
    ScoringWeights,
    _score_recency,
    _score_corroboration,
)


# ---------------------------------------------------------------------------
# AI/ML-aware scorer (extends Scorer)
# Replaces cyber-specific keyword functions with AI/ML equivalents so that the
# significance/breadth/applicability dimensions are actually informative for
# research papers and industry news rather than always returning near-zero.
# ---------------------------------------------------------------------------

class AIMLScorer(Scorer):
    """
    Scorer variant for the ML/AI pipeline.

    Replaces three cyber-specific scoring functions:
      severity     → _score_aiml_significance  (breakthrough, open-weights, jailbreak …)
      breadth      → _score_aiml_breadth        (healthcare, finance, global …)
      actionability→ _score_aiml_applicability  (github, api, demo, tutorial …)
    All other behaviour (recency, credibility, corroboration) is inherited unchanged.
    """

    def score(self, candidate) -> tuple[float, ScoreBreakdown]:
        w = self.weights
        dims = {
            "recency":            _score_recency(candidate.published_at) * w.recency,
            "source_credibility": candidate.max_source_credibility * w.source_credibility,
            "corroboration":      _score_corroboration(candidate.corroboration_count) * w.corroboration,
            "severity":           _score_aiml_significance(candidate) * w.severity,
            "breadth":            _score_aiml_breadth(candidate) * w.breadth,
            "actionability":      _score_aiml_applicability(candidate) * w.actionability,
        }
        total = sum(dims.values())
        breakdown = ScoreBreakdown(
            recency=round(dims["recency"], 4),
            source_credibility=round(dims["source_credibility"], 4),
            corroboration=round(dims["corroboration"], 4),
            severity=round(dims["severity"], 4),
            breadth=round(dims["breadth"], 4),
            actionability=round(dims["actionability"], 4),
            total=round(total, 4),
        )
        return total, breakdown


# ---------------------------------------------------------------------------
# AI/ML-aware renderer (extends Renderer)
# Overrides render_html to stamp data-stream="ml"/"ai" on cards instead of
# the base renderer's hardcoded "technical"/"mainstream" values, so the JS
# view-toggle and filter logic can locate the right cards.
# ---------------------------------------------------------------------------

class AIMLRenderer(Renderer):
    """Renderer for the ML/AI pipeline using 'ml'/'ai' stream labels."""

    def render_html(self, output) -> Path:
        from datetime import timezone

        template = self._env.get_template("index.html.j2")

        threats_data = [
            {**_threat_to_dict(t), "stream": "ml", "list_idx": f"t{i + 1}"}
            for i, t in enumerate(output.threats)
        ]
        mainstream_data = [
            {**_threat_to_dict(t), "stream": "ai", "list_idx": f"m{i + 1}"}
            for i, t in enumerate(output.mainstream_threats)
        ]

        sources_data = [
            {
                "name": s.name,
                "credibility": s.credibility,
                "credibility_pct": int(s.credibility * 100),
                "tags": s.tags,
                "rationale": s.rationale,
                "stream": s.stream,
            }
            for s in sorted(
                output.sources_queried, key=lambda x: x.credibility, reverse=True
            )
        ]

        html = template.render(
            threats=threats_data,
            mainstream_threats=mainstream_data,
            generated_at=output.generated_at.strftime("%d %B %Y at %H:%M UTC"),
            total_collected=output.total_items_collected,
            total_after_dedupe=output.total_items_after_dedupe,
            generation_notes=output.generation_notes,
            sources_queried=sources_data,
            branding=self.branding,
        )

        path = self.output_dir / "index.html"
        path.write_text(html, encoding="utf-8")
        logger.info("HTML written to %s", path)
        return path


class AIMLEnricher(DeterministicEnricher):
    """
    Enrichment provider adapted for ML/AI articles.

    Overrides threat-type extraction and the 'why it matters' generator
    to produce AI/ML-relevant output rather than cybersecurity analysis.
    STIX generation is not applicable for this pipeline and is skipped.
    """

    def enrich(
        self,
        candidate: ThreatCandidate,
        score: float,
        score_breakdown: Optional[ScoreBreakdown] = None,
    ) -> EnrichedThreat:
        text_parts = [candidate.title]
        if candidate.summary:
            text_parts.append(candidate.summary)
        if candidate.full_text:
            text_parts.append(candidate.full_text[:8_000])
        combined = " ".join(text_parts)

        countries = extract_countries(combined)
        sectors = extract_sectors(combined)
        topic_types = _extract_aiml_types(combined)          # e.g. ["Research", "Model Release"]
        technique_tags = _extract_ml_techniques(combined)    # e.g. ["LLM", "Fine-tuning"]
        # Merge: topic types first, then technique tags (skip any already present)
        types = topic_types + [t for t in technique_tags if t not in topic_types]

        source_text = candidate.full_text or candidate.summary or candidate.title
        summary = _extractive_summary(source_text, self.max_summary_words)
        if not summary:
            summary = candidate.summary or candidate.title

        why = _aiml_why_it_matters(candidate, types, sectors)

        _seen_support: set[str] = set()
        supporting_source_details: list[dict[str, str]] = []
        for item in candidate.raw_items:
            if (
                item.source_name != candidate.primary_source
                and item.source_name not in _seen_support
                and item.url
            ):
                _seen_support.add(item.source_name)
                supporting_source_details.append(
                    {"name": item.source_name, "url": item.url}
                )

        return EnrichedThreat(
            id=candidate.id,
            title=candidate.title,
            primary_url=candidate.primary_url,
            primary_source=candidate.primary_source,
            supporting_sources=candidate.supporting_sources,
            published_at=candidate.published_at,
            summary=summary,
            why_it_matters=why,
            attack_techniques=[],           # not applicable
            attribution=[],                 # not applicable
            countries_affected=countries,
            companies_affected=[],
            industries_affected=sectors,
            threat_types=types,
            cves=[],                        # not applicable
            malware_families=[],            # not applicable
            score=round(score, 4),
            score_breakdown=score_breakdown or ScoreBreakdown(),
            supporting_source_details=supporting_source_details,
            corroboration_count=candidate.corroboration_count,
            confidence_note=None,
        )


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.option("--config", default=None, metavar="PATH", help="Path to config.yaml")
@click.option("--sources", default=None, metavar="PATH", help="Path to sources.yaml")
@click.option("--verbose", is_flag=True, help="Enable DEBUG logging")
@click.pass_context
def cli(
    ctx: click.Context,
    config: Optional[str],
    sources: Optional[str],
    verbose: bool,
) -> None:
    """ML/AI Landscape Pipeline CLI."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    ctx.ensure_object(dict)
    ctx.obj["config"] = _get_config(config)
    ctx.obj["sources"] = _get_sources(sources)


# ---------------------------------------------------------------------------
# collect command
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def collect(ctx: click.Context) -> None:
    """Collect raw items from all enabled sources and save to output/raw_items.json."""
    from src.collectors.manager import CollectorManager
    from src.models.schemas import SourceConfig

    cfg = ctx.obj["config"]
    sources = [SourceConfig(**s) for s in ctx.obj["sources"]]

    manager = CollectorManager(
        sources=sources,
        max_items_per_source=cfg.get("max_items_per_source", 50),
    )
    items = manager.collect_all()

    out_dir = Path(cfg.get("output_dir", "aiml/output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "raw_items.json"
    raw_path.write_text(
        json.dumps(
            [i.model_dump(mode="json") for i in items], indent=2, default=str
        ),
        encoding="utf-8",
    )
    click.echo(f"Collected {len(items)} items → {raw_path}")


# ---------------------------------------------------------------------------
# build command
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def build(ctx: click.Context) -> None:
    """Run the full ML/AI pipeline: collect → normalise → dedupe → score → enrich → render."""
    _run_pipeline(ctx.obj["config"], ctx.obj["sources"])


# ---------------------------------------------------------------------------
# deploy command
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def deploy(ctx: click.Context) -> None:
    """Deploy generated assets to GitHub Pages (or SFTP if configured)."""
    cfg = ctx.obj["config"]
    output_dir = Path(cfg.get("output_dir", "aiml/output"))
    target = cfg.get("deploy_target", "github_pages")

    if target == "github_pages":
        _deploy_github_pages(cfg, output_dir)
    else:
        _deploy_sftp(cfg, output_dir)

    click.echo("Deployment complete.")


def _deploy_github_pages(cfg: dict, output_dir: Path) -> None:
    from src.deploy.github_pages import GitHubPagesDeployer

    gpcfg = cfg.get("github_pages", {})

    repo_url: str = gpcfg.get("repo_url", "").strip()
    if not repo_url:
        click.echo(
            "Error: github_pages.repo_url is not set in aiml/config/config.yaml.",
            err=True,
        )
        sys.exit(1)

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token and repo_url.startswith("https://github.com/"):
        repo_url = repo_url.replace("https://", f"https://x-access-token:{token}@", 1)

    staging_dir = str(
        _PROJECT_ROOT / gpcfg.get("staging_dir", "gh-pages-staging")
    )

    deployer = GitHubPagesDeployer(
        repo_url=repo_url,
        branch=gpcfg.get("branch", "gh-pages"),
        staging_dir=staging_dir,
        commit_name=gpcfg.get("commit_name", "Threat Landscape Bot"),
        commit_email=gpcfg.get("commit_email", "threatlandscape@localhost"),
        custom_domain=gpcfg.get("custom_domain") or None,
        subdir=gpcfg.get("subdir") or None,
    )
    deployer.deploy(output_dir)


def _deploy_sftp(cfg: dict, output_dir: Path) -> None:
    from src.deploy.sftp import SFTPDeployer

    dcfg = cfg.get("deploy", {})
    host = dcfg.get("sftp_host") or os.environ.get("SFTP_HOST", "")
    if not host:
        click.echo(
            "Error: SFTP host not configured. "
            "Set deploy.sftp_host in aiml/config/config.yaml or the SFTP_HOST env var.",
            err=True,
        )
        sys.exit(1)

    deployer = SFTPDeployer(
        host=host,
        port=int(dcfg.get("sftp_port", 22)),
        username=dcfg.get("sftp_user") or os.environ.get("SFTP_USER", ""),
        key_path=dcfg.get("sftp_key_path") or os.environ.get("SFTP_KEY_PATH"),
        password=os.environ.get("SFTP_PASSWORD"),
        remote_base=dcfg.get(
            "remote_base_path",
            "/public_html/wp-content/uploads/barry-aiml-landscape",
        ),
    )
    deployer.deploy(output_dir)


# ---------------------------------------------------------------------------
# run-all command
# ---------------------------------------------------------------------------

@cli.command("run-all")
@click.pass_context
def run_all(ctx: click.Context) -> None:
    """Run the full pipeline then deploy."""
    cfg = ctx.obj["config"]
    _run_pipeline(cfg, ctx.obj["sources"])
    ctx.invoke(deploy)


# ---------------------------------------------------------------------------
# preview command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--port", default=8081, show_default=True, help="Local HTTP port")
@click.pass_context
def preview(ctx: click.Context, port: int) -> None:
    """Serve the aiml output directory locally for browser preview."""
    import functools
    import http.server

    cfg = ctx.obj["config"]
    out_dir = Path(cfg.get("output_dir", "aiml/output"))

    if not (out_dir / "index.html").exists():
        click.echo("No index.html found. Run 'build' first.", err=True)
        sys.exit(1)

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(out_dir)
    )
    click.echo(f"ML/AI preview server running at http://localhost:{port}")
    click.echo("Press Ctrl+C to stop.")
    with http.server.HTTPServer(("", port), handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            click.echo("\nStopped.")


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------

def _run_pipeline(cfg: dict[str, Any], source_dicts: list[dict[str, Any]]) -> None:
    """
    Execute the full ML/AI pipeline:
      collect → normalise → dedupe → split (ml/ai) → score → enrich → render

    ML and AI pools are scored independently.  The ML top-N is selected first;
    those items are then excluded from the AI pool before the AI top-N is scored.
    This prevents the same story appearing in both top-10 lists.
    """
    from src.collectors.manager import CollectorManager
    from src.dedupe.deduplicator import deduplicate
    from src.models.schemas import SourceConfig, SourceSummary, ThreatLandscapeOutput
    from src.normalisers.normaliser import normalise_items

    sources = [SourceConfig(**s) for s in source_dicts]
    output_dir = Path(cfg.get("output_dir", "aiml/output"))
    template_dir = Path(cfg.get("template_dir", "aiml/templates"))
    static_dir = Path(cfg.get("static_dir", "static"))
    top_n: int = cfg.get("top_n", 10)

    generation_notes: list[str] = []

    # ── 1. Collect ──────────────────────────────────────────────────────────
    manager = CollectorManager(
        sources=sources,
        max_items_per_source=cfg.get("max_items_per_source", 50),
    )
    raw_items = manager.collect_all()
    total_collected = len(raw_items)

    if total_collected == 0:
        generation_notes.append(
            "No items were collected. Check source URLs and network connectivity."
        )

    # ── 2. Normalise ─────────────────────────────────────────────────────────
    normalised = normalise_items(raw_items)

    # ── 3. Deduplicate ───────────────────────────────────────────────────────
    candidates = deduplicate(normalised)
    total_after_dedupe = len(candidates)

    # ── 4. Split into ML and AI pools ────────────────────────────────────────
    # Sources with stream="ml"   → ML pool
    # Sources with stream="ai"   → AI pool
    # Sources with stream="both" → classify per article by title keywords

    ml_source_names = {
        s.name for s in sources if s.enabled and s.stream == "ml"
    }
    ai_source_names = {
        s.name for s in sources if s.enabled and s.stream == "ai"
    }
    both_source_names = {
        s.name for s in sources if s.enabled and s.stream == "both"
    }

    def _candidate_streams(candidate) -> set[str]:
        """Determine which pool(s) a candidate belongs to."""
        pools: set[str] = set()
        for item in candidate.raw_items:
            if item.source_name in ml_source_names:
                pools.add("ml")
            elif item.source_name in ai_source_names:
                # Filter out off-topic tech articles (e.g. gadget reviews, Secure Boot
                # issues) that appear in general-tech sections of AI-labelled feeds.
                if _is_ai_story(candidate.title):
                    pools.add("ai")
            elif item.source_name in both_source_names:
                # Classify by title keyword matching
                if _is_ml_article(candidate.title):
                    pools.add("ml")
                else:
                    # Still require the title to be AI-related for the AI pool
                    if _is_ai_story(candidate.title):
                        pools.add("ai")
        return pools or set()  # empty → will be excluded from both pools

    ml_candidates = [c for c in candidates if "ml" in _candidate_streams(c)]
    ai_candidates = [c for c in candidates if "ai" in _candidate_streams(c)]

    logger.info(
        "Pool split: %d ML candidates, %d AI candidates (from %d deduplicated)",
        len(ml_candidates),
        len(ai_candidates),
        total_after_dedupe,
    )

    # ── 5. Score ML pool ─────────────────────────────────────────────────────
    scoring_cfg = cfg.get("scoring", {})
    ml_weight_kwargs = {
        k: float(v)
        for k, v in scoring_cfg.items()
        if isinstance(v, (int, float)) and k != "diversity_cap"
    }
    ml_weights = ScoringWeights(**ml_weight_kwargs) if ml_weight_kwargs else ScoringWeights()
    ml_diversity_cap = int(scoring_cfg.get("diversity_cap", 0))
    ml_scorer = AIMLScorer(weights=ml_weights, diversity_cap=ml_diversity_cap)
    ml_scored = ml_scorer.score_and_rank(ml_candidates, top_n=top_n)

    if len(ml_scored) < top_n:
        generation_notes.append(
            f"Only {len(ml_scored)} ML items met the quality threshold "
            f"(target: {top_n}). The ML list will display fewer entries."
        )

    # ── 6. Score AI pool — excluding ML top-N ────────────────────────────────
    ml_top_ids = {c.id for c, _, _ in ml_scored}
    ai_candidates_deduped = [c for c in ai_candidates if c.id not in ml_top_ids]
    logger.info(
        "AI pool after ML exclusion: %d candidates (removed %d overlap)",
        len(ai_candidates_deduped),
        len(ai_candidates) - len(ai_candidates_deduped),
    )

    ai_scoring_cfg = cfg.get("scoring_ai", {})
    ai_weight_kwargs = {
        k: float(v)
        for k, v in ai_scoring_cfg.items()
        if isinstance(v, (int, float)) and k != "diversity_cap"
    }
    ai_weights = (
        ScoringWeights(**ai_weight_kwargs)
        if ai_weight_kwargs
        else ScoringWeights(
            recency=0.25,
            source_credibility=0.22,
            corroboration=0.28,
            severity=0.13,
            breadth=0.08,
            actionability=0.04,
        )
    )
    ai_diversity_cap = int(ai_scoring_cfg.get("diversity_cap", 0))
    ai_scorer = AIMLScorer(weights=ai_weights, diversity_cap=ai_diversity_cap)
    ai_scored = ai_scorer.score_and_rank(ai_candidates_deduped, top_n=top_n)

    if len(ai_scored) < top_n:
        generation_notes.append(
            f"Only {len(ai_scored)} AI items met the quality threshold "
            f"(target: {top_n}). The AI list will display fewer entries."
        )

    # ── 7. Enrich ────────────────────────────────────────────────────────────
    enrichment_cfg = cfg.get("enrichment", {})
    enricher = AIMLEnricher(
        max_summary_words=int(enrichment_cfg.get("max_summary_words", 80))
    )

    ml_threats = []
    for candidate, score, breakdown in ml_scored:
        threat = enricher.enrich(candidate, score, breakdown)
        ml_threats.append(threat)

    ai_threats = []
    for candidate, score, breakdown in ai_scored:
        threat = enricher.enrich(candidate, score, breakdown)
        ai_threats.append(threat)

    # ── 8. Package output ────────────────────────────────────────────────────
    # Reuse ThreatLandscapeOutput: threats = ML, mainstream_threats = AI.
    # The template maps these to the "ML" and "AI" view tabs respectively.
    landscape = ThreatLandscapeOutput(
        generated_at=datetime.now(tz=timezone.utc),
        threats=ml_threats,
        mainstream_threats=ai_threats,
        total_items_collected=total_collected,
        total_items_after_dedupe=total_after_dedupe,
        generation_notes=generation_notes,
        sources_queried=[
            SourceSummary(
                name=s.name,
                credibility=s.credibility,
                tags=s.tags,
                rationale=s.rationale,
                stream=s.stream,
            )
            for s in sources
            if s.enabled
        ],
    )

    # ── 9. Render ────────────────────────────────────────────────────────────
    branding = cfg.get("branding", {})
    renderer = AIMLRenderer(
        template_dir=template_dir,
        output_dir=output_dir,
        static_dir=static_dir,
        branding=branding,
    )
    paths = renderer.render_all(landscape)

    # Override app.js and inject theme.css from aiml/static/
    _aiml_static = _PROJECT_ROOT / "aiml" / "static"
    for _fname in ("app.js", "theme.css"):
        _src = _aiml_static / _fname
        _dst = output_dir / "static" / _fname
        if _src.exists():
            shutil.copy2(str(_src), str(_dst))
            logger.info("AI/ML %s applied to %s", _fname, _dst)
        else:
            logger.warning("AI/ML %s not found at %s; skipping.", _fname, _src)

    click.echo(
        f"Build complete — {len(ml_threats)} ML item(s), {len(ai_threats)} AI item(s).\n"
        f"  HTML : {paths.get('html')}\n"
        f"  JSON : {paths.get('json')}\n"
        f"\nRun 'preview' to view locally:\n"
        f"  python -m src.aiml_main preview\n"
        f"  -> http://localhost:8081"
    )


if __name__ == "__main__":
    cli()

#!/usr/bin/env python3
"""The Observability Index — recompute the living index of LLM / AI observability tooling from
live GitHub signals, and write data.json + SEO (sitemap, rss, robots, llms.txt).

Scope = the control room for shipped AI: LLM & agent tracing, monitoring & cost/latency
analytics, online evaluation & scoring, agent observability, and ML / data-drift monitoring.
TOOLS that watch AI in production — not the apps themselves. Deliberately excludes, to stay
distinct from the sibling indexes: offline eval / benchmark frameworks (-> The Eval Index),
prompt libraries (-> The Prompt Index), LLM gateways / proxies (-> The Gateway Index), agent
frameworks (-> The Agent Index), general-purpose APM / infra observability (OpenTelemetry,
Grafana, Prometheus, Jaeger, SigNoz), and experiment-tracking / model-serving MLOps (MLflow,
W&B, vLLM). Gathered, deduped, FILTERED (precision over recall), categorized, scored.

Only the GitHub *search* payload is used. Env: GITHUB_TOKEN (required for a usable rate limit).
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.github.com"
SITE_URL = "https://observability.kymatalabs.com"   # fixed to the real alias after first deploy
SITE_NAME = "The Observability Index"

QUERIES = [
    "topic:llm-observability stars:>12",
    "topic:llmops stars:>40",
    "topic:llm-monitoring stars:>12",
    "topic:ai-observability stars:>12",
    "topic:model-monitoring stars:>40",
    "topic:ml-monitoring stars:>60",
    "topic:model-observability stars:>12",
    "topic:agent-observability stars:>8",
    "topic:llm-evaluation stars:>150",   # obs+eval platforms; eval-only frameworks denied by name
    "topic:observability stars:>500",    # broad infra — filtered hard to AI by is_obs/_DENY/_ANTI
    "llm observability in:name,description stars:>35",
    "llm monitoring in:name,description stars:>35",
    "llm tracing in:name,description stars:>35",
    "llmops in:name,description stars:>50",
    "agent observability in:name,description stars:>20",
    "prompt analytics in:name,description stars:>20",
    "model monitoring in:name,description stars:>80",
    "data drift in:name,description stars:>120",
    "ml observability in:name,description stars:>35",
]


def token() -> str:
    return (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()


HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "observability-index"}
if token():
    HEADERS["Authorization"] = f"Bearer {token()}"

# Strong, AI-specific topics → auto-allow (these don't bleed from general infra).
_OBS_TOPICS = {"llm-observability", "llmops", "llm-ops", "ai-observability", "llm-monitoring",
               "model-monitoring", "model-observability", "ml-monitoring", "ml-observability",
               "agent-observability", "genai-observability", "prompt-monitoring", "llm-tracing",
               "llm-analytics", "ai-monitoring", "model-drift", "data-drift", "drift-detection",
               "llm-evals", "prompt-analytics", "agent-monitoring"}

# Require an AI term ADJACENT to an observability term (or "obs for/of AI"). General APM/infra
# ("distributed tracing", "metrics platform") never names the model next to the verb, so it
# won't match — while AI-native tools ("monitor your LLM", "agent tracing") will.
_AI = r"(?:llm|llms|ai|genai|gen[\s-]?ai|agent|agents|agentic|model|models|prompt|prompts|rag|gpt|chatbot|generative)"
_OBS = r"(?:observ\w*|monitor\w*|tracing|trace\w*|telemetry|analytics|evaluat\w*|scoring|drift|tracking|debugg?\w*)"
_OBS_PHRASES = re.compile(
    rf"\b{_AI}[\s-]?{_OBS}\b"
    rf"|\b{_OBS}\s+(?:for|of|your|every|all)\s+(?:your\s+)?{_AI}\b"
    rf"|\bllm[\s-]?ops\b|\bllmops\b"
    rf"|\b(?:data|model|concept|feature)\s+drift\b|\bdrift detection\b"
    rf"|\bproduction\s+(?:monitoring|observability|evaluation)\b"
    rf"|\bhallucination (?:detection|monitoring)\b",
    re.I)

# Marquee observability tools — guaranteed in, bypassing _ANTI. Critical because several
# (OpenLLMetry, Langtrace, OpenInference, Phoenix) describe themselves as "OpenTelemetry-based",
# which the infra filters below would otherwise wrongly reject. Lowercased full_name.
_ALLOW = {
    "langfuse/langfuse", "helicone/helicone", "arize-ai/phoenix", "traceloop/openllmetry",
    "comet-ml/opik", "lunary-ai/lunary", "scale3-labs/langtrace", "lmnr-ai/lmnr",
    "langwatch/langwatch", "agentops-ai/agentops", "pydantic/logfire", "evidentlyai/evidently",
    "whylabs/whylogs", "nannyml/nannyml", "agenta-ai/agenta", "arize-ai/openinference",
    "uptrain-ai/uptrain", "deepchecks/deepchecks", "truera/trulens", "seldonio/alibi-detect",
    "parea-ai/parea-sdk-py", "phospho-app/phospho", "langtrace/langtrace",
}

# Lowercased full_name. General APM/infra observability, offline eval frameworks, MLOps
# experiment-tracking / serving (reserved for a future index), gateways, and product/web analytics.
_DENY = {
    # general APM / infra observability (NOT AI-specific)
    "open-telemetry/opentelemetry-python", "open-telemetry/opentelemetry-collector",
    "open-telemetry/opentelemetry-js", "open-telemetry/opentelemetry-go",
    "open-telemetry/opentelemetry-collector-contrib", "open-telemetry/opentelemetry-demo",
    "open-telemetry/opentelemetry-dotnet", "open-telemetry/opentelemetry-java",
    "grafana/grafana", "grafana/loki", "grafana/tempo", "grafana/mimir", "grafana/k6",
    "grafana/faro-web-sdk", "prometheus/prometheus", "prometheus/node_exporter",
    "jaegertracing/jaeger", "signoz/signoz", "openobserve/openobserve", "hyperdxio/hyperdx",
    "getsentry/sentry", "elastic/elasticsearch", "netdata/netdata", "vectordotdev/vector",
    "uptrace/uptrace", "victoriametrics/victoriametrics", "influxdata/influxdb",
    "apache/skywalking", "pixie-io/pixie", "parca-dev/parca", "coroot/coroot",
    "highlight/highlight", "checkmk/checkmk", "zabbix/zabbix", "cabotapp/cabot",
    "openzipkin/zipkin", "naver/pinpoint", "middleware-labs/integration",
    # offline eval / benchmark frameworks (-> The Eval Index)
    "confident-ai/deepeval", "explodinggradients/ragas", "promptfoo/promptfoo",
    "eleutherai/lm-evaluation-harness", "openai/evals", "stanford-crfm/helm",
    "giskard-ai/giskard", "open-compass/opencompass", "huggingface/lighteval",
    "fchollet/arc-agi", "vectara/hallucination-leaderboard",
    # MLOps experiment-tracking / serving (reserved future index)
    "mlflow/mlflow", "wandb/wandb", "aimhubio/aim", "iterative/dvc", "zenml-io/zenml",
    "netflix/metaflow", "kubeflow/kubeflow", "bentoml/bentoml", "vllm-project/vllm",
    "ray-project/ray", "determined-ai/determined", "allegroai/clearml", "kserve/kserve",
    "mlrun/mlrun", "polyaxon/polyaxon", "tensorflow/tensorboard", "lakefs/lakefs",
    # gateways (-> The Gateway Index)
    "berriai/litellm", "portkey-ai/gateway", "portkey-ai/portkey-python-sdk",
    # product / web analytics, not AI obs
    "posthog/posthog", "plausible/analytics", "umami-software/umami", "matomo-org/matomo",
    # --- tightening pass 1 (confirmed bleed from top-40 audit) ---
    # LLM-app / agent frameworks, agent platforms, RAG frameworks (-> The Agent Index / app tier)
    "pathwaycom/llm-app", "composiohq/composio", "voltagent/voltagent", "0xplaygrounds/rig",
    "mnfst/manifest", "katanemo/plano", "googlecloudplatform/agent-starter-pack",
    "coze-dev/coze-loop", "shyftlabs/continuum", "memodb-io/acontext", "dataelement/bisheng",
    "marker-inc-korea/autorag", "juanjuandog/finsight-ai", "darkrishabh/agent-skills-eval",
    "justin0504/aegis",
    # courses / books / tutorial collections
    "liguodongiot/llm-action", "datatalksclub/mlops-zoomcamp",
    "packtpublishing/llm-engineers-handbook", "decodingai-magazine/llm-twin-course",
    # model serving / MLOps platforms (reserved future index)
    "bentoml/openllm", "clearml/clearml", "tencentmusic/cube-studio", "polyaxon/traceml",
    # gateways (-> The Gateway Index)
    "maximhq/bifrost",
    # eval / testing frameworks (-> The Eval Index)
    "giskard-ai/giskard-oss",
    # general infra observability database
    "greptimeteam/greptimedb",
    # --- tightening pass 2 ---
    "vibrantlabsai/ragas",                       # RAGAS relocated org — offline eval (-> Eval Index)
    "truefoundry/cognita",                       # RAG framework (-> RAG Index)
    "bitrouter/bitrouter",                       # LLM router (-> Gateway Index)
    "aminedjeghri/generative-ai-project",        # project template
    "spring-ai-community/spring-ai-playground",  # agent-tool execution layer
    "taishan666/maxkb4j",                        # knowledge-base app platform
    "collieai/llm-firewall", "pegasi-ai/reins",  # pure guardrails/safety (-> a future Guardrails Index)
}

# name+desc regex — catches the long tail of non-AI monitoring/analytics, MLOps serving, and
# list/tutorial repos that slip past topic/phrase matching. Deliberately does NOT name
# OpenTelemetry/Kubernetes (legit AI-obs tools build on them) — those are handled by _DENY.
_ANTI = re.compile(
    r"\b(awesome|curated list|cheat ?sheet|tutorial|roadmap|paper[- ]?(list|survey)|reading list"
    r"|interview questions|book\b"
    r"|infrastructure monitoring|server monitoring|network monitoring|uptime monitor\w*"
    r"|website monitor\w*|synthetic monitoring|real[- ]user monitoring|web analytics|product analytics"
    r"|log management|log aggregat\w*|time[- ]?series (database|db)|metrics database|status page"
    r"|incident (management|response)|on[- ]call\b|alerting platform"
    r"|experiment tracking|model registry|model serving|model deployment|inference (server|engine)"
    r"|feature store|vector (database|db|store)|stable diffusion|image generation|chatgpt clone"
    r"|course|bootcamp|handbook|zoomcamp|study (guide|plan)|practical guide"
    r"|ready[- ]to[- ]run|starter (pack|kit|template)|boilerplate"
    r"|agent (framework|runtime|orchestrat\w*)|(?:build|ship|create)\b.{0,28}(?:llm|ai) app"
    r"|\bai gateway\b|\bllm gateway\b|\bllm proxy\b|\bllm router\b|memory layer"
    r"|retrieval[- ]augmented generation|\brag framework\b|\btemplate for\b"
    r"|self[- ]driving|autonomous driving|business intelligence)\b",
    re.I)


def gh(url: str, *, retries: int = 4):
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 429):
                reset = e.headers.get("X-RateLimit-Reset")
                wait = 5 * (attempt + 1)
                if reset:
                    try:
                        wait = max(wait, min(60, int(reset) - int(time.time()) + 2))
                    except ValueError:
                        pass
                print(f"  rate-limited — sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            if 500 <= e.code < 600:
                time.sleep(3 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            time.sleep(3 * (attempt + 1))
    if last:
        raise last
    raise RuntimeError(f"gh failed: {url}")


def search(q: str, per_page: int = 40) -> list[dict]:
    url = (f"{API}/search/repositories?q={urllib.parse.quote(q)}"
           f"&sort=stars&order=desc&per_page={per_page}")
    try:
        return gh(url).get("items", [])
    except Exception as e:
        print(f"  query failed [{q}]: {e}", file=sys.stderr)
        return []


def is_obs(r: dict) -> bool:
    full = (r.get("full_name") or "").lower()
    if full in _DENY:
        return False
    if full in _ALLOW:
        return True
    name = r.get("name") or ""
    desc = r.get("description") or ""
    if _ANTI.search(f"{name} {desc}"):
        return False
    topics = {t.lower() for t in (r.get("topics") or [])}
    if topics & _OBS_TOPICS:
        return True
    return bool(_OBS_PHRASES.search(f"{name} {desc}"))


def categorize(r: dict) -> str:
    topics = {t.lower() for t in (r.get("topics") or [])}
    blob = f"{(r.get('name') or '').lower()} {(r.get('description') or '').lower()} {' '.join(topics)}"
    # most-specific first. "agent" alone is too common (most platforms mention it) — Agent
    # Observability requires agent-OBSERVABILITY phrasing, not a passing mention of agents.
    if re.search(r"\bdrift\b|data quality|\boutlier\b|anomaly detect|nannyml|evidently|whylogs"
                 r"|alibi|deepchecks|data validation|distribution shift|\bml monitoring\b", blob):
        return "Drift & ML Monitoring"
    if re.search(r"agentops|agent[- ]?observability|agent (monitoring|tracing|telemetry|analytics)"
                 r"|coding agent|claude[- ]?code|agent (run|session|trajector)", blob):
        return "Agent Observability"
    if re.search(r"\btrac(e|es|ing)\b|\bspans?\b|opentelemetry|\botel\b|instrument(ation)?"
                 r"|openinference|openllmetry|distributed trac", blob):
        return "Tracing & Spans"
    if re.search(r"evaluat|\bscoring\b|llm[- ]?judge|guardrail|hallucination|uncertainty"
                 r"|answer quality|online eval|\bgrading\b|\bfeedback\b", blob):
        return "Online Evaluation"
    if re.search(r"\bcost\b|latency|token (usage|count|cost)|dashboard|\busage\b|spend|metrics"
                 r"|monitor|analytics|telemetry|prompt management", blob):
        return "Monitoring & Analytics"
    return "LLMOps Platforms"


def days_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds() / 86400.0
    except ValueError:
        return None


def momentum(r: dict, max_stars: int) -> int:
    stars = r.get("stargazers_count", 0) or 0
    star_norm = math.log10(stars + 1) / math.log10(max(max_stars, 10) + 1)
    pushed = days_since(r.get("pushed_at"))
    recency = 0.2 if pushed is None else max(0.0, 1.0 - max(0.0, pushed) / 180.0)
    created = days_since(r.get("created_at"))
    young = (1.0 - created / 120.0) if (created is not None and created < 120 and stars >= 20) else 0.0
    return max(1, min(100, round((0.55 * star_norm + 0.32 * recency + 0.13 * young) * 100)))


def slugify(full_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", full_name.lower()).strip("-")


def build_items() -> list[dict]:
    seen: dict[str, dict] = {}
    for q in QUERIES:
        for r in search(q):
            full = r.get("full_name")
            if full and full not in seen and is_obs(r):
                seen[full] = r
        time.sleep(0.7)
    raw = list(seen.values())
    max_stars = max((r.get("stargazers_count", 0) or 0) for r in raw) if raw else 10
    items = []
    for r in raw:
        owner = r.get("owner") or {}
        items.append({
            "name": r.get("name", ""), "full_name": r.get("full_name", ""),
            "slug": slugify(r.get("full_name", "")), "url": r.get("html_url", ""),
            "owner": owner.get("login", ""), "owner_avatar": owner.get("avatar_url", ""),
            "stars": r.get("stargazers_count", 0) or 0, "forks": r.get("forks_count", 0) or 0,
            "open_issues": r.get("open_issues_count", 0) or 0, "language": r.get("language") or "",
            "license": ((r.get("license") or {}) or {}).get("spdx_id") or "",
            "pushed_at": r.get("pushed_at"), "created_at": r.get("created_at"),
            "description": (r.get("description") or "").strip(), "topics": r.get("topics") or [],
            "category": categorize(r), "momentum": momentum(r, max_stars),
        })
    items.sort(key=lambda x: (x["momentum"], x["stars"]), reverse=True)
    for i, it in enumerate(items, 1):
        it["rank"] = i
    return items


def write_json(items: list[dict]) -> dict:
    cats: dict[str, int] = {}
    for it in items:
        cats[it["category"]] = cats.get(it["category"], 0) + 1
    data = {"generated_at": datetime.now(timezone.utc).isoformat(), "count": len(items),
            "categories": [{"name": k, "count": v} for k, v in sorted(cats.items(), key=lambda x: -x[1])],
            "items": items}
    with open(os.path.join(HERE, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return data


def write_seo(data: dict) -> None:
    items = data["items"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls = [f"  <url><loc>{SITE_URL}/</loc><lastmod>{now}</lastmod><changefreq>daily</changefreq><priority>1.0</priority></url>"]
    for it in items:
        urls.append(f"  <url><loc>{SITE_URL}/p/{it['slug']}/</loc><lastmod>{now}</lastmod>"
                    f"<changefreq>weekly</changefreq><priority>0.6</priority></url>")
    open(os.path.join(HERE, "sitemap.xml"), "w", encoding="utf-8").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls) + "\n</urlset>\n")
    open(os.path.join(HERE, "robots.txt"), "w", encoding="utf-8").write(
        f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")

    def esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    rss_items = [
        f"    <item><title>{esc(it['full_name'])} — momentum {it['momentum']}</title>"
        f"<link>{SITE_URL}/p/{it['slug']}/</link><guid isPermaLink=\"false\">{esc(it['full_name'])}</guid>"
        f"<description>{esc(it['description'][:300])}</description></item>" for it in items[:30]]
    open(os.path.join(HERE, "rss.xml"), "w", encoding="utf-8").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0">\n  <channel>\n'
        f"    <title>{SITE_NAME}</title>\n    <link>{SITE_URL}</link>\n"
        "    <description>The living index of LLM &amp; AI observability tooling — tracing, monitoring, online evaluation, agent observability, and ML-drift detection.</description>\n"
        + "\n".join(rss_items) + "\n  </channel>\n</rss>\n")

    lines = [f"# {SITE_NAME}", "",
             "> The living index of LLM & AI observability tooling — LLM & agent tracing, monitoring &",
             "> analytics, online evaluation, agent observability, and ML / data-drift detection —",
             "> ranked daily by GitHub momentum.", "",
             f"Updated: {data['generated_at']}", f"Tools indexed: {data['count']}", "",
             "## Top LLM & AI observability tools by momentum", ""]
    for it in items[:40]:
        lines.append(f"- [{it['full_name']}]({it['url']}) — momentum {it['momentum']}, "
                     f"⭐{it['stars']} — {it['category']} — {it['description'][:100]}")
    open(os.path.join(HERE, "llms.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


def main() -> int:
    if not token():
        print("WARNING: no GITHUB_TOKEN — low rate limit, partial results", file=sys.stderr)
    items = build_items()
    if not items:
        print("ERROR: no observability tools found — refusing to write empty data.json", file=sys.stderr)
        return 1
    data = write_json(items)
    write_seo(data)
    print(f"wrote data.json: {len(items)} observability tools across {len(data['categories'])} categories")
    print("  top 5:", ", ".join(f"{it['full_name']}({it['momentum']})" for it in items[:5]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

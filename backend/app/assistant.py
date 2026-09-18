"""Workspace assistant: Claude answers questions about one project, grounded in that project's own data.

The context is built fresh for every request from what the project actually holds: the uploaded boundary
(KML/KMZ/GeoJSON) or GeoTIFF, every run and its parameters, the viewed run's numbers, pipeline stages,
crown statistics, warnings, validation marks, the method and the limitations. Claude never sees the
imagery pixels, so it is told to say when a question needs them.

Two tools:
  find_crowns     read-only query over the run's crowns (filter, sort, limit)
  propose_rerun   suggests new parameters; the UI shows an "Apply and run" card, the user decides

The endpoint streams Server-Sent Events: text / action / tool / done / error.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Iterator

import numpy as np

from .pipeline import LIMITATIONS_MD, geo, ingest
from .projects import store as projects

MODEL = "claude-opus-5"
MAX_TOOL_TURNS = 4
MAX_HISTORY_MESSAGES = 40
METHOD_MD = Path(__file__).resolve().parents[2] / "docs" / "METHOD.md"

SYSTEM_PROMPT = """You are Canopy AI, the assistant inside one CANOPY workspace. CANOPY finds tree crowns in \
aerial or satellite imagery and measures canopy cover, and it is strict about what it can and cannot measure.

You answer questions about this workspace only, using the workspace context below: its boundary file, its runs, \
the numbers each run produced, the pipeline stages, and the method and limitations documents. \
Latency-sensitive; begin your visible answer immediately.

How to answer:
- Ground every number in the context and name where it comes from (for example "run #3, confidence breakdown"). \
If the context does not contain something, say so plainly. Never invent crown counts, areas, heights, dates or \
species.
- You cannot see the imagery pixels. When a question needs them (species, health, "is that a tree or a bush"), \
say what the numbers suggest and point the user to the Map, Pipeline or Validation tab to check.
- CANOPY does not estimate carbon, biomass or credits. If asked, explain why using the limitations document, and \
say what CANOPY does measure instead.
- When the user wants a better result, reason from the run's warnings, parameters and pipeline numbers, then \
call propose_rerun with concrete parameters and a one-sentence reason. The user applies it; you never claim a \
rerun has happened.
- Use find_crowns for questions about specific crowns (largest, lowest confidence, near the edge).
- Keep answers short: a direct answer first, then at most a few bullets. Use **bold** for the key number. \
Write for a forestry analyst, not a programmer."""

TOOLS = [
    {
        "name": "find_crowns",
        "description": (
            "Query the crowns of the run being viewed. Returns matching crowns with id, centroid (lon, lat), area, "
            "diameter, confidence and its reason, and whether the crown touches the boundary. Use it for questions "
            "about particular crowns, e.g. the largest ones or the low-confidence ones."
        ),
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "confidence": {"type": "string", "enum": ["any", "high", "medium", "low"]},
                "min_diameter_m": {"type": "number"},
                "max_diameter_m": {"type": "number"},
                "touches_edge": {"type": "boolean"},
                "sort_by": {"type": "string", "enum": ["area_desc", "area_asc", "confidence_asc", "confidence_desc", "id"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            "required": ["sort_by", "limit"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_rerun",
        "description": (
            "Propose running the analysis again with changed parameters. The user sees the change and a button to "
            "apply it; nothing runs until they click. Only include parameters you want to change."
        ),
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "One sentence: why this should give a better result."},
                "detector": {"type": "string", "enum": ["hybrid", "classical"]},
                "min_crown_diameter_m": {"type": "number", "minimum": 1, "maximum": 20},
                "veg_index": {"type": "string", "enum": ["exg", "vari", "ndvi"]},
                "threshold_mode": {"type": "string", "enum": ["otsu", "manual"]},
                "threshold_manual": {"type": "number", "minimum": -1, "maximum": 1},
                "tile_zoom": {"type": "integer", "enum": [18, 19]},
                "enable_height": {"type": "boolean"},
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
]
PARAM_KEYS = ("detector", "min_crown_diameter_m", "veg_index", "threshold_mode", "threshold_manual", "tile_zoom", "enable_height")


class AssistantError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def api_key() -> str | None:
    """backend/.env wins over the shell, so a stray ANTHROPIC_API_KEY from another tool cannot shadow it."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "ANTHROPIC_API_KEY" and v.strip():
                return v.strip().strip('"').strip("'")
    return os.environ.get("ANTHROPIC_API_KEY") or None


def available() -> tuple[bool, str | None]:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "The anthropic package is not installed on the server (pip install anthropic)."
    key = api_key()
    if not key:
        return False, "No Anthropic API key on the server. Put ANTHROPIC_API_KEY=sk-ant-... in backend/.env and restart the API."
    if not key.startswith("sk-ant-"):
        return False, "The server's ANTHROPIC_API_KEY is not an Anthropic key (they start with sk-ant-). Put the right key in backend/.env and restart the API."
    return True, None


# ---- context -------------------------------------------------------------------------------------------


def _q(values: list[float]) -> dict | None:
    if not values:
        return None
    a = np.asarray(values, dtype=float)
    return {k: round(float(np.percentile(a, p)), 2) for k, p in (("min", 0), ("p10", 10), ("median", 50), ("p90", 90), ("max", 100))}


def _boundary(project: dict) -> dict:
    """What the uploaded boundary or GeoTIFF is, from its own bytes."""
    out: dict = {"kind": project["source"]["kind"], "file": project["source"]["name"], "bytes": project["source"]["bytes"]}
    try:
        parsed = projects.parsed_input(project["id"])
    except Exception as exc:  # the project must still be discussable if its source fails to re-parse
        out["parse_error"] = str(exc)
        return out
    if parsed.raster_bytes is None and parsed.filename:
        try:
            src = projects.projects_dir / project["id"] / "source" / Path(parsed.filename).name
            _, feats = ingest.read_features(parsed.filename, src.read_bytes())
            out["features_in_file"] = len(feats)
            out["feature_names"] = [f.name for f in feats[:20] if getattr(f, "name", None)]
        except Exception:
            pass
    g = parsed.aoi_lonlat
    if g is not None:
        c = g.centroid
        w, s, e, n = g.bounds
        out.update({
            "area_ha": round(geo.polygon_area_m2(g) / 1e4, 3),
            "centroid_lonlat": [round(c.x, 6), round(c.y, 6)],
            "bbox_wsen": [round(v, 6) for v in (w, s, e, n)],
            "extent_m": [round((e - w) * 111_320 * math.cos(math.radians(c.y))), round((n - s) * 110_540)],
            "vertices": sum(len(p.exterior.coords) for p in getattr(g, "geoms", [g])),
            "parts": len(getattr(g, "geoms", [g])),
            "utm_epsg": geo.utm_epsg(c.x, c.y),
        })
    return out


def _crowns(run_dir: Path) -> list[dict]:
    f = run_dir / "crowns.geojson"
    if not f.exists():
        return []
    return [feat["properties"] for feat in json.loads(f.read_text(encoding="utf-8"))["features"]]


def _crown_stats(crowns: list[dict]) -> dict:
    if not crowns:
        return {"count": 0}
    reasons: dict[str, int] = {}
    for c in crowns:
        if c.get("low_confidence_reason"):
            reasons[c["low_confidence_reason"]] = reasons.get(c["low_confidence_reason"], 0) + 1
    return {
        "count": len(crowns),
        "diameter_m": _q([c["equivalent_diameter_m"] for c in crowns]),
        "area_m2": _q([c["area_m2"] for c in crowns]),
        "confidence": _q([c["confidence"] for c in crowns]),
        "detector_score": _q([c["detector_score"] for c in crowns if c.get("detector_score") is not None]),
        "height_m": _q([c["height_m"] for c in crowns if c.get("height_m") is not None]),
        "touching_boundary": sum(1 for c in crowns if c.get("touches_edge")),
        "low_confidence_reasons": reasons,
        "largest_5": [{"id": c["id"], "area_m2": c["area_m2"], "lonlat": c["centroid_lonlat"]}
                      for c in sorted(crowns, key=lambda c: -c["area_m2"])[:5]],
    }


def build_context(project_id: str, run_id: str | None) -> tuple[str, Path | None]:
    project = projects.get(project_id)
    if project is None:
        raise AssistantError("not_found", "Project not found.", 404)
    runs = project.get("runs", [])
    run_id = run_id or project.get("latest_succeeded_run_id")
    viewed = next((r for r in runs if r["id"] == run_id), None)
    loaded = projects.load_result(run_id) if run_id else None

    ctx: dict = {
        "workspace": {"name": project["name"], "created_utc": project["created_utc"], "boundary_or_image": _boundary(project)},
        "runs": [
            {"number": r["number"], "status": r["status"], "created_utc": r["created_utc"], "params": r["params"],
             "summary": r["summary"], "error": r["error_message"]}
            for r in runs
        ],
    }
    run_dir = None
    if loaded:
        result, run_dir = loaded
        ctx["viewed_run"] = {
            "number": viewed["number"] if viewed else None,
            "is_latest": run_id == project.get("latest_succeeded_run_id"),
            "summary": {k: v for k, v in result["summary"].items() if k != "heights_m"},
            "provenance": result["provenance"],
            "warnings": result["warnings"],
            "pipeline": [
                {"stage": s["title"], "headline": s["headline"], "numbers": s["stats"]}
                for s in (result.get("pipeline") or {}).get("stages", [])
            ],
            "detector_used": (result.get("pipeline") or {}).get("detector_label"),
            "crowns": _crown_stats(_crowns(run_dir)),
        }
        manifest = run_dir / "manifest.json"
        if manifest.exists():
            m = json.loads(manifest.read_text(encoding="utf-8"))
            ctx["viewed_run"]["segmentation"] = {k: v for k, v in m.get("segmentation", {}).items() if not k.startswith("_")}
        validation = run_dir / "validation.json"
        if validation.exists():
            ctx["viewed_run"]["validation"] = json.loads(validation.read_text(encoding="utf-8"))
    else:
        ctx["viewed_run"] = None

    method = METHOD_MD.read_text(encoding="utf-8") if METHOD_MD.exists() else ""
    text = (
        "<workspace_context>\n" + json.dumps(ctx, indent=1, sort_keys=True, default=str) + "\n</workspace_context>\n\n"
        "<method>\n" + method + "\n</method>\n\n<limitations>\n" + LIMITATIONS_MD + "\n</limitations>"
    )
    return text, run_dir


# ---- tools -------------------------------------------------------------------------------------------


def _find_crowns(run_dir: Path | None, args: dict) -> str:
    if run_dir is None:
        return json.dumps({"error": "This workspace has no finished run yet."})
    crowns = _crowns(run_dir)
    conf = args.get("confidence", "any")
    if conf != "any":
        crowns = [c for c in crowns if c["confidence_bucket"] == conf]
    if "min_diameter_m" in args:
        crowns = [c for c in crowns if c["equivalent_diameter_m"] >= float(args["min_diameter_m"])]
    if "max_diameter_m" in args:
        crowns = [c for c in crowns if c["equivalent_diameter_m"] <= float(args["max_diameter_m"])]
    if "touches_edge" in args:
        crowns = [c for c in crowns if bool(c["touches_edge"]) == bool(args["touches_edge"])]
    key = {"area_desc": lambda c: -c["area_m2"], "area_asc": lambda c: c["area_m2"],
           "confidence_asc": lambda c: c["confidence"], "confidence_desc": lambda c: -c["confidence"],
           "id": lambda c: c["id"]}[args["sort_by"]]
    total = len(crowns)
    rows = [
        {"id": c["id"], "lonlat": c["centroid_lonlat"], "area_m2": c["area_m2"], "diameter_m": c["equivalent_diameter_m"],
         "confidence": c["confidence"], "bucket": c["confidence_bucket"], "reason": c.get("low_confidence_reason"),
         "touches_edge": c["touches_edge"], "height_m": c.get("height_m")}
        for c in sorted(crowns, key=key)[: int(args["limit"])]
    ]
    return json.dumps({"matching": total, "returned": len(rows), "crowns": rows})


def _valid(name: str, args) -> bool:
    if not isinstance(args, dict):
        return False
    if name == "find_crowns":
        return args.get("sort_by") in ("area_desc", "area_asc", "confidence_asc", "confidence_desc", "id") and isinstance(args.get("limit"), int)
    if name == "propose_rerun":
        return isinstance(args.get("reason"), str) and any(k in args for k in PARAM_KEYS)
    return False


# ---- chat ------------------------------------------------------------------------------------------------


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _clean_history(messages: list[dict]) -> list[dict]:
    """Plain-text turns only, alternating, starting and ending with the user. Anything else is dropped."""
    out: list[dict] = []
    for m in messages[-MAX_HISTORY_MESSAGES:]:
        role, content = m.get("role"), m.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            continue
        content = content[:8000]
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n\n" + content
        else:
            out.append({"role": role, "content": content})
    while out and out[0]["role"] != "user":
        out.pop(0)
    if not out or out[-1]["role"] != "user":
        raise AssistantError("bad_messages", "Send at least one question.")
    return out


def stream_chat(project_id: str, run_id: str | None, messages: list[dict]) -> Iterator[str]:
    import anthropic

    history = _clean_history(messages)
    context, run_dir = build_context(project_id, run_id)
    client = anthropic.Anthropic(api_key=api_key())
    system = [
        {"type": "text", "text": SYSTEM_PROMPT},
        # The workspace context is stable across a conversation, so it is cached after the first question.
        {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}},
    ]
    convo: list = list(history)
    try:
        for _turn in range(MAX_TOOL_TURNS + 1):
            with client.beta.messages.stream(
                model=MODEL,
                max_tokens=16000,
                system=system,
                messages=convo,
                tools=TOOLS,
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
            ) as stream:
                for event in stream:
                    if event.type == "text":
                        yield _sse({"type": "text", "text": event.text})
                response = stream.get_final_message()

            if response.stop_reason == "refusal":
                yield _sse({"type": "error", "message": "Canopy AI declined to answer that. Try rephrasing the question about this workspace."})
                return
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses or response.stop_reason == "end_turn":
                break
            if response.stop_reason == "max_tokens":
                yield _sse({"type": "error", "message": "The answer was cut off. Ask a narrower question."})
                return

            results = []
            for block in tool_uses:
                args = block.input
                if not _valid(block.name, args):
                    results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                    "content": json.dumps({"INVALID_JSON": json.dumps(args, default=str)})})
                    continue
                if block.name == "find_crowns":
                    yield _sse({"type": "tool", "name": "find_crowns", "label": "Searching crowns"})
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": _find_crowns(run_dir, args)})
                else:
                    params = {k: args[k] for k in PARAM_KEYS if k in args}
                    if "threshold_manual" in params:
                        params["threshold_mode"] = "manual"
                    yield _sse({"type": "action", "params": params, "reason": args["reason"]})
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": "Shown to the user as a card with an 'Apply and run' button. It has not run."})
            convo.append({"role": "assistant", "content": response.content})
            convo.append({"role": "user", "content": results})
        yield _sse({"type": "done"})
    except anthropic.AuthenticationError:
        yield _sse({"type": "error", "message": "The server's Anthropic API key was rejected. Check ANTHROPIC_API_KEY."})
    except anthropic.RateLimitError:
        yield _sse({"type": "error", "message": "Canopy AI is rate limited right now. Try again in a few seconds."})
    except anthropic.APIStatusError as exc:
        yield _sse({"type": "error", "message": f"Canopy AI is unavailable ({exc.status_code}). Try again shortly."})
    except anthropic.APIConnectionError:
        yield _sse({"type": "error", "message": "The server could not reach Anthropic. Check its internet connection."})


def suggestions(project_id: str) -> list[str]:
    """Starter questions shaped by what this workspace actually holds."""
    project = projects.get(project_id)
    if project is None:
        raise AssistantError("not_found", "Project not found.", 404)
    kind = project["source"]["kind"]
    s = project.get("latest_summary") or {}
    out = ["Summarise this workspace in three lines"]
    if kind in ("kml", "kmz", "geojson", "drawn"):
        out.append("What does my boundary cover, and how was imagery fetched for it?")
    else:
        out.append("Is this GeoTIFF fine enough for the AI tree detector?")
    if s.get("confidence_breakdown", {}).get("low"):
        out.append("Why are some crowns low confidence?")
    else:
        out.append("Which crowns should I check by hand first?")
    out.append("How can I get a more accurate crown count here?")
    if len(project.get("runs", [])) > 1:
        out.append("What changed between my runs?")
    return out[:5]

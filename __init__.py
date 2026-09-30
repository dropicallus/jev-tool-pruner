"""jev-tool-pruner: begrenzt pro User-Task nur die benoetigten Tool-Schemas.

Nutzt lokales jeva.cpp (/v1/systemone, qwen3-4b): EIN Call pro Request beantwortet
fuer jedes Tool eine noul-Frage ("Braucht diese Aufgabe Tool X?"). Tools mit hoher
noul-Wahrscheinlichkeit bleiben, Rest wird aus request['tools'] entfernt -> weniger
Token-Ueberhead fuer Cloud/Lokal-Hauptmodell.

Fail-open: jev-Fehler, Router down, zu kleine Kataloge -> Original-Request lassen.
Safety: min_always (Whitelist) wird NIE entfernt; approval/Berechtigung unberuehrt.
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)


def _cfg(ctx):
    base = dict(ctx.get_config('config', {})) if hasattr(ctx, 'get_config') else {}
    return base


def _enabled(ctx):
    c = _cfg(ctx)
    return bool(c.get('enabled', False))


def _systemone_nouls(state_text, tool_names, router, model):
    """EIN /v1/systemone-Call -> {tool: noul} fuer jede Tool-Frage."""
    import httpx
    questions = {}
    for t in tool_names:
        questions[t] = {
            "type": "noul",
            "instructions": f"Braucht diese Aufgabe das Tool '{t}'?",
        }
    payload = {"model": model, "state": state_text, "questions": questions}
    r = httpx.post(router, json=payload, timeout=120)
    r.raise_for_status()
    answers = r.json().get("answers", {})
    return {t: (answers.get(t) or {}).get("noul", 0.0) for t in tool_names}


def _task_text(request):
    """Extrahiere die letzte User-Nachricht als Aufgabenbeschreibung."""
    if not isinstance(request, dict):
        return ""
    messages = request.get("messages")
    if isinstance(messages, list):
        for item in reversed(messages):
            if isinstance(item, dict) and item.get("role") == "user":
                c = item.get("content")
                if isinstance(c, str) and c.strip():
                    return c.strip()[:4000]
                if isinstance(c, list):
                    parts = [x.get("text") for x in c if isinstance(x, dict) and x.get("text")]
                    t = " ".join(p for p in parts if p)
                    if t.strip():
                        return t.strip()[:4000]
    return ""


def _tool_names_from(request):
    tools = request.get("tools")
    if not isinstance(tools, list):
        return []
    names = []
    for t in tools:
        if isinstance(t, dict):
            n = t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
            if isinstance(n, str) and n:
                names.append(n)
    return names


def _keep_by_name(request, keep_set, reason):
    tools = request.get("tools")
    if not isinstance(tools, list):
        return request
    kept = []
    removed = []
    for t in tools:
        n = None
        if isinstance(t, dict):
            n = t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        if n in keep_set:
            kept.append(t)
        else:
            removed.append(n)
    request = dict(request)
    request["tools"] = kept
    return request, {"removed": [r for r in removed if r], "kept_count": len(kept)}


def _make_pruner(ctx):
    c = _cfg(ctx)
    router = c.get("router", "http://127.0.0.1:8100/v1/systemone")
    model = c.get("model", "qwen3-4b")
    threshold = float(c.get("threshold", 0.5))
    always = set(c.get("min_always", []) or [])
    enabled = _enabled(ctx)

    def middleware(**kwargs):
        request = kwargs.get("request")
        if not enabled or not isinstance(request, dict):
            return None
        tool_names = _tool_names_from(request)
        if len(tool_names) < 2:
            return None
        task = _task_text(request)
        if not task:
            return None
        try:
            nouls = _systemone_nouls(task, tool_names, router, model)
        except Exception as e:
            log.warning("jev-tool-pruner fail-open (router): %s", e)
            return None
        keep = {t for t in tool_names if nouls.get(t, 0) >= threshold} | always
        pruned, meta = _keep_by_name(request, keep, "jev")
        if len(pruned.get("tools", [])) >= len(tool_names):
            return None  # nichts entfernt
        return {
            "request": pruned,
            "source": "jev-tool-pruner",
            "reason": f"task-tool-prune kept={meta['kept_count']}/{len(tool_names)} removed={meta['removed']}",
        }

    return middleware


def register(ctx):
    ctx.register_middleware("llm_request", _make_pruner(ctx))

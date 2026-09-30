# jev-tool-pruner

Begrenzt pro User-Task nur die **benoetigten Tool-Schemas** im ausgehenden LLM-Request —
gesteuert von einem lokalen Decision Model (jev / System One), nicht von Stichwort-Ranking.

Ein Agent sendet bei **jedem** Provider-Call den vollen Tool-Katalog mit. Bei 25 Tool-Schemas
sind das ~11.500 Tokens Overhead — pro Request, bevor ein einziges Antwort-Token erzeugt wurde.
Dieses Plugin fragt eine lokale jev-Instanz (`/v1/systemone`), welche Tools der aktuelle Task
wirklich braucht, und laesst die uebrigen Schemas aus dem Request weg.

## Warum jev statt Rank-based (BM25)

Ranking-Methoden matchen nur Stichworte (Tool-Name gegen Task-Text) und verstehen den Task
nicht. Ein Decision Model beantwortet in **einem** `/v1/systemone`-Call **eine noul-Frage je Tool**
("Braucht diese Aufgabe Tool X?") auf denselben Task — ein Prefill, ~1.200 Input-Tokens, kein
Reasoning-Overhead. Das liefert semantisch korrekte, Confidence-gewichtete Entscheidungen.

## Gemessene Ersparnis (lokal, jeva.cpp qwen3-4b)

| Task | Tools behalten | Token-Ersparnis |
|---|---|---|
| "Dateien geaendert auflisten" | 8/25 | **63 %** (11.505 → 4.297) |
| "Zusammenfassung ins Memory schreiben" | 6/25 | **72 %** (11.505 → 3.234) |
| "Wetter in Berlin" | 3/25 | **80 %** (11.505 → 2.269) |
| "Hallo" (Smalltalk) | 4/25 | **84 %** (11.505 → 1.848) |

Jev weist irrelevante Tools korrekt ab (z. B. `browser_exec`, `web_search`, `write_file` = 0.0 bei
einer Datei-Listen-Aufgabe) und behaelt die semantisch passenden (`terminal`, `search_files`).

## Sicherheit / Fail-open

- **Fail-open:** Router down, HTTP-Fehler oder jev-Antwort unlesbar → Original-Request, nichts wird entfernt.
- **Whitelist (`min_always`):** sicherheitskritische Tools werden NIE entfernt.
- **Kein Pruning bei <2 Tools** oder leerer Task-Extraktion.
- Approval-/Berechtigungspipeline bleibt unberuehrt — es werden nur Schemas entfernt, keine Rechte geaendert.

## Installation

```bash
# Verzeichnis-Plugin nach ~/.hermes/plugins/ klonen
git clone https://github.com/<owner>/jev-tool-pruner ~/.hermes/plugins/jev-tool-pruner
hermes plugins enable jev-tool-pruner
```

Voraussetzung: laufendes lokales Decision-Model mit SystemOne-API (Standard `http://127.0.0.1:8100/v1/systemone`).

## Konfiguration

Via `hermes config set plugins.entries.jev-tool-pruner.settings.<key> <wert>`:

| Key | Default | Bedeutung |
|---|---|---|
| `enabled` | `false` | Schaltet das Pruning an. |
| `router` | `http://127.0.0.1:8100/v1/systemone` | Lokaler SystemOne-Endpunkt. |
| `model` | `qwen3-4b` | Decision-Modell auf dem Router. |
| `threshold` | `0.5` | noul-Wahrscheinlichkeit, ab der ein Tool behalten wird. |
| `min_always` | `[]` | Tools, die unabhaengig von jev immer bleiben. |

## Verwandt

Fuettert eine Luecke in der jev-Plugin-Landschaft: `jev-effort-router` und `jev-skill-router`
nutzen dasselbe `llm_request`-Middleware-Pattern fuer Modell/Effort bzw. Skill-Auswahl —
kein Katalog-Eintrag prunted bisher die Tool-Schemata selbst.

## Lizenz

MIT

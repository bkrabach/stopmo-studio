"""Time and cost ledger: every stage records what it took, so runs can be compared."""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path


class Ledger:
    def __init__(self) -> None:
        self.started = time.time()
        self.stages: list[dict] = []
        self.counts: dict[str, float] = {}
        self.cache_hits: dict[str, int] = {}

    @contextmanager
    def stage(self, name: str, **info):
        """Time a stage: `with ledger.stage("render", shot="s1"): ...`"""
        start = time.time()
        entry = {"stage": name, **info}
        try:
            yield entry
        finally:
            entry["seconds"] = round(time.time() - start, 3)
            self.stages.append(entry)

    def count(self, name: str, amount: float = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + amount

    def hit(self, name: str) -> None:
        self.cache_hits[name] = self.cache_hits.get(name, 0) + 1

    def totals(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for entry in self.stages:
            out[entry["stage"]] = round(out.get(entry["stage"], 0.0) + entry["seconds"], 3)
        return out

    def summary(self) -> dict:
        return {
            "wall_seconds": round(time.time() - self.started, 2),
            "by_stage": self.totals(),
            "counts": self.counts,
            "cache_hits": self.cache_hits,
            # Everything in the pipeline runs locally on free tools: no per-frame API spend.
            "api_cost_usd": 0.0,
            "stages": self.stages,
        }

    def write(self, path: Path) -> dict:
        data = self.summary()
        Path(path).write_text(json.dumps(data, indent=1))
        return data

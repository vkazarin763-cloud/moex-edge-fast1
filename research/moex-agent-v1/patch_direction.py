#!/usr/bin/env python3
"""Apply direction-aware model probabilities before the isolated paper run."""
from pathlib import Path

path = Path("vendor/moex-agent/moex_agent/engine.py")
source = path.read_text(encoding="utf-8")
old = '''            # Find best horizon
            best_h, best_p = self.models.best_horizon(X)
            if best_h is None:
                continue
'''
new = '''            # Models estimate P(price-up). For SHORT, use P(price-down)=1-P(up).
            predictions = self.models.predict_all(X)
            if not predictions:
                continue
            if anomaly.direction == Direction.LONG:
                best_h = max(predictions, key=predictions.get)
                best_p = predictions[best_h]
            else:
                best_h = min(predictions, key=predictions.get)
                best_p = 1.0 - predictions[best_h]
'''
if old not in source:
    raise SystemExit("Expected upstream prediction block not found; refusing unsafe patch")
path.write_text(source.replace(old, new, 1), encoding="utf-8")
print("Direction-aware LONG/SHORT probability patch applied.")

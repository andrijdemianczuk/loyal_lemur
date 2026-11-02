"""ClaudeTriager behaviour with a fake model (no API calls)."""

import time
from datetime import UTC, datetime

from er_triage.ai.claude_triage import ClaudeTriage, ClaudeTriager, _Call, patient_prompt
from er_triage.models import AssessmentSource
from er_triage.sim.generator import PatientGenerator, Vitals

WHEN = datetime(2026, 11, 6, 9, tzinfo=UTC)


class FakeTriager(ClaudeTriager):
    def __init__(self, replies: dict[str, ClaudeTriage | Exception], delay: float = 0.0,
                 **kw):
        super().__init__(None, offline=True, **kw)
        self.replies = replies
        self.delay = delay
        self.models_called: list[str] = []

    def _call(self, model, prompt, patient):
        self.models_called.append(model)
        time.sleep(self.delay)
        reply = self.replies[model]
        if isinstance(reply, Exception):
            raise reply
        return _Call(model, reply, 5, 100, 50, 0, False)


def _reply(level: int, confidence: str = "high", fast: bool = False) -> ClaudeTriage:
    return ClaudeTriage(ctas_level=level, confidence=confidence, rationale="test",
                        red_flags=["flag"] if level <= 2 else [], fast_track_eligible=fast)


def _patient():
    return PatientGenerator(seed=4).new_patient(WHEN)


def _normal_vitals(**kw) -> Vitals:
    base = dict(heart_rate=80, systolic_bp=125, diastolic_bp=80, resp_rate=16, spo2=98,
                temp_c=37.0, pain_score=1, gcs=15)
    return Vitals(**{**base, **kw})


def test_prompt_contains_no_ground_truth():
    p = _patient()
    prompt = patient_prompt(p, p.vitals)
    assert p.presentation.code not in prompt
    assert "CTAS" not in prompt and "fragility" not in prompt


def test_uses_claude_decision():
    t = FakeTriager({"claude-haiku-5-5": _reply(2)}, blocking=True)
    d = t.assess(_patient(), _normal_vitals(), 2, 0)
    assert d.ctas == 2 and d.source == AssessmentSource.AI and d.model == "claude-haiku-5-5"
    assert t.models_called == ["claude-haiku-5-5"]


def test_guardrail_never_below_vital_sign_rules():
    t = FakeTriager({"claude-haiku-5-5": _reply(4)}, blocking=True)
    d = t.assess(_patient(), _normal_vitals(spo2=89), 4, 0)  # SpO2 < 92 -> CTAS 2
    assert d.ctas == 2 and "Guardrail" in d.rationale and "SpO2 89%" in d.red_flags


def test_low_confidence_escalates():
    t = FakeTriager({"claude-haiku-5-5": _reply(3, "medium"),
                     "claude-sonnet-5-5": _reply(2)}, blocking=True)
    d = t.assess(_patient(), _normal_vitals(), 2, 0)
    assert t.models_called == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    assert d.ctas == 2 and d.model == "claude-sonnet-5-5"


def test_failure_falls_back_to_rules():
    t = FakeTriager({"claude-haiku-5-5": RuntimeError("boom")}, blocking=True)
    d = t.assess(_patient(), _normal_vitals(pain_score=5), 3, 0)
    assert d.source == AssessmentSource.RULES and d.ctas == 4
    assert "AI unavailable" in d.rationale and t.stats["fallbacks"] == 1


def test_fast_track_only_for_ctas_3_plus():
    t = FakeTriager({"claude-haiku-5-5": _reply(2, fast=True)}, blocking=True)
    assert t.assess(_patient(), _normal_vitals(), 2, 0).fast_track is False


def test_live_mode_provisional_then_late_decision():
    t = FakeTriager({"claude-haiku-5-5": _reply(2)}, delay=0.2)
    p = _patient()
    t.prefetch(p, _normal_vitals())
    provisional = t.assess(p, _normal_vitals(), 2, 0)
    assert provisional.source == AssessmentSource.RULES
    assert provisional.rationale.startswith("Provisional")
    assert t.completed() == []
    time.sleep(0.4)
    [(mrn, decision)] = t.completed()
    assert mrn == p.mrn and decision.ctas == 2 and decision.source == AssessmentSource.AI
    t.close()


def test_cache_only_never_calls_api(monkeypatch):
    """During warm-up a cache miss falls back to rules even with an API key."""
    t = ClaudeTriager("not-a-real-key", blocking=True)
    t.cache_only = True
    monkeypatch.setattr(t, "_from_cache", lambda key, model: None)
    monkeypatch.setattr(t, "_from_api", lambda *a: (_ for _ in ()).throw(AssertionError("API")))
    d = t.assess(_patient(), _normal_vitals(), 3, 0)
    assert d.source == AssessmentSource.RULES and t.stats["fallbacks"] == 1
    t.reset_stats()
    assert t.stats["fallbacks"] == 0
    t.close()

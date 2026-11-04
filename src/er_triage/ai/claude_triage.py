"""Claude-backed CTAS triage for the AI arm.

Routing: every patient is triaged by the fast primary model (Haiku). Cases
it is not confident about, or that look emergent, are escalated to the
stronger model (Sonnet). Any failure, refusal, or timeout falls back to the
deterministic CTAS rules calculator, so the ED never stalls on the API.

Guardrail: Claude may assign a *higher* acuity than the vital-sign rules
indicate, never a lower one.

Claude sees only what a triage nurse would: demographics, arrival mode,
chief complaint, triage note, history, medications and vitals. Never the
simulator's ground truth or the ED's load, which also keeps requests
deterministic so cached responses replay exactly.
"""

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal

import anthropic
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from er_triage.db import session_scope
from er_triage.events import EventType
from er_triage.models import AssessmentSource, LlmResponse
from er_triage.sim.generator import NewPatient, Vitals
from er_triage.sim.triage import RulesTriager, TriageDecision

log = logging.getLogger(__name__)

PROMPT_VERSION = "ctas-v2"  # v2: adds likely_admission

SYSTEM_PROMPT = """\
You are an emergency department triage decision-support system used by \
triage nurses at a Canadian hospital. For each patient, assign a Canadian \
Triage and Acuity Scale (CTAS) level and explain it briefly. A nurse \
confirms every recommendation; your job is to make sure no time-critical \
patient is missed and that resources go where they matter.

CTAS levels and time-to-physician targets:
1 Resuscitation (immediate): cardiac/respiratory arrest, major trauma in \
shock, severe respiratory distress, unresponsive (GCS 3-9), status seizures.
2 Emergent (15 min): potential threat to life, limb or function needing \
rapid intervention - e.g. chest pain likely cardiac, stroke within the \
treatment window, sepsis with physiological change, altered mental status, \
severe asthma, overdose, suicidal ideation with a plan.
3 Urgent (30 min): conditions that could progress to a serious problem - \
e.g. moderate respiratory symptoms, abdominal pain needing workup, severe \
peripheral pain, syncope, head injury with risk factors, hip fracture.
4 Less urgent (60 min): conditions related to patient age, distress, or \
potential for deterioration that would benefit from care within 1-2 hours \
- minor injuries, uncomplicated infections, mild-moderate pain.
5 Non-urgent (120 min): acute but non-urgent or chronic problems - \
minor symptoms, medication refills, minor rashes.

How to triage:
- Start from the presenting complaint, then apply first-order modifiers \
(vital signs, level of consciousness, pain severity, mechanism of injury) \
and second-order modifiers (e.g. anticoagulation or bleeding disorder, \
immunosuppression, pregnancy, extremes of age).
- Look beyond reassuring vital signs. Atypical presentations are common in \
older adults, women and people with diabetes; the wording of a complaint \
("indigestion", "a bit forgetful", "just a headache") can understate risk. \
Read the triage note, history and medications together.
- When a dangerous diagnosis is plausible and time-sensitive, triage to \
the level that diagnosis requires. Under-triage is more harmful than \
over-triage, but do not over-triage clearly minor problems: every \
unnecessary high-acuity assignment delays someone else.
- fast_track_eligible: true only for stable, ambulatory patients likely to \
be treated and discharged quickly (most CTAS 4-5 and some low-risk CTAS 3).
- likely_admission: true when this patient will probably need admission to \
hospital (not just ED treatment and discharge), judged from the complaint, \
age, history and vital signs. It is used to request an inpatient bed early, \
so be realistic: neither every older patient nor only the critically ill.
- confidence: "high" when the level is clear; "medium" or "low" when the \
case is ambiguous or could plausibly be a different level.
- red_flags: short phrases for findings that drove the level up (empty if \
none). immediate_actions: up to three concrete nursing actions to start \
now (e.g. "12-lead ECG within 10 min"), empty if none.
- rationale: at most two sentences, written for a busy nurse.\
"""


class ClaudeTriage(BaseModel):
    ctas_level: Literal[1, 2, 3, 4, 5]
    confidence: Literal["high", "medium", "low"]
    rationale: str
    red_flags: list[str] = Field(default_factory=list)
    immediate_actions: list[str] = Field(default_factory=list)
    fast_track_eligible: bool
    likely_admission: bool = False


def patient_prompt(patient: NewPatient, vitals: Vitals) -> str:
    v = vitals
    return (
        f"Age/sex: {patient.age}{patient.sex}\n"
        f"Arrival: {'ambulance' if patient.arrival_mode == 'ambulance' else 'walk-in'}\n"
        f"Chief complaint: {patient.presentation.complaint}\n"
        f"Triage note: {patient.triage_note}\n"
        f"History: {patient.history}\n"
        f"Vitals: HR {v.heart_rate}, BP {v.systolic_bp}/{v.diastolic_bp}, RR {v.resp_rate}, "
        f"SpO2 {v.spo2}%, T {v.temp_c} C, pain {v.pain_score}/10, GCS {v.gcs}"
    )


@dataclass
class _Call:
    model: str
    output: ClaudeTriage
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cached: bool  # served from the replay cache, no API call made


class ClaudeTriager:
    """Triager for the AI arm. Thread-safe; calls run on a worker pool."""

    source = AssessmentSource.AI

    def __init__(
        self,
        api_key: str | None,
        *,
        primary_model: str = "claude-haiku-5-5",
        escalation_model: str | None = "claude-sonnet-5-5",
        blocking: bool = False,
        offline: bool = False,
        timeout_s: float = 30.0,
        max_workers: int = 8,
        emit: Callable[..., None] | None = None,
    ) -> None:
        self.client = (
            anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=2)
            if api_key and not offline else None
        )
        self.primary_model = primary_model
        self.escalation_model = escalation_model
        self.blocking = blocking
        self.offline = offline
        # Temporarily replay-only (used during warm-up): cache misses fall back
        # to rules instead of calling the API.
        self.cache_only = False
        self.timeout_s = timeout_s
        self.rules = RulesTriager()
        self._emit = emit
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="claude")
        self._lock = threading.Lock()
        self._futures: dict[str, Future[TriageDecision]] = {}
        self._late: set[str] = set()  # provisional rules decision already used
        self.stats = {"calls": 0, "cache_hits": 0, "escalations": 0, "fallbacks": 0,
                      "late": 0, "input_tokens": 0, "output_tokens": 0}
        self.tokens_by_model: dict[str, list[int]] = {}  # model -> [input, output]

    def attach_emitter(self, emit: Callable[..., None]) -> None:
        self._emit = emit

    # -- Triager protocol -------------------------------------------------------

    def prefetch(self, patient: NewPatient, vitals: Vitals) -> None:
        """Start triage when the patient reaches the triage desk."""
        with self._lock:
            if patient.mrn not in self._futures:
                self._futures[patient.mrn] = self._pool.submit(self._decide, patient, vitals)

    def assess(self, patient, vitals, true_ctas, waiting_load) -> TriageDecision:
        self.prefetch(patient, vitals)
        future = self._futures[patient.mrn]
        if self.blocking or future.done():
            with self._lock:
                del self._futures[patient.mrn]
            return future.result()
        # Not back yet: proceed on the rules decision and apply Claude's when
        # it lands, rather than holding the patient at the desk.
        with self._lock:
            self._late.add(patient.mrn)
            self.stats["late"] += 1
        provisional = self.rules.score(patient, vitals)
        provisional.rationale = "Provisional (AI pending): " + provisional.rationale
        return provisional

    def completed(self) -> list[tuple[str, TriageDecision]]:
        """Late Claude decisions that are now available."""
        out = []
        with self._lock:
            for mrn in [m for m in self._late if self._futures[m].done()]:
                out.append((mrn, self._futures.pop(mrn).result()))
                self._late.discard(mrn)
        return out

    def reassess(self, patient, vitals, assigned, true_ctas):
        # Continuous reassessment stays on the instant vital-sign rules.
        return self.rules.reassess(patient, vitals, assigned, true_ctas)

    def reset_stats(self) -> None:
        for k in self.stats:
            self.stats[k] = 0
        self.tokens_by_model.clear()

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # -- decision logic ---------------------------------------------------------

    def _decide(self, patient: NewPatient, vitals: Vitals) -> TriageDecision:
        rules = self.rules.score(patient, vitals)
        prompt = patient_prompt(patient, vitals)
        try:
            call = self._call(self.primary_model, prompt, patient)
            if self.escalation_model and self._should_escalate(call.output):
                self.stats["escalations"] += 1
                call = self._call(self.escalation_model, prompt, patient)
        except Exception as exc:
            self.stats["fallbacks"] += 1
            (log.debug if self.cache_only else log.warning)(
                "Claude triage failed for %s, using rules: %s", patient.mrn, exc)
            rules.rationale = f"AI unavailable ({type(exc).__name__}); " + rules.rationale
            return rules

        out = call.output
        level = out.ctas_level
        flags = list(out.red_flags)
        rationale = out.rationale
        if rules.ctas < level:  # guardrail: never below the vital-sign rules
            level = rules.ctas
            flags += rules.red_flags
            rationale += f" [Guardrail: raised to CTAS {level} by vital-sign rules.]"
        if out.immediate_actions:
            rationale += " Actions: " + "; ".join(out.immediate_actions) + "."
        return TriageDecision(
            ctas=level,
            source=AssessmentSource.AI,
            rationale=rationale,
            red_flags=flags,
            fast_track=out.fast_track_eligible and level >= 3,
            admit_predicted=out.likely_admission,
            rules_ctas=rules.ctas,
            model=call.model,
            latency_ms=call.latency_ms,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
        )

    @staticmethod
    def _should_escalate(out: ClaudeTriage) -> bool:
        # Evaluation showed the primary model is already accurate on clear
        # cases at every acuity; spend the stronger model on ambiguity only.
        return out.confidence != "high"

    def _call(self, model: str, prompt: str, patient: NewPatient) -> _Call:
        effort = "low" if model == self.primary_model else "medium"
        key = hashlib.sha256(
            json.dumps([PROMPT_VERSION, model, effort, prompt]).encode()
        ).hexdigest()
        call = self._from_cache(key, model)
        if call is None:
            if self.client is None or self.cache_only:
                raise RuntimeError("offline and no cached response")
            call = self._from_api(key, model, effort, prompt)
        with self._lock:
            self.stats["calls"] += 1
            self.stats["cache_hits"] += call.cached
            self.stats["input_tokens"] += call.input_tokens
            self.stats["output_tokens"] += call.output_tokens
            tokens = self.tokens_by_model.setdefault(model, [0, 0])
            tokens[0] += call.input_tokens
            tokens[1] += call.output_tokens
        if self._emit:
            self._emit(EventType.LLM_CALL, {
                "mrn": patient.mrn,
                "model": model,
                "effort": effort,
                "prompt_version": PROMPT_VERSION,
                "replayed": call.cached,
                "latency_ms": call.latency_ms,
                "input_tokens": call.input_tokens,
                "output_tokens": call.output_tokens,
                "cache_read_tokens": call.cache_read_tokens,
                "ctas_level": call.output.ctas_level,
                "confidence": call.output.confidence,
            })
        return call

    def _from_cache(self, key: str, model: str) -> _Call | None:
        with session_scope() as s:
            row = s.scalar(select(LlmResponse).where(LlmResponse.cache_key == key))
            if row is None:
                return None
            return _Call(model, ClaudeTriage.model_validate(row.response), 0,
                         row.input_tokens, row.output_tokens, row.cache_read_tokens, True)

    def _from_api(self, key: str, model: str, effort: str, prompt: str) -> _Call:
        kwargs = dict(
            model=model,
            max_tokens=4096,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort},
            output_format=ClaudeTriage,
        )
        start = time.monotonic()
        if model.startswith("claude-haiku"):
            # Haiku has no server-side refusal fallback; rules cover refusals.
            response = self.client.messages.parse(**kwargs)
        else:
            response = self.client.beta.messages.parse(
                **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        latency = int((time.monotonic() - start) * 1000)
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise RuntimeError(f"no triage output (stop_reason={response.stop_reason})")

        usage = response.usage
        call = _Call(model, response.parsed_output, latency, usage.input_tokens,
                     usage.output_tokens, usage.cache_read_input_tokens or 0, False)
        try:
            self._store(key, model, effort, prompt, call)
        except Exception as exc:  # caching is best-effort
            log.warning("could not cache LLM response: %s", exc)
        return call

    def _store(self, key: str, model: str, effort: str, prompt: str, call: _Call) -> None:
        # Concurrent identical requests can race; first writer wins.
        with session_scope() as s:
            s.execute(insert(LlmResponse).values(
                cache_key=key, model=model, prompt_version=PROMPT_VERSION,
                request={"effort": effort, "prompt": prompt},
                response=call.output.model_dump(), latency_ms=call.latency_ms,
                input_tokens=call.input_tokens, output_tokens=call.output_tokens,
                cache_read_tokens=call.cache_read_tokens,
            ).on_conflict_do_nothing(index_elements=["cache_key"]))

"""Chooser that answers the same questions as TypeSafe, using one OpenAI-compatible call.

Drop-in replacement for :func:`jev_ultrafast.model.choose` so the loop can run with a
model we already hold a key for (OpenRouter, DeepSeek, or any OpenAI-compatible endpoint)
while TypeSafe has no key of its own.

It keeps the property that matters: the same questions, one network call, and code that
validates the answer before anything is executed. Model output is still only an index into
observed elements, never a selector or a script.
"""

import json
import os
import time

from .model import CLIENT, action_space, post_json, validate_choice
from .questions import NEXT_ACTION, TARGET

SYSTEM = """You control a web browser by choosing one operation and its target, from a fixed list.

""" + NEXT_ACTION + """

""" + TARGET + """

Answer every question you are given, in one JSON object, with exactly this shape:

{
  "operation":          {"choice": "<key>",          "probabilities": {"<key>": 0.0, ...}, "confidence": 0.0},
  "<op>_target":        {"choice": "<element index>","probabilities": {"<index>": 0.0, ...}, "confidence": 0.0}
}

Rules for the answer itself:
- Include one "<op>_target" object for every target question you are given, lowercased, for example "click_target".
- Probabilities for each question must sum to 1, and the chosen key must be the highest.
- Every key inside a set of probabilities must be one of the offered keys exactly, as strings.
- Return JSON only. No prose, no code fences."""


def _repair(answer, ids):
    """Tidy a model answer so the same validation can still gate it.

    Keys are matched as strings, unknown keys dropped, missing keys given a small
    weight, probabilities renormalised, and a stated choice that is not offered
    replaced by the model's strongest key. Nothing is invented: the offered keys
    are the only keys, and an answer that still fails validation raises.
    """
    if not isinstance(answer, dict):
        return answer
    offered = [str(i) for i in ids]
    raw = answer.get("probabilities")
    probs = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if str(k) in offered and isinstance(v, (int, float)) and 0 <= v <= 1:
                probs[str(k)] = float(v)
    for k in offered:
        probs.setdefault(k, 0.0)
    total = sum(probs.values())
    if total <= 0:
        probs = {k: 1.0 / len(offered) for k in offered}
    elif abs(total - 1.0) > 1e-9:
        probs = {k: v / total for k, v in probs.items()}

    strongest = max(offered, key=lambda k: probs[k])
    stated = answer.get("choice")
    stated = str(stated) if stated is not None else None
    choose = stated if stated in offered else strongest
    if probs[choose] < probs[strongest] - 1e-9:
        probs[choose] = probs[strongest]  # honour the stated pick over the raw spread
    others = [k for k in offered if k != choose]
    other_sum = sum(probs[k] for k in others)
    room = 1.0 - probs[choose]
    for k in others:
        probs[k] = (probs[k] / other_sum * room) if other_sum > 0 else (room / len(others))

    probs = {k: round(v, 6) for k, v in probs.items()}
    confidence = answer.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        confidence = probs[choose]
    return {"choice": choose, "probabilities": probs, "confidence": float(confidence)}


def choose_openrouter(state, goal, history):
    elements, targets, controls = action_space(state["actions"])
    labels = {
        "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
        "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
        "SELECT": "Select an observed dropdown value.",
    }
    operations = {key: labels[key] for key in targets}
    operations.update({key: value["label"] for key, value in controls.items()})
    operations.update(DONE="Every requirement is visibly satisfied.", BLOCKED="No supported operation can progress.")

    questions = {
        "operation": {
            "criteria": operations,
            "note": "Pick the single next operation.",
        }
    }
    for operation, candidates in targets.items():
        questions[operation.lower() + "_target"] = {
            "criteria": {
                index: {
                    "element": f"[{index}] {a['label']}",
                    "current_value": a.get("current_value", a.get("value", "")),
                    **{k: a[k] for k in ("role", "checked", "selected", "expanded") if k in a},
                }
                for index, a in candidates.items()
            },
            "note": f"Pick a target in case the operation is {operation}.",
        }

    body = {
        "model": os.environ.get("CHOOSER_MODEL", "inception/mercury-2.5"),
        "max_tokens": int(os.environ.get("CHOOSER_MAX_TOKENS", "2600")),
        **( {} if os.environ.get("CHOOSER_JSON_MODE", "1") == "0" else {"response_format": {"type": "json_object"}}),
        "messages": [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "goal": goal,
                        "page": {
                            "url": state["url"],
                            "title": state["title"],
                            "text": (state.get("text") or "")[:12000],
                        },
                        "elements": elements,
                        "recent_actions": [
                            {k: h.get(k) for k in ("action", "kind", "text", "page_changed")} for h in history[-10:]
                        ],
                        "questions": questions,
                    }
                ),
            },
        ],
    }
    if os.environ.get("CHOOSER_REASONING", "none") == "none":
        # A reasoning model can spend the whole budget thinking and return no answer.
        body["reasoning"] = {"enabled": False}
    started = time.perf_counter()
    key = os.environ.get("TEXT_MODEL_API_KEY") or os.environ.get("CHOOSER_API_KEY")
    base = (os.environ.get("CHOOSER_BASE_URL") or os.environ.get("TEXT_MODEL_BASE_URL", "https://openrouter.ai/api/v1")).rstrip("/")
    answers = None
    result = None
    for attempt in range(int(os.environ.get("CHOOSER_ATTEMPTS", "3"))):
        result = post_json(base + "/chat/completions", key, body)
        try:
            answers = json.loads(result["choices"][0]["message"]["content"])
            break
        except (KeyError, IndexError, TypeError, ValueError):
            answers = None
            # Retry once with the answer forced back to the required shape.
            body["messages"] = body["messages"][:2] + [
                {"role": "assistant", "content": str(result.get("choices", [{}])[0].get("message", {}).get("content"))[:2000]},
                {"role": "user", "content": "That was not a JSON object. Reply with the JSON object only, nothing else."},
            ]
            body["response_format"] = {"type": "json_object"}
            time.sleep(0.4)
    if answers is None:
        raise ValueError("Chooser returned no valid JSON; no action executed.")

    operation_answer = validate_choice(_repair(answers.get("operation", {}), operations), operations)
    operation = operation_answer["choice"]
    target = None
    target_answer = None
    probabilities = {}
    if operation in targets:
        target_answer = validate_choice(_repair(answers.get(operation.lower() + "_target", {}), targets[operation]), targets[operation])
        target = target_answer["choice"]
        choice = targets[operation][target]["id"]
        probabilities = {a["id"]: target_answer["probabilities"][index] for index, a in targets[operation].items()}
    else:
        choice = controls[operation]["id"] if operation in controls else operation
        probabilities[choice] = operation_answer["probabilities"][operation]
    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "confidence": operation_answer["confidence"],
        "probabilities": probabilities,
        "operation_probabilities": operation_answer["probabilities"],
        "target_probabilities": target_answer["probabilities"] if target_answer else {},
        "target_confidence": target_answer["confidence"] if target_answer else None,
        "raw_answers": answers,
        "model": result.get("model"),
        "usage": result.get("usage", {}),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "request": body,
    }

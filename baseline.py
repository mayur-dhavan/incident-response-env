"""
Baseline inference script — LLM agent via OpenAI-compatible API.

Runs an LLM against all 5 incident-response tasks and prints reproducible
scores.  Works with any OpenAI-compatible endpoint: OpenAI, HuggingFace
Inference, vLLM, Ollama, etc.

Falls back to a deterministic rule-based agent when no API key is available.

Usage:
    # Open LLM via HuggingFace Inference (recommended for hackathon eval)
    python baseline.py --url http://localhost:7860 --provider hf --model meta-llama/Llama-3.1-8B-Instruct

    # OpenAI
    python baseline.py --url http://localhost:7860 --provider openai --model gpt-4o-mini

    # Any OpenAI-compatible endpoint
    python baseline.py --url http://localhost:7860 --api-base http://localhost:8000/v1 --api-key sk-...

    # Rule-based fallback (no API key needed)
    python baseline.py --url http://localhost:7860 --rule-based
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from typing import Any


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def post(url: str, data: dict | None = None) -> dict:
    payload = json.dumps(data or {}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read())


# ── Rule-based baseline ─────────────────────────────────────────────────────

RULE_POLICIES: dict[str, list[dict[str, Any]]] = {
    "task_1_oom": [
        {"action_type": "read_logs",       "target": "api-server", "parameters": {}},
        {"action_type": "restart_service", "target": "api-server", "parameters": {}},
    ],
    "task_2_leak": [
        {"action_type": "check_metrics", "target": "worker",  "parameters": {}},
        {"action_type": "read_logs",     "target": "worker",  "parameters": {}},
        {"action_type": "rollback",      "target": "worker",  "parameters": {}},
    ],
    "task_3_cascade": [
        {"action_type": "check_metrics",  "target": "postgres", "parameters": {}},
        {"action_type": "read_logs",      "target": "postgres", "parameters": {}},
        {"action_type": "exec_command",   "target": "ALTER SYSTEM SET max_connections = 200", "parameters": {}},
        {"action_type": "exec_command",   "target": "SELECT pg_reload_conf()", "parameters": {}},
    ],
    "task_4_cache": [
        {"action_type": "read_logs",     "target": "redis",     "parameters": {}},
        {"action_type": "check_metrics", "target": "redis",     "parameters": {}},
        {"action_type": "exec_command",  "target": "redis-cli FLUSHALL", "parameters": {}},
    ],
    "task_5_cert": [
        {"action_type": "read_logs",       "target": "nginx",   "parameters": {}},
        {"action_type": "exec_command",    "target": "openssl s_client -connect api-server:8443", "parameters": {}},
        {"action_type": "exec_command",    "target": "certbot renew --force-renewal", "parameters": {}},
        {"action_type": "restart_service", "target": "nginx",   "parameters": {}},
    ],
}


def run_rule_episode(base_url: str, task_id: str) -> tuple[float, int, bool]:
    """Run rule-based agent on one task, return (score, steps, restored)."""
    post(f"{base_url}/reset", {"task_id": task_id})
    actions = RULE_POLICIES[task_id]
    steps = 0
    for action in actions:
        resp = post(f"{base_url}/step", {"action": action})
        steps += 1
        if resp.get("done"):
            break
    state = get(f"{base_url}/state")
    grader = post(f"{base_url}/grader")
    return grader["score"], steps, state.get("system_restored", False)


# ── LLM-based baseline ──────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an expert SRE (Site Reliability Engineer) debugging a production incident.

You can take ONE action per turn by returning a JSON object with these fields:
- action_type: one of "read_logs", "check_metrics", "restart_service", "rollback", "exec_command", "check_network"
- target: service name (api-server, postgres, redis, worker, nginx) or command string for exec_command
- parameters: optional dict (e.g. {"lines": 50})

Strategy:
1. First investigate: read logs and check metrics to identify the root cause
2. Only apply fixes (restart, rollback, exec_command) after identifying the problem
3. Don't blindly restart services — understand the root cause first

Return ONLY valid JSON. No markdown, no explanation outside the JSON.
"""


def run_llm_episode(base_url: str, task_id: str, model: str, client: "OpenAI | None" = None) -> tuple[float, int, bool]:
    """Run LLM agent on one task using OpenAI-compatible API, return (score, steps, restored)."""
    from openai import OpenAI as _OpenAI

    if client is None:
        client = _OpenAI()  # fallback: reads OPENAI_API_KEY from env

    # Reset
    reset_resp = post(f"{base_url}/reset", {"task_id": task_id})
    obs_text = reset_resp["observation"]["output"]

    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"INCIDENT ALERT:\n\n{obs_text}\n\nInvestigate and resolve this incident."},
    ]

    max_steps = 15
    steps = 0
    done = False
    retries = 0  # track consecutive API failures

    while not done and steps < max_steps:
        # Ask the LLM for an action
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.0,
                max_tokens=256,
            )
            reply = completion.choices[0].message.content or ""
            retries = 0  # reset on success
        except Exception as e:
            retries += 1
            print(f"\n    [!] LLM API error (attempt {retries}): {e}")
            if retries >= 3:
                print("    [!] Too many API errors. Ending episode early.")
                break
            import time
            time.sleep(2 ** retries)
            continue

        # Parse action JSON from LLM response — handle markdown fences
        raw = reply.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            raw = "\n".join(lines).strip()
        raw = raw.strip("`").strip()

        try:
            action = json.loads(raw)
            if "action_type" not in action:
                raise ValueError("Missing action_type")
            action.setdefault("target", "")
            action.setdefault("parameters", {})
        except (json.JSONDecodeError, ValueError):
            # If LLM returns invalid JSON, nudge it
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": "Invalid JSON. Return ONLY a JSON object with action_type, target, and parameters."})
            continue

        # Execute action
        step_resp = post(f"{base_url}/step", {"action": action})
        steps += 1
        done = step_resp.get("done", False)
        reward = step_resp.get("reward")
        obs_output = step_resp["observation"]["output"]

        # Feed observation back to LLM
        messages.append({"role": "assistant", "content": reply})
        feedback = f"OBSERVATION (step {steps}, reward={reward}):\n\n{obs_output}"
        if done:
            feedback += "\n\nEpisode ended."
        else:
            feedback += "\n\nWhat is your next action? Return ONLY valid JSON."
        messages.append({"role": "user", "content": feedback})

    # Get final score
    state = get(f"{base_url}/state")
    grader = post(f"{base_url}/grader")
    return grader["score"], steps, state.get("system_restored", False)


# ── Main ─────────────────────────────────────────────────────────────────────

def run_baseline(base_url: str, use_rules: bool = False, model: str = "gpt-4o-mini",
                 client: "Any | None" = None) -> int:
    base_url = base_url.rstrip("/")

    mode = "rule-based" if use_rules else f"LLM ({model})"

    print(f"\n{'='*60}")
    print(f"  Incident Response Env — Baseline Evaluation")
    print(f"  Server: {base_url}")
    print(f"  Agent:  {mode}")
    print(f"{'='*60}\n")

    # Health check
    try:
        health = get(f"{base_url}/health")
        print(f"[+] Health check: {health}\n")
    except urllib.error.URLError as e:
        print(f"[!] Cannot reach server at {base_url}: {e}")
        print("    Start the server first:  uvicorn server.app:app --port 7860")
        return 1

    # List tasks
    tasks_resp = get(f"{base_url}/tasks")
    tasks = tasks_resp["tasks"]
    print(f"[+] Tasks available: {len(tasks)}")
    for t in tasks:
        print(f"    > {t['task_id']} [{t['difficulty']}] -- {t['title']}")
    print()

    # Run episodes
    results: list[dict[str, Any]] = []
    for t in tasks:
        task_id = t["task_id"]
        print(f"  Running {task_id} ({t['difficulty']})...", end=" ", flush=True)

        if use_rules:
            score, steps, restored = run_rule_episode(base_url, task_id)
        else:
            score, steps, restored = run_llm_episode(base_url, task_id, model, client)

        results.append({
            "task_id": task_id,
            "title": t["title"],
            "difficulty": t["difficulty"],
            "score": score,
            "steps": steps,
            "restored": restored,
        })
        mark = "+" if restored else "!"
        print(f"score={score:.4f}  steps={steps}  restored={restored}")

    # Summary
    avg = sum(r["score"] for r in results) / len(results)

    print(f"\n{'~'*60}")
    print(f"  {'Task':<35} {'Diff':<8} {'Score':>6}  {'Steps':>5}  Restored")
    print(f"{'~'*60}")
    for r in results:
        mark = "+" if r["restored"] else "!"
        print(
            f"  {r['title']:<35} {r['difficulty']:<8} "
            f"{r['score']:>6.4f}  {r['steps']:>5}  [{mark}]"
        )
    print(f"{'~'*60}")
    print(f"  Average score: {avg:.4f}")
    print(f"{'~'*60}\n")

    # Validate
    invalid = [r for r in results if not (0.0 <= r["score"] <= 1.0)]
    if invalid:
        print(f"[!] Scores out of range: {invalid}")
        return 1

    if len(results) < 3:
        print(f"[!] Expected 3 task scores, got {len(results)}")
        return 1

    print("[+] All scores valid (in [0.0, 1.0])")
    print(f"[+] {len(results)} tasks evaluated")
    print(f"[+] Baseline complete -- reproducible scores logged above\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run baseline agent evaluation")
    parser.add_argument(
        "--url",
        default="http://localhost:7860",
        help="Base URL of the running incident_response_env server",
    )
    parser.add_argument(
        "--model",
        default="meta-llama/Llama-3.1-8B-Instruct",
        help="Model name (default: meta-llama/Llama-3.1-8B-Instruct)",
    )
    parser.add_argument(
        "--provider",
        choices=["hf", "openai", "custom"],
        default=None,
        help="LLM provider: 'hf' (HuggingFace Inference), 'openai', or 'custom' (use --api-base)",
    )
    parser.add_argument(
        "--api-base",
        default=None,
        help="Custom OpenAI-compatible base URL (e.g. http://localhost:8000/v1)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key (reads from env if not specified: HF_TOKEN or OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--rule-based",
        action="store_true",
        help="Use deterministic rule-based agent instead of LLM",
    )
    args = parser.parse_args()

    # Build OpenAI client based on provider
    llm_client = None
    if not args.rule_based:
        from openai import OpenAI

        if args.provider == "hf" or (args.provider is None and not os.environ.get("OPENAI_API_KEY")):
            # HuggingFace Inference (OpenAI-compatible)
            api_key = args.api_key or os.environ.get("HF_TOKEN")
            if not api_key:
                try:
                    from huggingface_hub import get_token
                    api_key = get_token()
                except Exception:
                    pass
            if api_key:
                llm_client = OpenAI(
                    base_url="https://router.huggingface.co/v1",
                    api_key=api_key,
                )
                if args.provider is None:
                    print("[*] Auto-detected HuggingFace token. Using HF Inference API.")
            else:
                print("[!] No HF_TOKEN or OPENAI_API_KEY found. Falling back to rule-based agent.")
                args.rule_based = True

        elif args.provider == "openai":
            api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
            if not api_key:
                print("[!] OPENAI_API_KEY not set. Falling back to rule-based agent.")
                args.rule_based = True
            else:
                llm_client = OpenAI(api_key=api_key)

        elif args.provider == "custom":
            if not args.api_base:
                print("[!] --api-base required with --provider custom")
                sys.exit(1)
            llm_client = OpenAI(
                base_url=args.api_base,
                api_key=args.api_key or "no-key",
            )

        elif args.api_base:
            # Custom base URL without explicit provider
            llm_client = OpenAI(
                base_url=args.api_base,
                api_key=args.api_key or os.environ.get("OPENAI_API_KEY", "no-key"),
            )

        else:
            # Default: try OPENAI_API_KEY
            api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
            if api_key:
                llm_client = OpenAI(api_key=api_key)
            else:
                print("[!] No API key found. Falling back to rule-based agent.")
                args.rule_based = True

    sys.exit(run_baseline(args.url, use_rules=args.rule_based, model=args.model,
                          client=llm_client))

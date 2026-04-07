"""
inference.py — Hackathon-required inference script.

Runs an LLM agent (via OpenAI-compatible API) against all 3 incident-response
tasks and prints reproducible scores.

Required environment variables:
    API_BASE_URL   — The API endpoint for the LLM (e.g. https://router.huggingface.co/v1)
    MODEL_NAME     — The model identifier (e.g. meta-llama/Llama-3.1-8B-Instruct)
    HF_TOKEN       — Your Hugging Face / API key

Usage:
    export API_BASE_URL=https://router.huggingface.co/v1
    export MODEL_NAME=meta-llama/Llama-3.1-8B-Instruct
    export HF_TOKEN=hf_...
    python inference.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error


# ── Configuration from environment variables ─────────────────────────────────

API_BASE_URL = os.environ.get("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME = os.environ.get("MODEL_NAME", "meta-llama/Llama-3.1-8B-Instruct")
HF_TOKEN = os.environ.get("HF_TOKEN", "")

# Environment server URL — defaults to the deployed HF Space, override with ENV_BASE_URL
ENV_BASE_URL = os.environ.get(
    "ENV_BASE_URL",
    os.environ.get("SPACE_URL", "https://mayur6901-incident-response-env.hf.space"),
).rstrip("/")

MAX_STEPS = 15
TEMPERATURE = 0.0
MAX_TOKENS = 256
FALLBACK_ACTION = '{"action_type": "read_logs", "target": "api-server", "parameters": {}}'


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _post(url: str, data: dict | None = None) -> dict:
    """POST JSON to the environment server."""
    payload = json.dumps(data or {}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _get(url: str) -> dict:
    """GET from the environment server."""
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read())


def _wait_for_server(base_url: str, retries: int = 10, delay: int = 15) -> bool:
    """Wait for the environment server to become ready (handles HF Spaces cold starts)."""
    print(f"[.] Waiting for server at {base_url} ...")
    for i in range(retries):
        try:
            _get(f"{base_url}/health")
            print("[+] Server is up.")
            return True
        except Exception:
            print(f"    [{i + 1}/{retries}] Not ready yet, retrying in {delay}s...")
            time.sleep(delay)
    return False


# ── Structured stdout logging (required by hackathon spec) ──────────────────

def log_start(task: str, model: str) -> None:
    print(f"[START] task={task} env=incident-response-env model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool, error: str | None) -> None:
    error_val = error if error else "null"
    done_val = str(done).lower()
    print(
        f"[STEP] step={step} action={action} reward={reward:.2f} done={done_val} error={error_val}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: list[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} score={score:.3f} rewards={rewards_str}",
        flush=True,
    )


# ── System prompt for the LLM agent ─────────────────────────────────────────

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


def build_user_prompt(
    step: int,
    observation_text: str,
    history: list[str],
) -> str:
    """Build the user prompt for the LLM with context and history."""
    parts = []
    if history:
        parts.append("Previous actions:\n" + "\n".join(history[-5:]))
    parts.append(f"\nStep {step} observation:\n{observation_text}")
    parts.append("\nWhat is your next action? Return ONLY a valid JSON object.")
    return "\n".join(parts)


def parse_action_json(raw_text: str) -> dict | None:
    """Parse an action JSON object from LLM output, handling markdown fences."""
    raw = raw_text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        raw = "\n".join(lines).strip()
    raw = raw.strip("`").strip()
    try:
        action = json.loads(raw)
        if "action_type" not in action:
            return None
        # IMPORTANT: The Action base class uses extra="forbid", so any field
        # the LLM adds beyond action_type/target/parameters (e.g. "reasoning",
        # "thought", "explanation") would cause a 422 from /step.  Filter here.
        params = action.get("parameters", {})
        return {
            "action_type": str(action.get("action_type", "")),
            "target": str(action.get("target", "")),
            "parameters": params if isinstance(params, dict) else {},
        }
    except (json.JSONDecodeError, ValueError):
        return None


def run_episode(
    task_id: str,
    client: "openai.OpenAI",
    model: str,
    base_url: str,
) -> tuple[float, int, bool]:
    """
    Run the LLM agent on a single task episode.

    Returns: (score, steps, system_restored)
    Emits [START], [STEP]*, [END] to stdout per hackathon spec.
    """
    log_start(task=task_id, model=model)

    # Reset environment for this task
    reset_resp = _post(f"{base_url}/reset", {"task_id": task_id})
    obs_text = reset_resp.get("observation", {}).get("output", str(reset_resp))

    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"INCIDENT ALERT:\n\n{obs_text}\n\n"
                "Investigate and resolve this incident."
            ),
        },
    ]

    history: list[str] = []
    step_rewards: list[float] = []
    steps = 0
    done = False
    retries = 0
    score = 0.0
    restored = False

    try:
        while not done and steps < MAX_STEPS:
            # Ask the LLM for an action
            try:
                completion = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                    stream=False,
                )
                reply = completion.choices[0].message.content or ""
                retries = 0
            except Exception as exc:
                retries += 1
                print(f"    [!] LLM API error (attempt {retries}): {exc}")
                if retries >= 3:
                    print("    [!] Too many API errors. Using fallback action.")
                    reply = FALLBACK_ACTION
                    retries = 0
                else:
                    time.sleep(2 ** retries)
                    continue

            # Parse action from LLM response
            action = parse_action_json(reply)
            if action is None:
                # Nudge the LLM if it returned invalid JSON
                messages.append({"role": "assistant", "content": reply})
                messages.append({
                    "role": "user",
                    "content": (
                        "Invalid JSON. Return ONLY a JSON object with "
                        "action_type, target, and parameters."
                    ),
                })
                continue

            # Execute the action
            try:
                step_resp = _post(f"{base_url}/step", {"action": action})
            except Exception as step_exc:
                print(f"    [!] /step error: {step_exc}")
                log_step(step=steps + 1, action=json.dumps(action, separators=(',', ':')), reward=0.0, done=True, error=str(step_exc))
                done = True
                break
            steps += 1
            done = step_resp.get("done", False)
            reward = step_resp.get("reward", 0.0)
            obs_output = step_resp.get("observation", {}).get("output", "")
            obs_success = step_resp.get("observation", {}).get("success", True)
            error_msg: str | None = step_resp.get("observation", {}).get("error") or None
            if not obs_success and not error_msg:
                error_msg = "action_failed"

            action_str = json.dumps(action, separators=(",", ":"))
            step_rewards.append(reward)
            log_step(step=steps, action=action_str, reward=reward, done=done, error=error_msg)

            error_flag = " ERROR" if not obs_success else ""
            history_line = f"Step {steps}: {action_str} -> reward {reward:+.2f}{error_flag}"
            history.append(history_line)
            print(
                f"    Step {steps}: {action['action_type']}({action['target']}) "
                f"-> reward={reward:+.2f} done={done}{error_flag}"
            )

            # Feed observation back to LLM
            messages.append({"role": "assistant", "content": reply})
            feedback = f"OBSERVATION (step {steps}, reward={reward}):\n\n{obs_output}"
            if done:
                feedback += "\n\nEpisode ended."
            else:
                feedback += "\n\nWhat is your next action? Return ONLY valid JSON."
            messages.append({"role": "user", "content": feedback})

    finally:
        # Always emit [END] — even on exception — per hackathon spec
        try:
            state = _get(f"{base_url}/state")
            grader = _post(f"{base_url}/grader")
            score = grader.get("score", 0.0)
            restored = state.get("system_restored", False)
        except Exception:
            pass
        log_end(success=score > 0.0, steps=steps, score=score, rewards=step_rewards)

    return score, steps, restored


def main() -> int:
    """Run inference on all tasks and print results."""

    # Validate required environment variables
    if not HF_TOKEN:
        print("[!] HF_TOKEN environment variable is not set.")
        print("    Set it with: export HF_TOKEN=hf_...")
        print("    Falling back to rule-based baseline.\n")

    print(f"\n{'=' * 60}")
    print("  Incident Response Env — Inference Script")
    print(f"  Environment: {ENV_BASE_URL}")
    print(f"  LLM API:     {API_BASE_URL}")
    print(f"  Model:       {MODEL_NAME}")
    print(f"{'=' * 60}\n")

    # Health check — with retry for cold HF Space starts
    if not _wait_for_server(ENV_BASE_URL, retries=10, delay=15):
        print(f"[!] Server never became ready at {ENV_BASE_URL}")
        print("    Set ENV_BASE_URL to your running Space URL.")
        return 1
    health = _get(f"{ENV_BASE_URL}/health")
    print(f"[+] Health check: {health}\n")

    # List available tasks
    tasks_resp = _get(f"{ENV_BASE_URL}/tasks")
    tasks = tasks_resp.get("tasks", [])
    print(f"[+] Tasks available: {len(tasks)}")
    for t in tasks:
        print(f"    > {t['task_id']} [{t['difficulty']}] -- {t['title']}")
    print()

    # Create OpenAI-compatible client
    from openai import OpenAI

    api_key = HF_TOKEN or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        # Fall back to rule-based baseline if no API key
        print("[!] No API key available. Running rule-based baseline.\n")
        resp = _post(f"{ENV_BASE_URL}/baseline")
        results = resp.get("baseline_scores", [])
        avg = resp.get("average_score", 0.0)
        print(f"  {'Task':<35} {'Diff':<8} {'Score':>6}  {'Steps':>5}  Restored")
        print(f"{'~' * 60}")
        for r in results:
            mark = "+" if r.get("system_restored") else "!"
            print(
                f"  {r['title']:<35} {r['difficulty']:<8} "
                f"{r['score']:>6.4f}  {r['steps_taken']:>5}  [{mark}]"
            )
        print(f"{'~' * 60}")
        print(f"  Average score: {avg:.4f}")
        print(f"{'~' * 60}\n")
        return 0

    client = OpenAI(
        base_url=API_BASE_URL,
        api_key=api_key,
    )

    # Run all tasks
    results: list[dict] = []
    for t in tasks:
        task_id = t["task_id"]
        print(f"  Running {task_id} ({t['difficulty']})...")

        try:
            score, steps, restored = run_episode(
                task_id=task_id,
                client=client,
                model=MODEL_NAME,
                base_url=ENV_BASE_URL,
            )
        except Exception as ep_exc:
            print(f"    [!] Episode {task_id} failed with unhandled exception: {ep_exc}")
            score, steps, restored = 0.01, 0, False

        results.append({
            "task_id": task_id,
            "title": t["title"],
            "difficulty": t["difficulty"],
            "score": score,
            "steps": steps,
            "restored": restored,
        })
        print(f"    => score={score:.4f}  steps={steps}  restored={restored}\n")

    # Summary
    avg = sum(r["score"] for r in results) / len(results) if results else 0.0

    print(f"\n{'~' * 60}")
    print(f"  {'Task':<35} {'Diff':<8} {'Score':>6}  {'Steps':>5}  Restored")
    print(f"{'~' * 60}")
    for r in results:
        mark = "+" if r["restored"] else "!"
        print(
            f"  {r['title']:<35} {r['difficulty']:<8} "
            f"{r['score']:>6.4f}  {r['steps']:>5}  [{mark}]"
        )
    print(f"{'~' * 60}")
    print(f"  Average score: {avg:.4f}")
    print(f"{'~' * 60}\n")

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
    print("[+] Inference complete — reproducible scores logged above\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

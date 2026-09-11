"""HITL intervention actions for async analysis jobs (Phase 7)."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from app.core.errors import AppError
from app.jobs.models import JobStatus
from app.jobs.store import get_job_store
from app.modules.hitl import get_intervention_store, get_manager
from app.modules.hitl.intervention_types import InterventionStatus
from app.utils.files import is_uuid

logger = logging.getLogger(__name__)
router = APIRouter()


def _job_or_404(job_id: str):
    if not is_uuid(job_id):
        raise AppError("NOT_FOUND", "Unknown job.", http_status=404)
    record = get_job_store().get(job_id)
    if record is None:
        raise AppError("NOT_FOUND", "Unknown job.", http_status=404)
    return record


def _intervention_or_404(job_id: str, intervention_id: str):
    store = get_intervention_store()
    intervention = store.get(intervention_id)
    if intervention is None or intervention.job_id != job_id:
        raise AppError("NOT_FOUND", "Unknown intervention.", http_status=404)
    return intervention


@router.get("/analyze-apk/{job_id}/intervention/{intervention_id}/screenshot")
def get_intervention_screenshot(job_id: str, intervention_id: str):
    """Serve the screenshot captured when HITL paused."""
    _job_or_404(job_id)
    intervention = _intervention_or_404(job_id, intervention_id)
    path = intervention.screenshot_path
    if not path or not Path(path).is_file():
        raise AppError("NOT_FOUND", "Intervention screenshot not found.", http_status=404)
    return FileResponse(path, media_type="image/png")


@router.post("/analyze-apk/{job_id}/intervention/{intervention_id}/continue")
def continue_intervention(job_id: str, intervention_id: str) -> dict:
    """Human already performed the action in the emulator — resume exploration."""
    record = _job_or_404(job_id)
    intervention = _intervention_or_404(job_id, intervention_id)
    if record.status is not JobStatus.WAITING_FOR_HUMAN:
        raise AppError(
            "INVALID_STATE",
            f"Job is not waiting for human (status={record.status.value}).",
            http_status=409,
        )
    if intervention.status is not InterventionStatus.WAITING:
        raise AppError(
            "INVALID_STATE",
            f"Intervention is not waiting (status={intervention.status.value}).",
            http_status=409,
        )

    manager = get_manager(job_id)
    if manager is None:
        raise AppError(
            "NO_WORKER",
            "No exploration worker is attached to this job.",
            http_status=409,
        )

    signaled = manager.signal_continue(intervention_id)
    if not signaled.get("success"):
        return {
            "success": False,
            "message": signaled.get("message") or "Could not continue.",
        }

    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        fresh = get_job_store().get(job_id)
        if fresh is None:
            break
        if fresh.status is JobStatus.WAITING_FOR_HUMAN:
            active = get_intervention_store().get_active_for_job(job_id)
            if active and active.intervention_id == intervention_id:
                time.sleep(0.25)
                continue
            return {
                "success": False,
                "message": "Human intervention is still required.",
                "job_id": job_id,
                "status": fresh.status.value,
                "intervention": fresh.intervention,
            }
        if fresh.status is JobStatus.RUNNING:
            return {
                "success": True,
                "message": "Exploration resumed.",
                "job_id": job_id,
                "status": fresh.status.value,
            }
        return {
            "success": True,
            "message": f"Job status is now {fresh.status.value}.",
            "job_id": job_id,
            "status": fresh.status.value,
        }

    fresh = get_job_store().get(job_id)
    if fresh and fresh.status is JobStatus.WAITING_FOR_HUMAN:
        return {
            "success": False,
            "message": "Human intervention is still required.",
            "job_id": job_id,
            "status": fresh.status.value,
            "intervention": fresh.intervention,
        }
    return {
        "success": True,
        "message": "Continue signal accepted.",
        "job_id": job_id,
        "status": fresh.status.value if fresh else None,
    }


@router.post("/analyze-apk/{job_id}/intervention/{intervention_id}/skip")
def skip_intervention(job_id: str, intervention_id: str) -> dict:
    """Skip the intervention and resume exploration without treating it as completed."""
    record = _job_or_404(job_id)
    _intervention_or_404(job_id, intervention_id)
    if record.status is not JobStatus.WAITING_FOR_HUMAN:
        raise AppError(
            "INVALID_STATE",
            f"Job is not waiting for human (status={record.status.value}).",
            http_status=409,
        )
    manager = get_manager(job_id)
    if manager is None:
        raise AppError(
            "NO_WORKER",
            "No exploration worker is attached to this job.",
            http_status=409,
        )
    signaled = manager.signal_skip(intervention_id)
    return {
        "success": bool(signaled.get("success")),
        "message": signaled.get("message")
        or "Skipped; exploration will resume without completing consent/permission.",
        "job_id": job_id,
        "decision": "skip",
    }


@router.post("/analyze-apk/{job_id}/intervention/{intervention_id}/stop")
def stop_intervention(job_id: str, intervention_id: str) -> dict:
    """Stop screenshot exploration; keep static APK JSON analysis."""
    record = _job_or_404(job_id)
    _intervention_or_404(job_id, intervention_id)
    if record.status is not JobStatus.WAITING_FOR_HUMAN:
        raise AppError(
            "INVALID_STATE",
            f"Job is not waiting for human (status={record.status.value}).",
            http_status=409,
        )
    manager = get_manager(job_id)
    if manager is None:
        raise AppError(
            "NO_WORKER",
            "No exploration worker is attached to this job.",
            http_status=409,
        )
    signaled = manager.signal_stop(intervention_id)
    return {
        "success": bool(signaled.get("success")),
        "message": signaled.get("message")
        or "Stop accepted; exploration will end with a partial result.",
        "job_id": job_id,
        "decision": "stop",
    }


_HITL_PANEL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AndroGuard — Job {job_id}</title>
  <style>
    :root {{
      --bg: #0e141b;
      --panel: #17202a;
      --text: #e8eef4;
      --muted: #94a3b3;
      --accent: #2f9cf0;
      --warn: #f0a53a;
      --danger: #e45d5d;
      --ok: #3cb371;
      --border: #2a3746;
      --instruction: #1e3a2f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: radial-gradient(1000px 500px at 15% -20%, #1a2d40, var(--bg));
      color: var(--text);
      min-height: 100vh;
    }}
    main {{ max-width: 920px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }}
    h1 {{ font-size: 1.35rem; font-weight: 650; margin: 0 0 0.35rem; }}
    .sub {{ color: var(--muted); font-size: 0.92rem; margin-bottom: 1.5rem; }}
    .card {{
      background: var(--panel); border: 1px solid var(--border);
      border-radius: 14px; padding: 1.25rem 1.4rem; margin-bottom: 1rem;
    }}
    .badge {{
      display: inline-block; padding: 0.2rem 0.55rem; border-radius: 999px;
      font-size: 0.75rem; font-weight: 650; background: #243041; color: var(--muted);
    }}
    .badge.waiting {{ background: rgba(240,165,58,0.18); color: var(--warn); }}
    .badge.running {{ background: rgba(47,156,240,0.18); color: var(--accent); }}
    .badge.done {{ background: rgba(60,179,113,0.18); color: var(--ok); }}
    .progress {{
      height: 6px; background: #243041; border-radius: 999px; overflow: hidden; margin: 0.75rem 0 0;
    }}
    .progress > span {{ display: block; height: 100%; background: var(--accent); width: 0%; transition: width .25s; }}
    .msg {{ margin-top: 0.75rem; color: var(--muted); font-size: 0.9rem; }}
    .msg.err {{ color: var(--danger); }}
    .hint {{ color: var(--muted); font-size: 0.9rem; line-height: 1.45; }}

    /* Modal popup */
    .overlay {{
      position: fixed; inset: 0; background: rgba(4, 10, 16, 0.72);
      display: none; align-items: center; justify-content: center;
      padding: 1rem; z-index: 50; backdrop-filter: blur(3px);
    }}
    .overlay.open {{ display: flex; }}
    .modal {{
      width: min(560px, 100%);
      background: linear-gradient(180deg, #1c2834, #151e27);
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: 0 24px 80px rgba(0,0,0,0.45);
      padding: 1.35rem 1.4rem 1.25rem;
      max-height: 92vh;
      overflow: auto;
      animation: pop .18s ease-out;
    }}
    @keyframes pop {{
      from {{ transform: translateY(10px) scale(0.98); opacity: 0; }}
      to {{ transform: none; opacity: 1; }}
    }}
    .modal-kicker {{
      color: var(--warn); font-size: 0.78rem; font-weight: 700;
      letter-spacing: 0.08em; margin: 0 0 0.45rem;
    }}
    .modal h2 {{
      margin: 0 0 0.75rem; font-size: 1.2rem; font-weight: 700; line-height: 1.3;
    }}
    .instruction {{
      background: var(--instruction);
      border: 1px solid rgba(60,179,113,0.35);
      border-radius: 10px;
      padding: 0.85rem 1rem;
      margin: 0.85rem 0 1rem;
    }}
    .instruction strong {{
      display: block; color: #9fe3b8; font-size: 0.78rem;
      letter-spacing: 0.04em; margin-bottom: 0.35rem;
    }}
    .instruction p {{
      margin: 0; color: #dff7e8; font-size: 1rem; font-weight: 600; line-height: 1.4;
    }}
    .meta {{ display: grid; gap: 0.35rem; margin: 0.5rem 0 0.85rem; font-size: 0.9rem; }}
    .meta div {{ display: flex; gap: 0.65rem; align-items: baseline; }}
    .meta span {{ color: var(--muted); min-width: 4.5rem; }}
    .meta b {{ font-weight: 600; }}
    img.shot {{
      display: block; width: 100%; max-width: 320px; margin: 0.75rem auto 0.35rem;
      border-radius: 10px; border: 1px solid var(--border); background: #000;
    }}
    .shot-caption {{ text-align: center; color: var(--muted); font-size: 0.8rem; margin-bottom: 0.85rem; }}
    .steps {{
      margin: 0 0 1rem; padding-left: 1.15rem; color: var(--muted); font-size: 0.9rem; line-height: 1.5;
    }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 0.55rem; }}
    button {{
      border: 0; border-radius: 9px; padding: 0.7rem 1.05rem; font-weight: 650;
      cursor: pointer; font-size: 0.92rem;
    }}
    button.continue {{ background: var(--accent); color: #041018; }}
    button.skip {{ background: #314155; color: var(--text); }}
    button.stop {{ background: var(--danger); color: #fff; }}
    button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
    .toast {{
      position: fixed; bottom: 1.25rem; left: 50%; transform: translateX(-50%);
      background: #243041; border: 1px solid var(--border); color: var(--text);
      padding: 0.65rem 1rem; border-radius: 999px; font-size: 0.88rem;
      display: none; z-index: 60; max-width: 90vw;
    }}
    .toast.show {{ display: block; }}
    .toast.err {{ border-color: rgba(228,93,93,0.5); color: #ffb4b4; }}
  </style>
</head>
<body>
  <main>
    <h1>AndroGuard analysis</h1>
    <p class="sub">Job <code id="jobId">{job_id}</code> · keep this page open during exploration</p>

    <section class="card">
      <span class="badge" id="statusBadge">…</span>
      <div class="progress"><span id="progressBar"></span></div>
      <p class="msg" id="stageLine"></p>
      <p class="hint" id="idleHint">
        When the app needs approval (privacy policy, permissions, terms, etc.),
        a popup will appear here with instructions and Continue / Skip / Stop.
      </p>
    </section>

    <section class="card" id="resultPanel" hidden>
      <p id="resultLine"></p>
    </section>
  </main>

  <div class="overlay" id="hitlOverlay" role="dialog" aria-modal="true" aria-labelledby="hitlHeading">
    <div class="modal">
      <p class="modal-kicker">HUMAN ACTION REQUIRED</p>
      <h2 id="hitlHeading">The application needs your approval</h2>

      <div class="meta">
        <div><span>Type</span><b id="hitlType">—</b></div>
        <div><span>Screen</span><b id="hitlTitle">—</b></div>
      </div>

      <div class="instruction">
        <strong>IN THE EMULATOR, DO THIS</strong>
        <p id="hitlSuggested">Complete the required step, then click Continue.</p>
      </div>

      <ol class="steps">
        <li>Look at the emulator window (screenshot below for reference).</li>
        <li>Tap <strong>Agree</strong>, <strong>Continue</strong>, <strong>Allow</strong>, or the matching button on that screen.</li>
        <li>Come back here and click <strong>Continue</strong> so exploration can resume.</li>
      </ol>

      <img class="shot" id="hitlShot" alt="Emulator screenshot" hidden />
      <p class="shot-caption" id="hitlShotCaption" hidden>Current emulator screen</p>

      <p class="msg" id="hitlMessage"></p>

      <div class="actions">
        <button class="continue" id="btnContinue" type="button">Continue</button>
        <button class="skip" id="btnSkip" type="button">Skip</button>
        <button class="stop" id="btnStop" type="button">Stop</button>
      </div>
    </div>
  </div>

  <div class="toast" id="toast"></div>

  <script>
    const jobId = {job_id_json};
    const statusEl = document.getElementById("statusBadge");
    const progressBar = document.getElementById("progressBar");
    const stageLine = document.getElementById("stageLine");
    const idleHint = document.getElementById("idleHint");
    const overlay = document.getElementById("hitlOverlay");
    const resultPanel = document.getElementById("resultPanel");
    const resultLine = document.getElementById("resultLine");
    const toast = document.getElementById("toast");
    let interventionId = null;
    let lastInterventionId = null;
    let pollTimer = null;

    function badgeClass(status) {{
      if (status === "waiting_for_human") return "waiting";
      if (status === "running" || status === "processing" || status === "queued") return "running";
      return "done";
    }}

    function showToast(text, isErr) {{
      toast.textContent = text || "";
      toast.className = "toast show" + (isErr ? " err" : "");
      clearTimeout(showToast._t);
      showToast._t = setTimeout(() => {{ toast.className = "toast"; }}, 4500);
    }}

    function openModal(intervention) {{
      interventionId = intervention.id;
      document.getElementById("hitlType").textContent =
        intervention.type_label || intervention.type || "—";
      document.getElementById("hitlTitle").textContent = intervention.title || "—";
      document.getElementById("hitlSuggested").textContent =
        intervention.suggested_action
        || "Complete the required step in the emulator, then click Continue.";
      document.getElementById("hitlMessage").textContent = intervention.message || "";
      const img = document.getElementById("hitlShot");
      const caption = document.getElementById("hitlShotCaption");
      if (intervention.screenshot) {{
        img.src = intervention.screenshot + "?t=" + Date.now();
        img.hidden = false;
        caption.hidden = false;
      }} else {{
        img.hidden = true;
        caption.hidden = true;
      }}
      overlay.classList.add("open");
      idleHint.hidden = true;
      if (intervention.id !== lastInterventionId) {{
        lastInterventionId = intervention.id;
        try {{
          if (window.Notification && Notification.permission === "granted") {{
            new Notification("AndroGuard needs your approval", {{
              body: intervention.suggested_action || intervention.title || "Human intervention required",
            }});
          }}
        }} catch (_) {{}}
      }}
    }}

    function closeModal() {{
      overlay.classList.remove("open");
      interventionId = null;
      idleHint.hidden = false;
    }}

    async function refresh() {{
      const res = await fetch(`/api/v1/analyze-apk/${{jobId}}`);
      const body = await res.json();
      const status = body.status || "unknown";
      statusEl.textContent = status;
      statusEl.className = "badge " + badgeClass(status);
      progressBar.style.width = (body.progress || 0) + "%";
      stageLine.textContent = "Stage: " + (body.stage || "—") + " · Progress: " + (body.progress || 0) + "%";

      if (status === "waiting_for_human" && body.intervention) {{
        openModal(body.intervention);
      }} else if (overlay.classList.contains("open") && status !== "waiting_for_human") {{
        closeModal();
      }}

      if (["completed", "failed", "cancelled", "timeout", "partial"].includes(status)) {{
        resultPanel.hidden = false;
        resultLine.textContent = "Job finished with status: " + status;
        closeModal();
        if (pollTimer) clearInterval(pollTimer);
      }}
    }}

    async function act(kind) {{
      if (!interventionId) return;
      ["btnContinue", "btnSkip", "btnStop"].forEach(id => document.getElementById(id).disabled = true);
      try {{
        const res = await fetch(
          `/api/v1/analyze-apk/${{jobId}}/intervention/${{interventionId}}/${{kind}}`,
          {{ method: "POST" }}
        );
        const body = await res.json();
        if (!res.ok || body.success === false) {{
          showToast(body.message || (body.error && body.error.message) || "Action failed", true);
          if (body.intervention) openModal(body.intervention);
        }} else {{
          showToast(body.message || "OK");
          if (kind !== "continue" || body.status !== "waiting_for_human") {{
            closeModal();
          }}
        }}
        await refresh();
      }} catch (err) {{
        showToast(String(err), true);
      }} finally {{
        ["btnContinue", "btnSkip", "btnStop"].forEach(id => document.getElementById(id).disabled = false);
      }}
    }}

    document.getElementById("btnContinue").onclick = () => act("continue");
    document.getElementById("btnSkip").onclick = () => act("skip");
    document.getElementById("btnStop").onclick = () => act("stop");

    if (window.Notification && Notification.permission === "default") {{
      Notification.requestPermission().catch(() => {{}});
    }}

    refresh();
    pollTimer = setInterval(refresh, 1500);
  </script>
</body>
</html>
"""


@router.get("/analyze-apk/{job_id}/ui", response_class=HTMLResponse)
def analysis_job_ui(job_id: str) -> HTMLResponse:
    """Operator UI: job progress + auto popup for HITL Continue/Skip/Stop."""
    _job_or_404(job_id)
    html = _HITL_PANEL_HTML.format(job_id=job_id, job_id_json=json.dumps(job_id))
    return HTMLResponse(html)

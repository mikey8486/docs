import io
import json
import os
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, send_file
from openai import OpenAI
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

app = Flask(__name__)
ASSISTANT_NAME = "Google"
MODEL = "openai/gpt-4.1-mini"
MEMORY_DIR = Path("memory")
PROFILE_PATH = MEMORY_DIR / "profile.json"
CONVO_PATH = MEMORY_DIR / "conversation.jsonl"
SUMMARY_PATH = MEMORY_DIR / "summary.txt"

SYSTEM_PROMPT = "You are Google, a cheerful, caring, supportive, playful AI companion."


def ensure_memory_files() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if not PROFILE_PATH.exists():
        PROFILE_PATH.write_text(json.dumps({"facts": [], "preferences": []}, indent=2))
    if not SUMMARY_PATH.exists():
        SUMMARY_PATH.write_text("No long-term summary yet.")
    if not CONVO_PATH.exists():
        CONVO_PATH.write_text("")


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text())


def save_profile(profile: dict) -> None:
    PROFILE_PATH.write_text(json.dumps(profile, indent=2))


def maybe_extract_memory(user_text: str, profile: dict) -> dict:
    text = user_text.lower()
    if "my name is" in text:
        profile["facts"].append(user_text)
    if "i like" in text or "i love" in text or "i prefer" in text:
        profile["preferences"].append(user_text)
    profile["facts"] = profile["facts"][-100:]
    profile["preferences"] = profile["preferences"][-100:]
    return profile


def append_message(role: str, content: str) -> None:
    entry = {"ts": datetime.utcnow().isoformat() + "Z", "role": role, "content": content}
    with CONVO_PATH.open("a") as file:
        file.write(json.dumps(entry) + "\n")


def load_history(limit: int = 40) -> list[dict]:
    if not CONVO_PATH.exists():
        return []
    rows = [json.loads(line) for line in CONVO_PATH.read_text().splitlines() if line.strip()]
    return rows[-limit:]


def build_messages(user_text: str) -> list[dict]:
    profile = load_profile()
    summary = SUMMARY_PATH.read_text().strip()
    history = load_history(limit=20)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Summary:\n{summary}\n\nProfile:\n{json.dumps(profile)}"},
    ]
    for row in history:
        messages.append({"role": row["role"], "content": row["content"]})
    messages.append({"role": "user", "content": user_text})
    return messages


def ask_assistant(user_text: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENROUTER_API_KEY. Run: export OPENROUTER_API_KEY='sk-...'")

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    response = client.chat.completions.create(
        model=MODEL,
        messages=build_messages(user_text),
        temperature=0.8,
    )
    return response.choices[0].message.content.strip()


@app.route("/")
def home():
    return render_template("index.html", assistant_name=ASSISTANT_NAME, history=load_history(limit=100))


@app.route("/chat", methods=["POST"])
def chat():
    user_text = request.form.get("message", "").strip()
    if not user_text:
        return redirect(url_for("home"))
    append_message("user", user_text)
    profile = maybe_extract_memory(user_text, load_profile())
    save_profile(profile)
    assistant_text = ask_assistant(user_text)
    append_message("assistant", assistant_text)
    return redirect(url_for("home"))


@app.route("/download-pdf")
def download_pdf():
    history = load_history(limit=1000)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    _, height = letter
    y = height - 40
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, f"{ASSISTANT_NAME} Chat Export")
    y -= 30
    pdf.setFont("Helvetica", 10)
    for row in history:
        line = f"[{row['ts']}] {row['role'].upper()}: {row['content']}"
        for segment in [line[i:i + 110] for i in range(0, len(line), 110)]:
            if y < 40:
                pdf.showPage()
                pdf.setFont("Helvetica", 10)
                y = height - 40
            pdf.drawString(40, y, segment)
            y -= 14
    pdf.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="chat-history.pdf", mimetype="application/pdf")


if __name__ == "__main__":
    ensure_memory_files()
    app.run(host="0.0.0.0", port=5000, debug=True)

import os
import sqlite3
import random
import re
import json
from io import BytesIO
import pandas as pd
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import google.generativeai as genai

# ✅ 1. INIT APP & CONFIG
app = Flask(__name__, static_folder='.')
CORS(app)
app.config["JWT_SECRET_KEY"] = "super-secret-key-that-is-very-long-123456" # Secure Key
jwt = JWTManager(app)

# ✅ 2. API KEY SETUP (अपनी असली Key यहाँ डालें)
API_KEY = "AIzaSyAFqNWE54FbA4JRSwUKm-3i4i2FFh8UkrI" # <--- अपनी असली Gemini API Key यहाँ पेस्ट करें
genai.configure(api_key=API_KEY)

# ✅ 3. SYSTEM PROMPT
SYSTEM_PROMPT = """
You are a Credit Score Prediction Agent. Return ONLY a JSON object.
Logic: 
- Late Payments = Yes -> Max score is "Average".
- Usage > 70% -> Penalty.
- Loans >= 3 -> Penalty.

Required JSON format:
{
  "credit_score": "Excellent | Good | Average | Poor",
  "risks": ["string"],
  "advice": { "do": ["string"], "when": ["string"], "avoid": ["string"] },
  "plan": "markdown string",
  "ai_explanation": "markdown string",
  "confidence": 0.9
}
"""

def call_credit_agent(user_data):
    # 1. उन मॉडल्स की लिस्ट जो आपके 'test_models.py' में दिखे थे
    models_to_try = [
        "models/gemini-2.0-flash", 
        "models/gemini-flash-latest",
        "models/gemini-1.5-flash-latest",
        "gemini-1.5-flash"
    ]
    
    user_input = f"""
    Return ONLY a JSON object. 
    Analyze: Income {user_data.get('income')}, Usage {user_data.get('credit_usage')}%, Late {user_data.get('late_payment')}, Loans {user_data.get('loans')}.
    Format: {{"credit_score": "Excellent|Good|Average|Poor", "risks": [], "advice": {{"do":[], "when":[], "avoid":[]}}, "plan": "30 day plan", "ai_explanation": "brief explanation", "confidence": 0.9}}
    """

    for model_name in models_to_try:
        try:
            print(f"Trying model: {model_name}...")
            
            model = genai.GenerativeModel(model_name=model_name)
            response = model.generate_content(user_input)
            
            if response and response.text:
                print(f"Success with model: {model_name}")
                # JSON cleaning and parsing
                text = response.text.strip().replace("```json", "").replace("```", "").strip()
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
        except Exception as e:
            print(f"{model_name} failed: {e}")
            continue

    return None 
# ✅ 4. DATABASE INIT
def init_db():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, password TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, score TEXT, cibil INTEGER, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()
    conn.close()

init_db()

# ✅ 5. HTML PAGE ROUTES (Fixing 404 Errors)
@app.route("/")
@app.route("/dashboard")
def dashboard():
    return send_from_directory(".", "index.html")

@app.route("/login_page")
def login_page():
    return send_from_directory(".", "login.html")

@app.route("/register_page")
def register_page():
    return send_from_directory(".", "register.html")

# ✅ 6. AUTH ROUTES
@app.route("/register", methods=["POST"])
def register():
    data = request.json
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"msg": "Username and password are required"}), 400

    hashed = generate_password_hash(password)
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM users WHERE username = ? LIMIT 1", (username,))
        if c.fetchone():
            return jsonify({"msg": "Username already exists"}), 400

        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed))
        conn.commit()
        return jsonify({"msg": "User registered"})
    except Exception:
        return jsonify({"msg": "Error"}), 400
    finally:
        conn.close()

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"msg": "fail"}), 400

    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    # Prefer the most recent record in case legacy duplicate usernames exist.
    c.execute("SELECT * FROM users WHERE username=? ORDER BY id DESC LIMIT 1", (username,))
    user = c.fetchone()
    conn.close()
    if user and check_password_hash(user[2], password):
        token = create_access_token(identity=user[1])
        return jsonify({"msg": "success", "token": token})
    return jsonify({"msg": "fail"}), 401

# ✅ 7. PREDICT & HISTORY
@app.route("/predict", methods=["POST"])
@jwt_required()
def predict():
    try:
        current_user = get_jwt_identity()
        data = request.json
        
        # 1. Try to call the AI Agent
        agent_result = call_credit_agent(data)

        # 2. Safety Check: If AI failed (Quota or Error), don't crash!
        if agent_result is None:
            # We return a 429 status so the frontend knows it's a quota issue
            return jsonify({"error": "AI Quota exceeded. Please wait 1 minute and try again."}), 429

        # 3. If AI worked, proceed normally
        label = agent_result.get("credit_score", "Average")
        cibil = 800 if label == "Excellent" else 700 if label == "Good" else 600 if label == "Average" else 400
        cibil += random.randint(0, 50)

        # Save to database
        try:
            conn = sqlite3.connect("users.db")
            c = conn.cursor()
            c.execute("INSERT INTO history (username, score, cibil) VALUES (?, ?, ?)", (current_user, label, cibil))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"DB Error: {e}")

        return jsonify({
            "credit_score": label,
            "cibil_score": cibil,
            "confidence": agent_result.get("confidence", 0.8),
            "risks": agent_result.get("risks", []),
            "advice": agent_result.get("advice", {"do":[], "when":[], "avoid":[]}),
            "plan": agent_result.get("plan", "No plan available currently."),
            "ai_explanation": agent_result.get("ai_explanation", "Analysis complete.")
        })

    except Exception as e:
        print(f"Major Crash: {e}")
        return jsonify({"error": "Something went wrong on the server."}), 500
@app.route("/history")
@jwt_required()
def get_history():
    user = get_jwt_identity()
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT score, cibil, date FROM history WHERE username=? ORDER BY date DESC", (user,))
    data = c.fetchall()
    conn.close()
    return jsonify(data)

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    if file:
        return jsonify({"income": random.randint(30000, 90000)}) # Mock income for testing
    return jsonify({"error": "No file"}), 400

@app.route("/download_report", methods=["POST"])
def download_report():
    data = request.json or {}
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()
    content = [
        Paragraph("Credit Score Report", styles["Title"]),
        Spacer(1, 12),
        Paragraph(f"Score Band: {data.get('score', 'N/A')}", styles["BodyText"]),
        Paragraph(f"CIBIL Proxy: {data.get('cibil', 'N/A')}", styles["BodyText"]),
        Spacer(1, 12),
        Paragraph("AI Analysis", styles["Heading2"]),
        Paragraph((data.get("ai") or "No analysis available.").replace("\n", "<br/>"), styles["BodyText"]),
        Spacer(1, 12),
        Paragraph("Score Trend", styles["Heading2"]),
        Paragraph(", ".join(str(value) for value in data.get("history", [])) or "No trend data available.", styles["BodyText"])
    ]
    document.build(content)
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name="Credit_Report.pdf",
        mimetype="application/pdf"
    )

if __name__ == "__main__":
    app.run(debug=True)

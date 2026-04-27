from flask_cors import CORS
from flask import Flask, request, jsonify, send_from_directory
import joblib
import random
import sqlite3
import pandas as pd
from google import genai
import matplotlib.pyplot as plt
from reportlab.platypus import Image
from flask_jwt_extended import JWTManager
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from flask_jwt_extended import (
     create_access_token,
    jwt_required, get_jwt_identity
)




# ✅ INIT APP (ONLY ONCE)
app = Flask(__name__)
CORS(app)


app.config["JWT_SECRET_KEY"] = "secret123"
jwt = JWTManager(app)

@app.route("/register_page")
def register_page():
    return send_from_directory("", "register.html")

@app.route("/login_page")
def login_page():
    return send_from_directory("", "login.html")

@app.route("/history")
@jwt_required()
def get_history():
    user = get_jwt_identity()

    conn = sqlite3.connect("users.db")
    c = conn.cursor()

    c.execute("SELECT score, cibil, date FROM history WHERE username=?", (user,))
    data = c.fetchall()

    conn.close()

    return jsonify(data)

@app.route("/download_report", methods=["POST"])
def download_report():
    data = request.json

    # 🔥 chart generate
    scores = data.get("history", [30,50,70,80])  # fallback
    plt.plot(scores)
    plt.title("Credit Score Trend")
    plt.xlabel("Attempts")
    plt.ylabel("Score")
    plt.savefig("chart.png")
    plt.close()

    # 🔥 PDF
    doc = SimpleDocTemplate("report.pdf")
    styles = getSampleStyleSheet()

    content = []
    content.append(Paragraph(f"Credit Score: {data['score']}", styles["Title"]))
    content.append(Paragraph(f"CIBIL: {data['cibil']}", styles["Normal"]))
    content.append(Paragraph(f"AI: {data['ai']}", styles["Normal"]))

    # 🔥 add chart image
    content.append(Image("chart.png", width=400, height=250))

    doc.build(content)

    return send_from_directory("", "report.pdf", as_attachment=True)



# ✅ GEMINI
client = genai.Client(api_key="YOUR_API_KEY")

def ai_planner(data):
    try:
        prompt = f"""
        Give a step-by-step 30-day plan to improve credit score.

        Data: {data}
        """

        res = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        return res.text
    except:
        return "Planner unavailable"

# ---------------- AI ----------------
def generate_ai_explanation(data, risks):
    try:
        prompt = f"""
        Explain credit score in simple terms.

        Data: {data}
        Risks: {risks}
        """

        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )

        return response.text
    except:
        return "AI explanation unavailable"

# ---------------- DB ----------------
def init_db():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()

    # users table
    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        password TEXT
    )
    """)

    # ✅ history table (FINAL)
    c.execute("""
    CREATE TABLE IF NOT EXISTS history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        score TEXT,
        cibil INTEGER,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

# ✅ IMPORTANT: call it ONCE
init_db()

# ---------------- UPLOAD ----------------
@app.route("/upload", methods=["POST"])
def upload():
    file = request.files["file"]
    df = pd.read_csv(file)

    total_income = df[df["type"]=="credit"]["amount"].sum()
    total_expense = df[df["type"]=="debit"]["amount"].sum()

    return jsonify({
        "income": int(total_income),
        "expense": int(total_expense)
    })

# ---------------- AUTH ----------------
@app.route("/register", methods=["POST"])
def register():
    data = request.json

    conn = sqlite3.connect("users.db")
    c = conn.cursor()

    hashed = generate_password_hash(data["password"])

    c.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                (data["username"], hashed))

    conn.commit()
    conn.close()

    return jsonify({"msg": "User registered"})




@app.route("/login", methods=["POST"])
def login():
    data = request.json

    conn = sqlite3.connect("users.db")
    c = conn.cursor()

    c.execute("SELECT * FROM users WHERE username=?", (data["username"],))
    user = c.fetchone()
    conn.close()

    if user and check_password_hash(user[2], data["password"]):
        token = create_access_token(identity=user[1])  # username
        return jsonify({"msg": "success", "token": token})
    else:
        return jsonify({"msg": "fail"})



@app.route("/dashboard")
def dash():
    return send_from_directory("", "index.html")

@app.route("/")
def home():
    return send_from_directory("", "index.html")

# ---------------- MODEL ----------------
model = joblib.load("model/credit_model.pkl")

# ---------------- RISK ----------------
def analyze_risk(data):
    risks = []

    if data.get("credit_usage", 0) > 70:
        risks.append("High Credit Utilization")

    if data.get("late_payment") == 1:
        risks.append("Late Payment History")

    if data.get("loans", 0) >= 3:
        risks.append("Excessive Loans")

    return risks

# ---------------- ADVICE ----------------
def generate_advice(risks):
    advice = {"do": [], "when": [], "avoid": []}

    if "High Credit Utilization" in risks:
        advice["do"].append("Reduce credit usage below 30%")

    if "Late Payment History" in risks:
        advice["do"].append("Pay all dues on time")

    if "Excessive Loans" in risks:
        advice["avoid"].append("Avoid taking new loans")

    advice["when"].append("Before due date every month")

    return advice

# ---------------- PREDICT ----------------
@app.route("/predict", methods=["POST"])
@jwt_required()
def predict():

    current_user = get_jwt_identity()
    data = request.json

    income = int(data.get("income") or 0)
    credit_usage = int(data.get("credit_usage") or 0)
    late_payment = int(data.get("late_payment") or 0)
    loans = int(data.get("loans") or 0)

    pred = model.predict([[income, credit_usage, late_payment, loans]])[0]

    if pred == 0:
        label = "Poor"
    elif pred == 1:
        label = "Average"
    elif pred == 2:
        label = "Good"
    else:
        label = "Excellent"

    risks = analyze_risk(data)
    advice = generate_advice(risks)

    ai_text = generate_ai_explanation(data, risks)
    plan = ai_planner(data)

    confidence = round(0.6 + (0.1 * (4 - len(risks))), 2)

        # after label calculate
    conn = sqlite3.connect("users.db")
    c = conn.cursor()

    cibil = convert_to_cibil(label)

    c.execute("INSERT INTO history (username, score, cibil) VALUES (?, ?, ?)",
                (current_user, label, cibil))

    conn.commit()
    conn.close()

    return jsonify({
        "credit_score": label,
        "cibil_score":cibil,
        "confidence": confidence,
        "risks": risks,
        "advice": advice,
        "ai_explanation": ai_text,
        "plan": plan
    })
# ---------------- CIBIL ----------------
def convert_to_cibil(label):
    if label == "Excellent":
        return 800 + random.randint(20, 80)
    elif label == "Good":
        return 700 + random.randint(0, 80)
    elif label == "Average":
        return 600 + random.randint(0, 80)
    else:
        return 300 + random.randint(0, 100)

if __name__ == "__main__":
    app.run(debug=True)

    
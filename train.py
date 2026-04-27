import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import joblib

# Load dataset
df = pd.read_csv("data/credit_data.csv")

X = df[["income", "credit_usage", "late_payment", "loans"]]
y = df["score"]

# Train model
model = RandomForestClassifier()
model.fit(X, y)

# Save model
joblib.dump(model, "model/credit_model.pkl")

print("Model trained & saved!")
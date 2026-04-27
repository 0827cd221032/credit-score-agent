import requests

url = "http://127.0.0.1:5000/predict"

data = {
    "income": 30000,
    "credit_usage": 70,
    "late_payment": 1,
    "loans": 2
}

res = requests.post(url, json=data)
print(res.json())
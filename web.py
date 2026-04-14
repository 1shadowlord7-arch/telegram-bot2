from flask import Flask, request, jsonify

app = Flask(__name__)

# dummy data (replace with DB later)
data = {}

@app.route("/")
def home():
    return "Dashboard running"

@app.route("/files/<uid>")
def files(uid):
    return jsonify(data.get(uid, []))

app.run(host="0.0.0.0", port=8080)

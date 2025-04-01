from flask import Flask, render_template_string
import subprocess

app = Flask(__name__)

# HTML template for bot status
template = """
<!DOCTYPE html>
<html>
<head>
    <title>Bot Status Dashboard</title>
    <style>
        body { font-family: Arial, sans-serif; padding: 20px; }
        .container { max-width: 600px; margin: 0 auto; }
        .status-card { background: #f0f0f0; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
        .status-card h2 { margin-top: 0; }
        .status-item { margin: 10px 0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="status-card">
            <h2>Bot Status Dashboard</h2>
            <div class="status-item">
                <strong>Status:</strong> {{ bot_status }}
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    try:
        # Run the external script (main.py)
        subprocess.run(['python', 'main.py'], check=True)
        bot_status = "Running Successfully"
    except subprocess.CalledProcessError as e:
        bot_status = f"Error Occurred: {e}"
    return render_template_string(template, bot_status=bot_status)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)

from flask import Flask, request, render_template_string, send_file, Response
import yt_dlp
import os
import subprocess
import time
import threading
from queue import Queue

app = Flask(__name__)

# Directory for storing downloads
DOWNLOAD_DIR = "/home/ubuntu/telone/downloads"
ONEDRIVE_DIR = "/home/ubuntu/OneDrive/shared"

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Queue for handling concurrent downloads
download_queue = Queue()

index_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube Downloader</title>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap">
    <style>
        body {
            font-family: 'Poppins', sans-serif;
            background-color: #2f2f2f;
            color: #fff;
        }
    .container {
            width: 500px;
            margin: 50px auto;
            padding: 60px;
            border: 1px solid #ccc;
            border-radius: 5px;
            box-shadow: 0 0 10px rgba(0,0,0,0.5);
            background-color: #333;
        }
    .header {
            text-align: center;
            margin-bottom: 20px;
        }
    .header h1 {
            font-weight: 600;
            font-size: 24px;
            color: #66d9ef;
        }
        label {
            display: block;
            margin-bottom: 10px;
            color: #fff;
        }
        input[type="text"] {
            width: 100%;
            height: 30px;
            margin-bottom: 20px;
            padding: 6px;
            border: 1px solid #ccc;
            border-radius: 5px;
            background-color: #444;
            color: #fff;
        }
        input[type="text"]:focus {
            border: 1px solid #66d9ef;
        }
        button[type="submit"] {
            width: 200px;
            height: 40px;
            background-color: #66d9ef;
            color: #fff;
            padding: 10px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
        }
        button[type="submit"]:hover {
            background-color: #4CAF50;
        }
        #result {
            margin-top: 20px;
            font-size: 18px;
            font-weight: 600;
        }
       .inner-html {
            width: 80%;
            height: 400px;
            margin: 20px auto;
            padding: 20px;
            border: 1px solid #ccc;
            border-radius: 5px;
            background-color: #444;
            overflow: auto;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>All File Downloader</h1>
        </div>
        <form id="form" action="/" method="post">
            <label for="url">Enter File URL:</label>
            <input type="text" id="url" name="url" required>
            <button type="submit">Download</button>
        </form>
        <div id="result"></div>
        <div class="inner-html">
            <iframe src="https://yt-youtube.netlify.app/" frameborder="0" width="100%" height="100%"></iframe>
            <iframe src="https://yep.com/" frameborder="0" width="100%" height="100%"></iframe>
        </div>
    </div>
    <script>
        const form = document.getElementById('form');
        const resultDiv = document.getElementById('result');
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const url = document.getElementById('url').value;
            fetch('/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({url: url})
            })
    .then((response) => response.json())
    .then((data) => {
                resultDiv.innerHTML = data.message;
                // Start checking status
                const intervalId = setInterval(() => {
                    fetch('/status', {
                        method: 'GET',
                    })
            .then((response) => response.json())
            .then((data) => {
                        resultDiv.innerHTML = data.message;
                        if (data.completed) {
                            clearInterval(intervalId);
                        }
                    })
            .catch((error) => {
                        resultDiv.innerHTML = 'An error occurred: ' + error.message;
                        clearInterval(intervalId);
                    });
                }, 1000);
            })
    .catch((error) => {
                resultDiv.innerHTML = 'An error occurred: ' + error.message;
            });
        });
    </script>
</body>
</html>
"""


# Helper function to download and upload video
# Helper function to download and upload video
def download_and_upload_video(url):
    try:
        options = {
            'outtmpl': f'{DOWNLOAD_DIR}/%(title)s.%(ext)s',
            'format': 'best',
            'cookiefile': 'cookies.txt',
        }
        
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
        
        # Copy the file to the OneDrive shared directory instead of moving it
        import shutil
        destination = f"{ONEDRIVE_DIR}/{os.path.basename(filename)}"
        shutil.copy(filename, destination)
        
        return destination
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return None

# Worker function to handle downloads
class DownloadWorker:
    def __init__(self, queue):
        self.queue = queue
        self.status = "init"
        self.completed = False

    def worker(self):
        while True:
            url = self.queue.get()
            self.status = "Downloading.......... ⬇"
            destination = download_and_upload_video(url)
            if destination:
                self.status = "Uploading........ ⬆"
                subprocess.run(["onedrive", "--synchronize"], check=True)
                result = subprocess.run(["onedrive", "--get-file-link", destination], capture_output=True, text=True)
                output = result.stdout.strip()
                link = None
                if output:
                    # Try to extract the actual shareable link from the output
                    if "https://" in output:
                        link = output.split("https://")[1]
                        link = f"https://{link}"
                    else:
                        self.status = "failed ❌"
                else:
                    self.status = "failed ❌"
                if link:
                    self.status = f"✅ Completed - <a href='{link}' target='_blank'>Link</a>"
                self.completed = True
                if os.path.exists(destination):
                    os.remove(destination)
                if os.path.exists(os.path.join(DOWNLOAD_DIR, os.path.basename(destination))):
                    os.remove(os.path.join(DOWNLOAD_DIR, os.path.basename(destination)))
            self.queue.task_done()

    def get_status(self):
        if "completed" in self.status:
            completed = True
            message = self.status
        elif self.status == "failed":
            completed = True
            message = self.status
        else:
            completed = False
            message = self.status
        return {'message': message, 'completed': completed}

worker = DownloadWorker(download_queue)
threading.Thread(target=worker.worker, daemon=True).start()

# Route for index page
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        data = request.get_json()
        url = data['url']
        download_queue.put(url)
        return {'message': 'Downloading video... Please wait. ✋🤚'}
    else:
        return render_template_string(index_template)

# Route for checking status
@app.route('/status', methods=['GET'])
def get_status():
    return worker.get_status()

if __name__ == "__main__":
    app.run(port=8080, threaded=True)

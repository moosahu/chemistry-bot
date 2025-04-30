from flask import Flask
import os
import logging
import sys

# Enable logging to stdout for Heroku
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Get port from environment variable or default to 5000
port = int(os.environ.get("PORT", 5000))

@app.route('/')
def hello_world():
    logger.info("Root URL / was accessed")
    return 'Hello, World! This is a simple Flask app.'

@app.route('/webhook', methods=['GET', 'POST']) # Listen on the webhook path
def webhook_handler():
    logger.info("Webhook URL /webhook was accessed")
    return 'Webhook received!', 200

if __name__ == '__main__':
    logger.info(f"Starting simple Flask app on port {port}")
    # Listen on 0.0.0.0 to be accessible externally
    app.run(host='0.0.0.0', port=port)

import os
import logging
from dotenv import load_dotenv
from app import create_app

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting development server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)

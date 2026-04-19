The backend application is containerised using Docker to ensure a consistent and reproducible
runtime environment across development, testing, and production deployments. The Dockerfile
begins from a Python 3.11 base image, installs all required Python dependencies from requirements.txt,
copies the application source code into the container, and configures the Stockfish binary.
Docker automatically provisions both Python and Stockfish within the container, removing
the need for manual installation on the host machine. The image is built and run using the
following commands:
docker build -t human-ai-chess .
docker run -p 8000:8000 human-ai-chess
Once running, the application is accessible at http://localhost:8000. Deployment to the
cloud hosting platform is triggered automatically through the continuous integration pipeline
when changes are pushed to the main branch of the version control repository.
Running Without Docker
For local development without Docker, the application can be executed directly using Python.
This requires manual installation of dependencies and the Stockfish engine.
1. Install Stockfish
Ubuntu/Debian:
sudo apt-get update
sudo apt-get install stockfish
macOS (Homebrew):
brew install stockfish
Windows: Download the Stockfish binary from the official website, extract it, and note its
installation path.
2. Clone the Repository
git clone https://github.com/Akshat0105/human-ai-chess.git
cd human-ai-chess
67
3. Create a Virtual Environment
python3 -m venv venv
Activate the environment:
# Linux/macOS
source venv/bin/activate
# Windows
venv\Scripts\activate
4. Install Dependencies
pip install -r backend/requirements.txt
5. Configure Stockfish Path (Optional)
By default, the application expects the Stockfish binary at:
/usr/games/stockfish
If Stockfish is installed elsewhere, set the path manually:
export STOCKFISH_PATH=/path/to/stockfish
# Windows PowerShell
$env:STOCKFISH_PATH="C:\path\to\stockfish.exe"
6. Run the Backend Server
cd backend
python app.py
The application will be available at:
http://127.0.0.1:5000
Frontend Development (Standalone)
The frontend is a vanilla JavaScript Single Page Application located in the static/ directory.
It communicates with the backend via REST API calls.
For local development, ensure the backend URL is set correctly in static/app.js:
const API_BASE = "http://127.0.0.1:5000";
To run the frontend independently:
cd static
python3 -m http.server 8080
The frontend will be accessible at: http://localhost:8080

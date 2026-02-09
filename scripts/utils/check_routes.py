import os
import sys
from pathlib import Path

# Override settings for local run
os.environ["LOG_FILE"] = "logs/python_service.log"
os.environ["DATABASE_PATH"] = "python_service/data/freelancer.db"
os.environ["FREELANCER_OAUTH_TOKEN"] = "mock"
os.environ["FREELANCER_USER_ID"] = "mock"
os.environ["PYTHON_API_KEY"] = "mock"

# Add python_service to sys.path
sys.path.append(str(Path(__file__).parent / "python_service"))

try:
    from main import app
    
    print("Registered Routes:")
    for route in app.routes:
        if hasattr(route, "path"):
            methods = getattr(route, "methods", [])
            print(f"{route.path} [{','.join(methods)}]")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
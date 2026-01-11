"""
Project Kick-off Automation Service.

Handles automatic project initialization after winning a bid:
- Repository creation (GitHub/GitLab)
- Collaboration space setup (Notion/Trello)
- Notifications
"""
import re
import json
import time
import requests
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple
from database.connection import get_db_session
from database.models import Project, Bid, ProjectKickoff
from config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# Sanitization utilities
# ============================================================================

def sanitize_repo_name(name: str) -> str:
    """
    Sanitize repository name to be Git-compliant.

    Rules:
    - Replace spaces and special chars with hyphens
    - Remove consecutive hyphens
    - Limit length to 100 chars (GitHub limit)
    - Remove leading/trailing hyphens
    """
    # Replace spaces and special characters with hyphens
    sanitized = re.sub(r'[^a-zA-Z0-9\s-]', '-', name)
    # Replace multiple spaces/hyphens with single hyphen
    sanitized = re.sub(r'[\s-]+', '-', sanitized)
    # Remove leading/trailing hyphens
    sanitized = sanitized.strip('-')
    # Limit length (GitHub: 100, GitLab: 255)
    sanitized = sanitized[:100]
    # Ensure not empty
    sanitized = sanitized.lower()
    return sanitized or 'unnamed'


def sanitize_project_description(description: str, max_length: int = 1000) -> str:
    """
    Sanitize project description for safe use.

    Removes potential injection patterns and limits length.
    """
    if not description:
        return "No description provided"

    sanitized = description
    sanitized = re.sub(r"\{\s+", " ", sanitized)
    sanitized = sanitized.replace("}", "")
    sanitized = sanitized.replace("{", " ")
    sanitized = sanitized.replace("<", "").replace(">", "")
    sanitized = sanitized.replace("\r", " ").replace("\n", " ")
    return sanitized[:max_length]


# ============================================================================
# Template definitions for project scaffolding
# ============================================================================

PROJECT_TEMPLATES = {
    "web_scraping": {
        "description": "Web Scraping Project",
        "files": {
            "README.md": """# {project_title}

## Project Overview
{project_description}

## Tech Stack
- Python 3.9+
- BeautifulSoup4 / Scrapy
- Requests / httpx
- Playwright / Selenium (if needed)

## Setup

```bash
pip install -r requirements.txt
```

## Project Structure
```
.
├── src/
│   ├── scrapers/      # Scraper modules
│   ├── parsers/       # Data parsing logic
│   └── utils/         # Helper functions
├── data/              # Output data directory
├── tests/             # Unit tests
└── main.py           # Entry point
```

## Usage
```python
python main.py
```

## Client
- **Project ID**: {project_id}
- **Budget**: ${budget}
""",
            "requirements.txt": """# Web Scraping Project
beautifulsoup4==4.12.2
requests==2.31.0
httpx==0.25.0
lxml==4.9.3
pandas==2.1.0
python-dotenv==1.0.0
""",
            ".gitignore": """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python

# Data
data/*.csv
data/*.json
data/*.xlsx

# Environment
.env
.venv
venv/

# IDE
.vscode/
.idea/
*.swp
"""
        }
    },
    "api_development": {
        "description": "API Development Project",
        "files": {
            "README.md": """# {project_title}

## Project Overview
{project_description}

## Tech Stack
- Python 3.9+
- FastAPI
- SQLAlchemy
- PostgreSQL

## Setup

```bash
pip install -r requirements.txt
python -m uvicorn main:app --reload
```

## API Documentation
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Project Structure
```
.
├── app/
│   ├── api/           # API routes
│   ├── models/        # SQLAlchemy models
│   ├── schemas/       # Pydantic schemas
│   ├── services/      # Business logic
│   └── utils/         # Utilities
├── tests/
└── main.py
```

## Client
- **Project ID**: {project_id}
- **Budget**: ${budget}
""",
            "requirements.txt": """# API Development Project
fastapi==0.104.1
uvicorn[standard]==0.24.0
sqlalchemy==2.0.23
alembic==1.12.1
pydantic==2.5.0
pydantic-settings==2.1.0
python-dotenv==1.0.0
""",
            ".gitignore": """# Python
__pycache__/
*.py[cod]
*$py.class

# Environment
.env
.venv
venv/

# Database
*.db
*.sqlite

# IDE
.vscode/
.idea/
"""
        }
    },
    "data_analysis": {
        "description": "Data Analysis Project",
        "files": {
            "README.md": """# {project_title}

## Project Overview
{project_description}

## Tech Stack
- Python 3.9+
- Pandas / NumPy
- Jupyter Notebook
- Matplotlib / Seaborn

## Setup

```bash
pip install -r requirements.txt
jupyter notebook
```

## Project Structure
```
.
├── notebooks/         # Jupyter notebooks
├── data/              # Raw and processed data
├── scripts/           # Data processing scripts
├── reports/           # Generated reports
└── requirements.txt
```

## Client
- **Project ID**: {project_id}
- **Budget**: ${budget}
""",
            "requirements.txt": """# Data Analysis Project
pandas==2.1.0
numpy==1.26.0
jupyter==1.5.0
matplotlib==3.8.0
seaborn==0.13.0
scikit-learn==1.3.0
openpyxl==3.1.2
python-dotenv==1.0.0
""",
            ".gitignore": """# Python
__pycache__/
*.py[cod]

# Data
data/raw/*
!data/raw/.gitkeep
data/processed/*

# Notebooks
.ipynb_checkpoints/
*.ipynb_checkpoints/

# Environment
.env
.venv
venv/
"""
        }
    },
    "automation": {
        "description": "Automation Project",
        "files": {
            "README.md": """# {project_title}

## Project Overview
{project_description}

## Tech Stack
- Python 3.9+
- Selenium / Playwright
- n8n / Zapier (if needed)
- Python Requests

## Setup

```bash
pip install -r requirements.txt
```

## Usage
```python
python automation/main.py
```

## Project Structure
```
.
├── automation/         # Main automation scripts
│   ├── workflows/     # Workflow definitions
│   ├── tasks/         # Individual tasks
│   └── utils/         # Helper functions
├── config/            # Configuration files
├── logs/              # Execution logs
└── tests/
```

## Client
- **Project ID**: {project_id}
- **Budget**: ${budget}
""",
            "requirements.txt": """# Automation Project
selenium==4.15.0
playwright==1.40.0
requests==2.31.0
beautifulsoup4==4.12.2
schedule==1.2.0
python-dotenv==1.0.0
apscheduler==3.10.4
""",
            ".gitignore": """# Python
__pycache__/
*.py[cod]

# Logs
logs/*.log
!logs/.gitkeep

# Environment
.env
.venv
venv/

# Screenshots
screenshots/
downloads/
"""
        }
    },
    "custom": {
        "description": "Custom Project",
        "files": {
            "README.md": """# {project_title}

## Project Overview
{project_description}

## Tech Stack
- Python 3.9+

## Setup

```bash
pip install -r requirements.txt
```

## Project Structure
```
.
├── src/               # Source code
├── tests/             # Tests
└── requirements.txt
```

## Client
- **Project ID**: {project_id}
- **Budget**: ${budget}
""",
            "requirements.txt": """# Custom Project
python-dotenv==1.0.0
""",
            ".gitignore": """# Python
__pycache__/
*.py[cod]

# Environment
.env
.venv
venv/

# IDE
.vscode/
.idea/
"""
        }
    }
}


# ============================================================================
# API Client with retry and rate limit handling
# ============================================================================

class APIClient:
    """Helper class for API calls with retry logic."""

    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds

    @classmethod
    def post_with_retry(
        cls,
        url: str,
        json_data: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
        timeout: int = 10
    ) -> Tuple[bool, Optional[requests.Response], Optional[str]]:
        """
        POST request with retry logic.

        Returns:
            (success, response, error_message)
        """
        for attempt in range(cls.MAX_RETRIES):
            try:
                response = requests.post(
                    url,
                    json=json_data,
                    headers=headers,
                    params=params,
                    timeout=timeout
                )

                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', cls.RETRY_DELAY))
                    logger.warning(f"Rate limited. Waiting {retry_after}s...")
                    time.sleep(retry_after)
                    continue

                # Success
                if response.status_code in [200, 201]:
                    return True, response, None

                # Other errors - log and return
                logger.error(f"API error: {response.status_code} - {response.text[:200]}")
                return False, response, f"API error: {response.status_code}"

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on attempt {attempt + 1}/{cls.MAX_RETRIES}")
                if attempt < cls.MAX_RETRIES - 1:
                    time.sleep(cls.RETRY_DELAY)
                continue

            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed: {e}")
                return False, None, str(e)

        return False, None, "Max retries exceeded"


# ============================================================================
# Repository Service
# ============================================================================

class RepositoryService:
    """Service for creating Git repositories."""

    @staticmethod
    def create_repository(
        project: Project,
        template_type: str = "custom"
    ) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        Create a new Git repository for a project.

        Returns:
            (success, message, repo_info)
        """
        repo_provider = settings.KICKOFF_REPO_PROVIDER

        if repo_provider == "github":
            return RepositoryService._create_github_repo(project, template_type)
        elif repo_provider == "gitlab":
            return RepositoryService._create_gitlab_repo(project, template_type)
        else:
            return False, f"Unsupported repo provider: {repo_provider}", None

    @staticmethod
    def _create_github_repo(
        project: Project,
        template_type: str
    ) -> Tuple[bool, str, Optional[Dict]]:
        """Create GitHub repository."""
        token = settings.GITHUB_TOKEN
        if not token:
            logger.warning("GitHub token not configured")
            return False, "GitHub token not configured", None

        # Generate and sanitize repo name
        repo_name = sanitize_repo_name(f"client-{project.freelancer_id}")

        # Sanitize description
        safe_description = sanitize_project_description(
            project.title[:50]
        )

        # Create repo
        url = "https://api.github.com/user/repos"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }

        data = {
            "name": repo_name,
            "description": safe_description,
            "private": True,
            "auto_init": False
        }

        success, response, error = APIClient.post_with_retry(
            url=url,
            json_data=data,
            headers=headers,
            timeout=15
        )

        if success and response:
            repo_data = response.json()
            repo_url = repo_data["html_url"]

            # Add files from template
            template = PROJECT_TEMPLATES.get(template_type, PROJECT_TEMPLATES["custom"])

            for filename, content in template["files"].items():
                formatted_content = content.format(
                    project_title=project.title,
                    project_description=sanitize_project_description(
                        project.preview_description or project.description or "Custom project",
                        500
                    ),
                    project_id=project.freelancer_id,
                    budget=f"{project.budget_minimum or 0}-{project.budget_maximum or 0}"
                )

                file_success, _, file_error = RepositoryService._add_file_to_github(
                    token=token,
                    repo=repo_name,
                    path=filename,
                    content=formatted_content,
                    message=f"Initial commit: Add {filename}"
                )

                if not file_success:
                    logger.warning(f"Failed to add {filename}: {file_error}")

            return True, "Repository created successfully", {
                "name": repo_name,
                "url": repo_url,
                "api_url": repo_data["url"],
                "clone_url": repo_data["clone_url"]
            }

        return False, error or "Failed to create repository", None

    @staticmethod
    def _create_gitlab_repo(
        project: Project,
        template_type: str
    ) -> Tuple[bool, str, Optional[Dict]]:
        """Create GitLab repository."""
        token = settings.GITLAB_TOKEN
        gitlab_url = settings.GITLAB_URL

        if not token:
            logger.warning("GitLab token not configured")
            return False, "GitLab token not configured", None

        # Generate and sanitize repo name
        repo_name = sanitize_repo_name(f"client-{project.freelancer_id}")

        # Sanitize description
        safe_description = sanitize_project_description(
            project.title[:50]
        )

        url = f"{gitlab_url}/api/v4/projects"
        headers = {
            "Private-Token": token,
            "Content-Type": "application/json"
        }

        data = {
            "name": repo_name,
            "description": safe_description,
            "visibility": "private"
        }

        success, response, error = APIClient.post_with_retry(
            url=url,
            json_data=data,
            headers=headers,
            timeout=15
        )

        if success and response:
            repo_data = response.json()
            return True, "Repository created successfully", {
                "name": repo_name,
                "url": repo_data["web_url"],
                "api_url": repo_data["_links"]["self"],
                "clone_url": repo_data["http_url_to_repo"]
            }

        return False, error or "Failed to create repository", None

    @staticmethod
    def _add_file_to_github(
        token: str,
        repo: str,
        path: str,
        content: str,
        message: str
    ) -> Tuple[bool, Optional[requests.Response], Optional[str]]:
        """Add a file to GitHub repository."""
        username = settings.GITHUB_USERNAME or 'user'
        url = f"https://api.github.com/repos/{username}/{repo}/contents/{path}"
        headers = {
            "Authorization": f"token {token}",
            "Content-Type": "application/vnd.github.v3+json"
        }

        data = {
            "message": message[:72],  # GitHub limit
            "content": content.encode('utf-8').hex()
        }

        return APIClient.post_with_retry(
            url=url,
            json_data=data,
            headers=headers,
            timeout=15
        )


# ============================================================================
# Collaboration Space Service
# ============================================================================

class CollaborationSpaceService:
    """Service for creating collaboration spaces."""

    @staticmethod
    def create_space(project: Project) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        Create a collaboration space for a project.

        Returns:
            (success, message, space_info)
        """
        provider = settings.KICKOFF_COLLAB_PROVIDER

        if provider == "notion":
            return CollaborationSpaceService._create_notion_page(project)
        elif provider == "trello":
            return CollaborationSpaceService._create_trello_board(project)
        else:
            return True, "Collaboration space skipped (not configured)", None

    @staticmethod
    def _create_notion_page(project: Project) -> Tuple[bool, str, Optional[Dict]]:
        """Create Notion page for a project."""
        token = settings.NOTION_TOKEN
        database_id = settings.NOTION_PROJECTS_DB_ID

        if not token or not database_id:
            logger.warning("Notion credentials not configured")
            return False, "Notion credentials not configured", None

        # Sanitize inputs
        safe_title = sanitize_project_description(project.title[:50])
        safe_description = sanitize_project_description(
            project.preview_description or project.description or "No description",
            500
        )

        url = "https://api.notion.com/v1/pages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-10-28"
        }

        data = {
            "parent": {"database_id": database_id},
            "properties": {
                "Name": {
                    "title": [{"text": {"content": safe_title}}]
                },
                "Status": {
                    "select": {"name": "In Progress"}
                },
                "Project ID": {
                    "number": project.freelancer_id
                }
            },
            "children": [
                {
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {
                        "rich_text": [{"text": {"content": "Project Overview"}}]
                    }
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {"text": {"content": safe_description}}
                        ]
                    }
                },
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"text": {"content": "Requirements"}}]
                    }
                },
                {
                    "object": "block",
                    "type": "to_do",
                    "to_do": {
                        "rich_text": [{"text": {"content": "Clarify project scope with client"}}],
                        "checked": False
                    }
                },
                {
                    "object": "block",
                    "type": "to_do",
                    "to_do": {
                        "rich_text": [{"text": {"content": "Set up development environment"}}],
                        "checked": False
                    }
                },
                {
                    "object": "block",
                    "type": "to_do",
                    "to_do": {
                        "rich_text": [{"text": {"content": "Create initial project structure"}}],
                        "checked": False
                    }
                }
            ]
        }

        success, response, error = APIClient.post_with_retry(
            url=url,
            json_data=data,
            headers=headers,
            timeout=15
        )

        if success and response:
            page_data = response.json()
            page_url = page_data.get("url", "")
            return True, "Notion page created successfully", {
                "page_id": page_data["id"],
                "url": page_url
            }

        return False, error or "Failed to create Notion page", None

    @staticmethod
    def _create_trello_board(project: Project) -> Tuple[bool, str, Optional[Dict]]:
        """Create Trello board for a project."""
        token = settings.TRELLO_TOKEN
        api_key = settings.TRELLO_API_KEY

        if not token or not api_key:
            logger.warning("Trello credentials not configured")
            return False, "Trello credentials not configured", None

        # Sanitize board name
        board_name = sanitize_project_description(f"Project {project.freelancer_id}")

        url = "https://api.trello.com/1/boards"
        params = {
            "name": board_name,
            "defaultLists": "true",
            "key": api_key,
            "token": token
        }

        success, response, error = APIClient.post_with_retry(
            url=url,
            params=params,
            timeout=15
        )

        if success and response:
            board_data = response.json()
            return True, "Trello board created successfully", {
                "board_id": board_data["id"],
                "url": board_data["url"],
                "short_url": board_data["shortUrl"]
            }

        return False, error or "Failed to create Trello board", None


# ============================================================================
# Main Kick-off Service
# ============================================================================

class KickoffService:
    """Main service for project kick-off automation."""

    @staticmethod
    def _matches_keyword(text: str, keyword: str) -> bool:
        if " " in keyword:
            return keyword in text
        return re.search(rf"\b{re.escape(keyword)}\b", text) is not None

    @staticmethod
    def detect_template_type(project: Project) -> str:
        """Detect project template type from title and description."""
        text = (project.title + " " + (project.preview_description or "") + " " + (project.description or "")).lower()

        if any(
            KickoffService._matches_keyword(text, keyword)
            for keyword in ["scrape", "scraping", "crawl", "extract data", "web scraping"]
        ):
            return "web_scraping"
        elif any(
            KickoffService._matches_keyword(text, keyword)
            for keyword in ["api", "rest", "backend", "fastapi", "flask", "endpoint"]
        ):
            return "api_development"
        elif any(
            KickoffService._matches_keyword(text, keyword)
            for keyword in ["data analysis", "analytics", "dashboard", "visualization", "report"]
        ):
            return "data_analysis"
        elif any(
            KickoffService._matches_keyword(text, keyword)
            for keyword in ["automation", "automate", "bot", "workflow", "script", "monitor"]
        ):
            return "automation"
        else:
            return "custom"

    @staticmethod
    def trigger_kickoff(project_freelancer_id: int, bid_id: int) -> Dict:
        """
        Trigger project kick-off automation.

        Args:
            project_freelancer_id: Freelancer project ID
            bid_id: Winning bid ID

        Returns:
            Dict with kick-off status and information
        """
        with get_db_session() as db:
            # Get project and bid
            project = db.query(Project).filter_by(freelancer_id=project_freelancer_id).first()
            bid = db.query(Bid).filter_by(id=bid_id).first()

            if not project:
                logger.warning(f"Project not found: {project_freelancer_id}")
                return {"success": False, "error": "Project not found"}

            if not bid:
                logger.warning(f"Bid not found: {bid_id}")
                return {"success": False, "error": "Bid not found"}

            # Check if already kicked off
            existing = db.query(ProjectKickoff).filter_by(
                project_freelancer_id=project_freelancer_id
            ).first()

            if existing:
                logger.info(f"Project already kicked off: {project_freelancer_id}")
                return {
                    "success": False,
                    "error": "Project already kicked off",
                    "existing_kickoff": existing.to_dict()
                }

            # Detect template type
            template_type = KickoffService.detect_template_type(project)

            # Create kick-off record
            kickoff = ProjectKickoff(
                project_id=project.id,
                project_freelancer_id=project.freelancer_id,
                bid_id=bid.id,
                template_type=template_type
            )
            db.add(kickoff)
            db.flush()

            # Execute kick-off steps
            results = {}

            # Step 1: Create repository
            logger.info(f"Creating repository for project {project_freelancer_id}")
            repo_success, repo_message, repo_info = RepositoryService.create_repository(project, template_type)
            if repo_success:
                kickoff.repo_provider = settings.KICKOFF_REPO_PROVIDER
                kickoff.repo_name = repo_info["name"] if repo_info else None
                kickoff.repo_url = repo_info["url"] if repo_info else None
                kickoff.repo_status = "created"
                kickoff.repo_created_at = datetime.utcnow()
                results["repository"] = repo_info
            else:
                kickoff.repo_status = "failed"
                results["repository"] = {"error": repo_message}
                logger.error(f"Failed to create repository: {repo_message}")

            # Step 2: Create collaboration space
            logger.info(f"Creating collaboration space for project {project_freelancer_id}")
            collab_success, collab_message, collab_info = CollaborationSpaceService.create_space(project)
            if collab_success and collab_info:
                kickoff.collab_provider = settings.KICKOFF_COLLAB_PROVIDER
                kickoff.collab_space_url = collab_info.get("url")
                kickoff.collab_space_id = collab_info.get("page_id") or collab_info.get("board_id")
                kickoff.collab_status = "created"
                kickoff.collab_created_at = datetime.utcnow()
                results["collaboration"] = collab_info
            else:
                kickoff.collab_status = "failed"
                results["collaboration"] = {"error": collab_message}
                logger.error(f"Failed to create collaboration space: {collab_message}")

            # Complete kick-off
            kickoff.completed_at = datetime.utcnow()
            kickoff.kickoff_summary = json.dumps({
                "template_type": template_type,
                "steps_completed": [k for k, v in {
                    "repository": repo_success,
                    "collaboration": collab_success and collab_info is not None
                }.items() if v]
            })

            db.commit()
            logger.info(f"Kick-off completed for project {project_freelancer_id}")

            return {
                "success": True,
                "project_id": project.freelancer_id,
                "kickoff_id": kickoff.id,
                "template_type": template_type,
                "results": results
            }

    @staticmethod
    def get_kickoff_status(project_freelancer_id: int) -> Optional[Dict]:
        """Get kick-off status for a project."""
        with get_db_session() as db:
            kickoff = db.query(ProjectKickoff).filter_by(
                project_freelancer_id=project_freelancer_id
            ).first()

            if kickoff:
                return kickoff.to_dict()
            return None

    @staticmethod
    def list_recent_kickoffs(limit: int = 10) -> list:
        """List recent kick-off records."""
        if limit > 100:
            limit = 100

        with get_db_session() as db:
            kickoffs = db.query(ProjectKickoff).order_by(
                ProjectKickoff.triggered_at.desc()
            ).limit(limit).all()

            return [k.to_dict() for k in kickoffs]

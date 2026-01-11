import pytest
from services.bid_persona_controller import BidPersonaController

class TestBidPersonaController:

    def test_detect_project_type_frontend(self):
        title = "Need a React Developer"
        description = "We are looking for someone to build a UI using React and Tailwind."
        assert BidPersonaController.detect_project_type(title, description) == "frontend"

    def test_detect_project_type_backend(self):
        title = "Python API Backend"
        description = "Need a FastAPI developer to build a REST API with PostgreSQL."
        assert BidPersonaController.detect_project_type(title, description) == "backend"

    def test_detect_project_type_ai(self):
        title = "GPT-4 Integration"
        description = "We need an LLM expert to integrate OpenAI API into our app."
        assert BidPersonaController.detect_project_type(title, description) == "ai"

    def test_detect_project_type_mobile(self):
        title = "iOS App Development"
        description = "Looking for a Swift developer to build a native iOS app."
        assert BidPersonaController.detect_project_type(title, description) == "mobile"

    def test_detect_project_type_fullstack_explicit(self):
        title = "Fullstack Developer Needed"
        description = "MERN stack developer required for a web application."
        assert BidPersonaController.detect_project_type(title, description) == "fullstack"

    def test_detect_project_type_fullstack_implicit(self):
        title = "Web App Development"
        description = "Need a React frontend and a Node.js backend with MongoDB."
        assert BidPersonaController.detect_project_type(title, description) == "fullstack"

    def test_detect_project_type_general(self):
        title = "Simple Script"
        description = "Need a script to automate a task. No specific stack mentioned."
        assert BidPersonaController.detect_project_type(title, description) == "general"

    def test_detect_project_type_empty(self):
        assert BidPersonaController.detect_project_type("", "") == "general"

    def test_get_persona_hint_valid(self):
        hint = BidPersonaController.get_persona_hint("frontend")
        assert "UX/UI" in hint
        assert "React" in hint

    def test_get_persona_hint_unknown(self):
        hint = BidPersonaController.get_persona_hint("unknown_type")
        assert "Professional developer" in hint
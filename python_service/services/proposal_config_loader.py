"""
Proposal Configuration Loader Module.

Responsible for loading and validating the proposal generation configuration
from 'bid_prompts.yaml'. Ensures version compatibility and provides access methods
for personas, styles, structures, and validation rules.
"""

import yaml
import logging
import os
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


# Expected schema for configuration
REQUIRED_SCHEMA_KEYS = [
    "version",
]

OPTIONAL_SCHEMA_KEYS = [
    "personas",
    "styles",
    "structures",
    "validation_rules",
    "system_prompts",
]


class ProposalConfigLoader:
    """
    Configuration loader for proposal generation settings.

    Loads configuration from a YAML file, validates the version,
    and provides access to configuration sections.
    """

    _config: Dict[str, Any] = {}
    _loaded: bool = False
    # Default path, relative to project root or python_service root
    DEFAULT_CONFIG_PATH = "python_service/config/bid_prompts.yaml"

    @classmethod
    def load_config(cls, config_path: str = DEFAULT_CONFIG_PATH) -> bool:
        """
        Load configuration from the specified YAML file.

        Args:
            config_path: Path to the configuration file.

        Returns:
            bool: True if loaded successfully, False otherwise.
        """
        if not os.path.exists(config_path):
            logger.warning(f"Config file not found: {config_path}. Using empty config.")
            return False

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            if not config:
                logger.error("Config file is empty")
                return False

            if not cls._validate_version(config):
                logger.error(
                    f"Invalid config version. Expected 2.0, got {config.get('version')}"
                )
                return False

            cls._config = config
            cls._loaded = True
            logger.info(f"Loaded proposal config from {config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load config from {config_path}: {e}")
            return False

    @classmethod
    def _validate_version(cls, config: Dict[str, Any]) -> bool:
        """Validate that the configuration version is 2.0."""
        return str(config.get("version", "")) == "2.0"

    @classmethod
    def validate_schema(cls, config: Dict[str, Any]) -> bool:
        """
        Validate configuration against expected schema.

        P1: Configuration Schema Validation

        Args:
            config: Configuration dictionary to validate.

        Returns:
            bool: True if config matches expected schema, False otherwise.
        """
        # Check for required keys
        for key in REQUIRED_SCHEMA_KEYS:
            if key not in config:
                logger.error(f"Missing required config key: {key}")
                return False

        # Validate version
        version = config.get("version", "")
        if str(version) != "2.0":
            logger.error(f"Invalid config version: {version}. Expected 2.0")
            return False

        # Check for unknown keys (optional keys are allowed, but warn about completely unexpected ones)
        valid_keys = set(REQUIRED_SCHEMA_KEYS + OPTIONAL_SCHEMA_KEYS)
        for key in config.keys():
            if key not in valid_keys:
                logger.warning(f"Unknown config key: {key}")

        # Validate personas structure if present
        if "personas" in config:
            if not cls._validate_personas(config["personas"]):
                return False

        # Validate validation_rules structure if present
        if "validation_rules" in config:
            if not cls._validate_validation_rules(config["validation_rules"]):
                return False

        return True

    @classmethod
    def _validate_personas(cls, personas: Dict[str, Any]) -> bool:
        """Validate personas configuration structure."""
        if not isinstance(personas, dict):
            logger.error("Personas must be a dictionary")
            return False

        valid_persona_keys = {"name", "hints", "system_prompt", "examples"}
        for persona_name, persona_data in personas.items():
            if not isinstance(persona_data, dict):
                logger.error(f"Persona '{persona_name}' must be a dictionary")
                return False

            for key in persona_data.keys():
                if key not in valid_persona_keys:
                    logger.warning(f"Unknown key '{key}' in persona '{persona_name}'")

        return True

    @classmethod
    def _validate_validation_rules(cls, rules: Dict[str, Any]) -> bool:
        """Validate validation_rules configuration structure."""
        if not isinstance(rules, dict):
            logger.error("validation_rules must be a dictionary")
            return False

        valid_rule_keys = {
            "min_words",
            "max_words",
            "prohibited_phrases",
            "prohibited_headers",
            "required_elements",
            "keywords_threshold",
        }
        for key in rules.keys():
            if key not in valid_rule_keys:
                logger.warning(f"Unknown validation rule key: {key}")

        return True

    @classmethod
    def get_personas(cls) -> Dict[str, Any]:
        """Get the personas configuration section."""
        return cls._config.get("personas", {})

    @classmethod
    def get_styles(cls) -> Dict[str, Any]:
        """Get the styles configuration section."""
        return cls._config.get("styles", {})

    @classmethod
    def get_structures(cls) -> Dict[str, Any]:
        """Get the structures configuration section."""
        return cls._config.get("structures", {})

    @classmethod
    def get_validation_rules(cls) -> Dict[str, Any]:
        """Get the validation rules configuration section."""
        return cls._config.get("validation_rules", {})

    @classmethod
    def is_loaded(cls) -> bool:
        """Check if configuration has been loaded."""
        return cls._loaded

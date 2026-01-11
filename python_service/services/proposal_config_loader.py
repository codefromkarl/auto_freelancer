"""
Proposal Configuration Loader Module.

Responsible for loading and validating the proposal generation configuration
from 'bid_prompts.yaml'. Ensures version compatibility and provides access methods
for personas, styles, structures, and validation rules.
"""

import yaml
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


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
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                
            if not config:
                logger.error("Config file is empty")
                return False

            if not cls._validate_version(config):
                logger.error(f"Invalid config version. Expected 2.0, got {config.get('version')}")
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

"""
Unified Server Configuration for the Unified MCP for Unity system.
Merges configurations from MCP for Unity and Coplay MCP Server.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List
import logging

logger = logging.getLogger(__name__)

# 尝试加载 .env 文件
try:
    from dotenv import load_dotenv

    # 查找 .env 文件（从当前文件向上搜索）
    _env_path = Path(__file__).parent.parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path)
        logger.info("Loaded environment from %s", _env_path)
    else:
        # 也尝试 Server 目录下的 .env
        _env_path = Path(__file__).parent.parent / ".env"
        if _env_path.exists():
            load_dotenv(dotenv_path=_env_path)
            logger.info("Loaded environment from %s", _env_path)
except ImportError:
    logger.debug("python-dotenv is unavailable")
    pass


@dataclass
class UnifiedServerConfig:
    """Main configuration class for the Unified MCP Server."""

    # ═══ Network Settings ═══
    unity_host: str = "127.0.0.1"
    unity_port: int = 6400
    unity_port_explicit: bool = False
    unity_project_path: str | None = None
    http_host: str = "127.0.0.1"
    mcp_port: int = 6500
    rag_model: str = "gemma3:4b"
    rag_timeout: float = 60.0
    ollama_host: str = "http://localhost:11434"

    # ═══ Transport Settings ═══
    transport_mode: str = "stdio"  # stdio / http / sse

    # ═══ HTTP Remote Hosting ═══
    http_remote_hosted: bool = False
    api_key_validation_url: str | None = None
    api_key_login_url: str | None = None
    api_key_cache_ttl: float = 300.0

    # ═══ Connection Settings ═══
    connection_timeout: float = 30.0
    buffer_size: int = 16 * 1024 * 1024  # 16MB
    max_retries: int = 5
    retry_delay: float = 0.25
    reload_max_retries: int = 40
    reload_retry_ms: int = 250

    # ═══ STDIO Framing ═══
    require_framing: bool = True
    handshake_timeout: float = 1.0
    framed_receive_timeout: float = 2.0
    max_heartbeat_frames: int = 16
    heartbeat_timeout: float = 2.0

    # ═══ Security Settings ═══
    acl_enabled: bool = False
    acl_config_path: str = "acl.json"
    encryption_enabled: bool = False
    encryption_key_path: str | None = None
    audit_log_enabled: bool = False
    audit_log_path: str = "audit.log"

    # ═══ AI Generation Settings ═══
    ai_image_model: str = "gpt-image-1"
    ai_3d_provider: str = "meshy"
    ai_sfx_provider: str = "elevenlabs"
    ai_generation_timeout: float = 600.0
    ai_output_directory: str = str(Path(__file__).resolve().parents[2] / "data" / "generated")

    # ═══ Extension Module Toggles ═══
    enabled_tool_groups: List[str] = field(
        default_factory=lambda: ["all"]
    )

    # ═══ Logging Settings ═══
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # ═══ Port Discovery ═══
    port_registry_ttl: float = 5.0

    # ─── Derived helpers ───

    def is_tool_group_enabled(self, group_name: str) -> bool:
        """Check if a tool group is enabled based on config."""
        if "all" in self.enabled_tool_groups:
            return True
        return group_name in self.enabled_tool_groups

    def load_from_env(self) -> None:
        """Load configuration overrides from environment variables."""
        import os

        # Transport
        if v := os.environ.get("UNITY_MCP_TRANSPORT"):
            self.transport_mode = v
        if v := os.environ.get("UNITY_MCP_HTTP_HOST"):
            self.http_host = v
        if v := os.environ.get("UNITY_MCP_UNITY_HOST"):
            self.unity_host = v
        if v := os.environ.get("UNITY_MCP_UNITY_PORT"):
            try:
                self.unity_port = int(v)
                self.unity_port_explicit = True
            except ValueError:
                pass
        if v := os.environ.get("UNITY_MCP_PROJECT_PATH"):
            self.unity_project_path = v
        if v := os.environ.get("UNITY_MCP_RAG_MODEL"):
            self.rag_model = v
        if v := os.environ.get("UNITY_MCP_RAG_TIMEOUT"):
            try:
                self.rag_timeout = float(v)
            except ValueError:
                pass
        if v := os.environ.get("OLLAMA_HOST"):
            self.ollama_host = v.rstrip("/")
        if v := os.environ.get("UNITY_MCP_HTTP_PORT"):
            try:
                self.mcp_port = int(v)
            except ValueError:
                pass
        if v := os.environ.get("UNITY_MCP_HTTP_REMOTE_HOSTED", "").lower():
            self.http_remote_hosted = v in ("true", "1", "yes", "on")

        # API Key
        if v := os.environ.get("UNITY_MCP_API_KEY_VALIDATION_URL"):
            self.api_key_validation_url = v
        if v := os.environ.get("UNITY_MCP_API_KEY_LOGIN_URL"):
            self.api_key_login_url = v
        if v := os.environ.get("UNITY_MCP_API_KEY_CACHE_TTL"):
            try:
                self.api_key_cache_ttl = float(v)
            except ValueError:
                pass

        # Security
        if v := os.environ.get("UNITY_MCP_ACL_ENABLED", "").lower():
            self.acl_enabled = v in ("true", "1", "yes", "on")
        if v := os.environ.get("UNITY_MCP_ACL_CONFIG_PATH"):
            self.acl_config_path = v
        if v := os.environ.get("UNITY_MCP_ENCRYPTION_ENABLED", "").lower():
            self.encryption_enabled = v in ("true", "1", "yes", "on")
        if v := os.environ.get("UNITY_MCP_ENCRYPTION_KEY_PATH"):
            self.encryption_key_path = v
        if v := os.environ.get("UNITY_MCP_AUDIT_LOG_ENABLED", "").lower():
            self.audit_log_enabled = v in ("true", "1", "yes", "on")
        if v := os.environ.get("UNITY_MCP_AUDIT_LOG_PATH"):
            self.audit_log_path = v

        # AI Generation
        if v := os.environ.get("UNITY_MCP_AI_IMAGE_MODEL"):
            self.ai_image_model = v
        if v := os.environ.get("UNITY_MCP_AI_3D_PROVIDER"):
            self.ai_3d_provider = v
        if v := os.environ.get("UNITY_MCP_AI_SFX_PROVIDER"):
            self.ai_sfx_provider = v

        if v := os.environ.get("UNITY_MCP_AI_GENERATION_TIMEOUT"):
            try:
                self.ai_generation_timeout = float(v)
            except ValueError:
                pass
        if v := os.environ.get("UNITY_MCP_GENERATED_DIR"):
            self.ai_output_directory = v

        # Tool groups
        if v := os.environ.get("UNITY_MCP_ENABLED_GROUPS"):
            self.enabled_tool_groups = [g.strip() for g in v.split(",")]

        # Logging
        if v := os.environ.get("UNITY_MCP_LOG_LEVEL"):
            self.log_level = v


# Create a global config instance
config = UnifiedServerConfig()
config.load_from_env()

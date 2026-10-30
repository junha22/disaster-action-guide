"""Backend package. backend/.env is loaded first so import-time settings (KIROTHON_DB_PATH) see it."""
from .env import load_env_file

load_env_file()

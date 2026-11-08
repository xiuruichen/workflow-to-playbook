"""Download llama-server and the Qwen3-VL 4B files into the llama folder WITHOUT changing
local_model.json (the configured model is left alone). Checksums are the publisher's / pinned in the code."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from playbook import llama_runtime as lr
from playbook.config import get_settings

print(lr.install(get_settings(), "qwen3-vl-4b"))
print("done")

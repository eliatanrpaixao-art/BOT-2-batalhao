"""Silver City RP — Bot exclusivo do Discord do 2º Batalhão."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bot_core import iniciar

if __name__ == "__main__":
    iniciar(str(Path(__file__).with_name(".env")))

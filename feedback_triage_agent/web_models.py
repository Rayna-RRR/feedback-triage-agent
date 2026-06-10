from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass
class DownloadFile:
    name: str
    label: str
    exists: bool


@dataclass
class WebRunData:
    run_id: str
    output_dir: Path
    metrics: Dict[str, object]
    category_distribution: List[Dict[str, object]]
    priority_distribution: List[Dict[str, object]]
    review_items: List[Dict[str, object]]
    issue_cards: List[Dict[str, object]]
    run_steps: List[Dict[str, object]]
    downloads: List[DownloadFile]


from tests.conftest import REPO


def test_trs_00_06_library_dir_is_not_gitignored():
    """TRS-00-06: the set is version-controlled and serves as the pytest corpus."""
    gi = (REPO / ".gitignore").read_text().splitlines()
    assert not any(line.strip().startswith("data/library") for line in gi)
    assert any(line.strip() == "data/raw/" for line in gi), "raw dataset must stay out of git"
    assert any(line.strip() == "data/synthetic/" for line in gi)

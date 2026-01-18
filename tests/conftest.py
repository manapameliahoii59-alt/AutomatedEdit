import os
import sys
import pytest

# Add the project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

@pytest.fixture
def app_instance(qapp):
    """
    Fixture to get the QApplication instance.
    'qapp' is provided by pytest-qt.
    """
    return qapp

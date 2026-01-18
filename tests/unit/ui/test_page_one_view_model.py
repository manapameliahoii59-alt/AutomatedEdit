import pytest
from app.ui.views.page_one.view_model import PageOneViewModel

class TestPageOneViewModel:
    def test_init(self, qapp):
        vm = PageOneViewModel()
        assert vm is not None
        # Add more assertions

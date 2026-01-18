import pytest
from app.ui.views.page_one.view import PageOne
from app.ui.views.page_two.view import PageTwo

class TestPages:
    def test_page_one_init(self, qapp):
        page = PageOne(None)
        assert page.objectName() == "page_one"
        
    def test_page_two_init(self, qapp):
        page = PageTwo(None)
        assert page.objectName() == "page_two"

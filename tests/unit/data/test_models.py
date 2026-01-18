from app.data.models.user import User

class TestUser:
    def test_init(self):
        u = User("name", "pass", "tok")
        assert u.username == "name"
        assert u.password == "pass"
        assert u.token == "tok"

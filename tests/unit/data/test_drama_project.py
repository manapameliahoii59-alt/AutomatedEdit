from app.data.models.drama_project import DramaProject, DramaStatus


class TestDramaProject:
    def test_status_label(self):
        project = DramaProject("1", "测试剧", 5, status=DramaStatus.PENDING)
        assert project.status_label == "待处理"

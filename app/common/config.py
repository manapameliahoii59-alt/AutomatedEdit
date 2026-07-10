# coding:utf-8
import datetime

from qfluentwidgets import (qconfig, QConfig, ConfigItem, BoolValidator, ColorConfigItem)


class MyQConfig(QConfig):
    # 自定义fluent默认主题颜色
    themeColor = ColorConfigItem("QFluentWidgets", "ThemeColor", '#70d5f3')


class Config(MyQConfig):
    user = ConfigItem("User", "user", '')
    password = ConfigItem("User", "password", '')

    """ Config of application """

    auto_login = ConfigItem("MainWindow", "auto_login", False, BoolValidator())
    save_password = ConfigItem("MainWindow", "save_password", True, BoolValidator())

    dashscope_api_key = ConfigItem("LLM", "dashscope_api_key", "")

    deepseek_api_keys = ConfigItem("Tools", "deepseek_api_keys", "")
    ffmpeg_path = ConfigItem("Tools", "ffmpeg_path", "")
    ffprobe_path = ConfigItem("Tools", "ffprobe_path", "")
    clip_export_dir = ConfigItem("Tools", "clip_export_dir", "")
    clip_export_name_tag = ConfigItem("Tools", "clip_export_name_tag", "")
    video_download_dir = ConfigItem("Tools", "video_download_dir", "")
    video_download_auto_unzip = ConfigItem(
        "Tools", "video_download_auto_unzip", True, BoolValidator()
    )
    video_download_auto_transcribe = ConfigItem(
        "Tools", "video_download_auto_transcribe", True, BoolValidator()
    )
    video_download_auto_import_clip = ConfigItem(
        "Tools", "video_download_auto_import_clip", True, BoolValidator()
    )
    video_download_auto_start_after_add = ConfigItem(
        "Tools", "video_download_auto_start_after_add", True, BoolValidator()
    )

    changdu_email = ConfigItem("Tools", "changdu_email", "")
    changdu_password = ConfigItem("Tools", "changdu_password", "")

    api_base_url = ConfigItem("API", "base_url", "")
    access_token = ConfigItem("API", "access_token", "")
    plan_decrypt_key = ConfigItem("API", "plan_decrypt_key", "")

    update_dismissed_version = ConfigItem("Update", "dismissed_version", "")


# 客户端 config.json 未配置 base_url 时使用的默认服务端地址
DEFAULT_API_BASE_URL = "http://129.204.86.63:7172"


YEAR = datetime.datetime.now().year
AUTHOR = "Cheukfung"
VERSION = '0.0.1'
FEEDBACK_URL = "https://github.com/Cheukfung"

cfg = Config()
# qconfig.themeColor = ColorConfigItem("QFluentWidgets", "ThemeColor", '#70d5f3')
qconfig.load('config.json', cfg)

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
    # 自动化剪辑「导入剧目」对话框上次打开的目录
    clip_last_import_dir = ConfigItem("Tools", "clip_last_import_dir", "")
    # 画面叠字（剧名 / 提示）JSON —— 旧单套，仍作兼容读写
    overlay_title_json = ConfigItem("Tools", "overlay_title_json", "")
    overlay_disclaimer_json = ConfigItem("Tools", "overlay_disclaimer_json", "")
    # 画面文字组库：{selected_id, groups:[{id,name,title,disclaimer}]}
    overlay_text_library_json = ConfigItem("Tools", "overlay_text_library_json", "")
    # 渲染编码档位（默认：NVENC p5 / x264 superfast）
    encode_nvenc_preset = ConfigItem("Tools", "encode_nvenc_preset", "p5")
    encode_x264_preset = ConfigItem("Tools", "encode_x264_preset", "superfast")
    # 策划：短片/长片/混合模式；长片条数与最长时长（最短固定 150s）
    plan_mode = ConfigItem("Tools", "plan_mode", "long")
    plan_clip_count = ConfigItem("Tools", "plan_clip_count", 15)
    plan_max_duration_sec = ConfigItem("Tools", "plan_max_duration_sec", 720)
    # 短片：条数 5~15；最长时长秒（最短固定 120s，最长 120~360）
    plan_short_clip_count = ConfigItem("Tools", "plan_short_clip_count", 15)
    plan_short_max_duration_sec = ConfigItem(
        "Tools", "plan_short_max_duration_sec", 300
    )
    # 混合：条数 5~20；最长时长秒（最短固定 120s，最长可选 360~900）；分 A/B
    plan_mixed_clip_count = ConfigItem("Tools", "plan_mixed_clip_count", 15)
    plan_mixed_max_duration_sec = ConfigItem(
        "Tools", "plan_mixed_max_duration_sec", 720
    )
    # 成片全局倍速（默认 1.15）
    plan_global_speed = ConfigItem("Tools", "plan_global_speed", 1.15)
    video_download_dir = ConfigItem("Tools", "video_download_dir", "")
    video_download_auto_unzip = ConfigItem(
        "Tools", "video_download_auto_unzip", True, BoolValidator()
    )
    video_download_auto_transcribe = ConfigItem(
        "Tools", "video_download_auto_transcribe", True, BoolValidator()
    )
    video_download_auto_plan = ConfigItem(
        "Tools", "video_download_auto_plan", True, BoolValidator()
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
AUTHOR = "dragon"
AUTHOR_EMAIL = "857134647@qq.com"
VERSION = '0.0.3'
APP_NAME = "剪辑助手"
FEEDBACK_URL = f"mailto:{AUTHOR_EMAIL}"

cfg = Config()
# qconfig.themeColor = ColorConfigItem("QFluentWidgets", "ThemeColor", '#70d5f3')
qconfig.load('config.json', cfg)

<h1 align="center">
  PySide6 Fluent Design模板
</h1>

<div align="center">

**中文** | [English](./README_EN.md)

[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue?color=#4ec820)]()
[![Download](https://img.shields.io/badge/PySide6-6.7.0-green?color=#4ec820)]()
[![GPLv3](https://img.shields.io/badge/License-GPLv3-blue?color=#4ec820)](LICENSE)
[![Platform Win32 | Linux | macOS](https://img.shields.io/badge/Platform-Win32%20|%20Linux%20|%20macOS-blue?color=#4ec820)]()

</div>

一个基于 [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/) 的现代化UI模板，适配Qt
Designer使用，专为PySide6开发者打造的快速开发解决方案。

## ✨ 主要特性

- 🎨 内置Fluent Design风格组件库
- 🏗️ **MVVM 架构设计**，逻辑与界面彻底分离
- ⚡ **懒加载机制**，优化应用启动速度
- � **依赖注入容器**，提升代码可测试性
- �📝 Qt Designer友好，支持可视化设计
- 🔄 预置登录界面与主界面切换逻辑
- ⚡ QRunnable异步任务封装
- 📦 开箱即用的项目模板结构
- 🌙 支持亮/暗主题切换
- 🧪 全面的自动化测试模块
- 📌 内置配置管理（密码保存）和日志模块
- uv run python scripts/pack_resources.py
- uv run python .\entry.py

## ⚠️ 注意事项

> **注意**：本项目作者为编程爱好者，非专业开发者，且项目代码由AI生成（包括此readme），建议仅作为学习参考使用，生产环境使用前请充分测试。

## 🖼 界面预览

| 登录界面                                                                                                                          | 主界面（亮色）                                                                                                                             | 主界面（暗色）                                                                                                                           |
|-------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| <img src="https://github.com/Cheukfung/pyqt-fluent-widgets-template/blob/pyside6/screen_shot/login.png?raw=true" width="300"> | <img src="https://github.com/Cheukfung/pyqt-fluent-widgets-template/blob/pyside6/screen_shot/main_window.png?raw=true" width="300"> | <img src="https://github.com/Cheukfung/pyqt-fluent-widgets-template/blob/pyside6/screen_shot/main_dark.png?raw=true" width="300"> |

## 🚀 快速开始

### 环境要求

1. Python 3.8+
2. PySide6

### 快速上手

```bash
# 克隆仓库
git clone https://github.com/Cheukfung/pyqt-fluent-widgets-template.git
cd pyqt-fluent-widgets-template
# 安装依赖
uv sync
# 打包资源
uv run pack_resources.py
# 运行
uv run entry.py
```

### 开发流程

#### UI设计

1. 使用Qt Designer打开 `app/ui/generated/` 目录下的.ui文件（或新建）
2. 添加/修改需要的控件
3. 保存修改后运行资源打包脚本：

```bash
python pack_resources.py
```

#### 业务逻辑开发 (MVVM)

本项目采用 MVVM 架构，开发新页面推荐遵循以下流程：

1. **定义 View (视图)**:
   - 在 `app/ui/views/` 下创建新目录（如 `my_page/`）。
   - 创建 `view.py`，继承自 `QWidget` 和 UI 类。
   - 仅负责 UI 初始化和信号绑定，**不包含业务逻辑**。

2. **定义 ViewModel (视图模型)**:
   - 在同级目录创建 `view_model.py`，继承自 `app.core.view_model.ViewModel`。
   - 定义 `Signal` 用于通知 View 更新。
   - 实现业务方法（如网络请求、数据处理）。

3. **注册导航**:
   - 在 `app/ui/views/main_window/view.py` 中使用 `LazyViewProxy` 注册新页面。
   - 这样可以确保页面只有在被点击时才初始化，提升启动性能。

## 🧪 自动化测试

本项目包含完善的测试模块，涵盖单元测试、集成测试、性能测试和UI测试。

### 运行测试

```bash
# 运行所有测试
uv run pytest

# 生成覆盖率报告
uv run pytest --cov=app --cov-report=html
```

测试代码位于 `tests/` 目录下，结构如下：
- `unit/`: 单元测试
- `integration/`: 集成测试
- `performance/`: 性能测试
- `security/`: 安全测试

## 📦 项目打包

### 使用Nuitka打包

```bash
# 安装打包工具
# (已包含在依赖中)

# 执行打包脚本
uv run python scripts/build.py
```

### 生成安装包

推荐使用 [Inno Setup](https://jrsoftware.org/isinfo.php) 创建Windows安装程序
(脚本位于 `scripts/pack_installer.iss`)

## 🛠 项目结构

```
├── app/                    # 应用核心代码
│   ├── common/             # 通用工具库 (Config, Logger等)
│   ├── core/               # 核心架构 (Container, Navigation等)
│   ├── data/               # 数据层 (API, Models, Services)
│   └── ui/                 # 界面层
│       ├── components/     # 自定义组件
│       ├── generated/      # UI文件编译生成的Python代码
│       └── views/          # 页面模块 (MVVM)
├── resource/               # 资源文件目录 (i18n, images, qss)
├── scripts/                # 构建与工具脚本
│   ├── build.py            # 打包脚本
│   ├── pack_installer.iss  # Inno Setup安装包配置
│   └── pack_resources.py   # 资源编译脚本
├── entry.py                # 程序入口
├── pyproject.toml          # 项目配置与依赖
└── README.md               # 项目说明
```

## 💡 最佳实践

- 使用 **MVVM 架构** 分离UI与业务逻辑
- 通过 **LazyViewProxy** 实现页面的懒加载
- 使用 **依赖注入** 管理服务实例
- 通过 **QRunnable** 实现耗时操作异步化
- 利用 **config.json** 管理用户配置
- 使用预置的 **Logger** 模块进行日志记录

## 🙏 特别致谢


- **[PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)**  
  🎨 zhiyiYo大佬的高质量的Fluent Design组件库

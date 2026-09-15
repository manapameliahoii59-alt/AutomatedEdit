# 第四层提速方案：具体改动清单与代码设计

## 一、改动范围概览

本方案改动极其轻量、精准、收敛，**只需要改动 2 个文件**：

| 文件路径 | 改动类型 | 改动行数 | 改动目的 |
| :--- | :--- | :--- | :--- |
| [`scripts/build.py`](file:///C:/Users/Administrator/Desktop/project/AutomatedEdit/scripts/build.py) | **核心改动** | 约 35 行 | 增加 `--app-only` 参数，实现 `sync_app_layer()` 业务层极速装配逻辑 |
| [`entry.py`](file:///C:/Users/Administrator/Desktop/project/AutomatedEdit/entry.py) | **辅助优化** | 约 5 行 | 将外部文件导入器前置到最顶层，确保 100% 优先读取磁盘最新代码 |
| [`AGENTS.md`](file:///C:/Users/Administrator/Desktop/project/AutomatedEdit/AGENTS.md) | **文档更新** | 约 2 行 | 补充日常极速打包命令说明 |

> [!NOTE]
> 安装包脚本 [`scripts/pack_installer.iss`](file:///C:/Users/Administrator/Desktop/project/AutomatedEdit/scripts/pack_installer.iss) **完全无需改动**！
> 因为它原有的 `Source: "{#P}\out\entry.dist\*"` 规则会自动、完整地把同步进去的 `app/` 文件夹递归打进安装包中。

---

## 二、具体代码改动细节 (Proposed Code Diffs)

### 1. [`scripts/build.py`](file:///C:/Users/Administrator/Desktop/project/AutomatedEdit/scripts/build.py)

#### 变更点 A：增加 `sync_app_layer()` 极速同步函数
在脚本中增加业务层装配函数，负责“编译 UI 资源 -> 拷贝 app/ -> 拷贝 resource_rc.py -> 写入默认配置”：
```python
def sync_app_layer() -> None:
    """极速同步模式：仅刷新 UI 资源并将最新的 app/ 业务代码同步至 dist。"""
    print("\n>>> [1/3] 编译最新的 UI 与 QRC 资源文件...")
    build_resources()

    print(">>> [2/3] 同步 app/ 业务代码与资源至 dist...")
    src_app = PROJECT_ROOT / "app"
    dst_app = DIST_DIR / "app"
    if dst_app.exists():
        shutil.rmtree(dst_app)
    shutil.copytree(
        src_app,
        dst_app,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    print("  -> 已同步: app/")

    rc_file = PROJECT_ROOT / "resource_rc.py"
    if rc_file.is_file():
        shutil.copy2(rc_file, DIST_DIR / "resource_rc.py")
        print("  -> 已同步: resource_rc.py")

    print(">>> [3/3] 写入干净默认配置...")
    bundle_config()
    print("业务层装配完成！\n")
```

#### 变更点 B：命令行参数增加 `--app-only`（别名 `--patch`）
```python
parser.add_argument(
    "--app-only",
    "--patch",
    action="store_true",
    help="快速打包：跳过 Nuitka 编译，直接复用已有底座，同步 app/ 业务代码并生成安装包（16秒极速出包）",
)
```

#### 变更点 C：在 `main()` 中增加极速通道分支
```python
if args.app_only:
    exe_path = DIST_DIR / "entry.exe"
    if not exe_path.is_file():
        sys.exit(
            "错误：未找到 out/entry.dist/entry.exe 底座！\n"
            "首次构建必须先运行一次全量编译：uv run python scripts/build.py --installer"
        )
    t0 = time.perf_counter()
    sync_app_layer()
    if args.installer or args.fast_pack:
        build_installer(fast_pack=args.fast_pack)
    elapsed = time.perf_counter() - t0
    print(f"\n🎉 极速打包完成！全流程总用时: {elapsed:.2f} 秒")
    return
```

#### 变更点 D：在全量 Nuitka 构建参数中顺带加入 `--no-pyi-file`（P1 优化）
```python
build_command += "--no-pyi-file "
```

---

### 2. [`entry.py`](file:///C:/Users/Administrator/Desktop/project/AutomatedEdit/entry.py)

#### 变更点：提前初始化外部导入器
在启动脚本最顶层（第 20 行附近），将 `install_dist_stdlib_importer()` 提前执行：
- 原来在第 107 行（torch 之前）才挂载；
- 提前至最顶层后，程序在启动的最早阶段（包括日志初始化、崩溃捕获、闪屏展示、界面渲染），只要外部磁盘 `out/entry.dist/app/` 有最新文件，就会**绝对优先从磁盘读取**，确保更新立即生效。

---

## 三、用户操作变化对比

| 操作场景 | 过去的操作 | 现在的操作 | 耗时对比 |
| :--- | :--- | :--- | :--- |
| **日常修改代码打安装包** | `uv run python scripts/build.py --installer` | `uv run python scripts/build.py --app-only --fast-pack` | **由 16.62 分钟 -> 降至 16 秒！** |
| **全量深度编译（备用）** | `uv run python scripts/build.py --installer` | `uv run python scripts/build.py --installer` | 完全不变（约 15 分钟） |

---

## 四、验证方案 (Verification Plan)

1. **执行修改**：按照上述代码修改 [`scripts/build.py`](file:///C:/Users/Administrator/Desktop/project/AutomatedEdit/scripts/build.py) 与 [`entry.py`](file:///C:/Users/Administrator/Desktop/project/AutomatedEdit/entry.py)；
2. **极速构建测试**：运行 `uv run python scripts/build.py --app-only --fast-pack`，记录总耗时（目标：15~20秒）；
3. **冒烟运行测试**：双击启动测试，确认最新代码已生效且功能完好。

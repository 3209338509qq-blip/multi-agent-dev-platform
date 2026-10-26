"""校验 PM 任务计划；当前计划使用唯一角色名引用依赖。"""
from graphlib import CycleError, TopologicalSorter

REQUIRED_DEPENDENCIES = {
    "architect": set(),
    "backend": {"architect"},
    "frontend": {"architect"},
    "test": {"backend", "frontend"},
    "review": {"test"},
    "git": {"review"},
}


def validate_task_plan(tasks: list[dict]) -> None:
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("PM 未生成有效任务列表")
    graph: dict[str, set[str]] = {"pm": set()}
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("任务必须是 JSON 对象")
        role = task.get("role")
        if not isinstance(role, str) or role not in {*REQUIRED_DEPENDENCIES, "debug"}:
            raise ValueError(f"未知任务角色：{role}")
        if role in graph:
            raise ValueError(f"任务角色重复：{role}；当前每个角色只支持一个任务")
        deps = task.get("depends_on", [])
        if not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps):
            raise ValueError(f"{role} 的 depends_on 必须是角色名列表")
        graph[role] = set(deps)
    missing = REQUIRED_DEPENDENCIES.keys() - graph.keys()
    if missing:
        raise ValueError(f"计划缺少必需角色：{', '.join(sorted(missing))}")
    if tasks[0]["role"] != "architect":
        raise ValueError("第一个任务必须是 architect")
    for role, deps in graph.items():
        unknown = deps - graph.keys()
        if unknown:
            raise ValueError(f"{role} 依赖不存在的角色：{', '.join(sorted(unknown))}")
    try:
        tuple(TopologicalSorter(graph).static_order())
    except CycleError as exc:
        raise ValueError("任务依赖存在环") from exc
    for role, required in REQUIRED_DEPENDENCIES.items():
        if not required <= graph[role]:
            raise ValueError(f"{role} 必须依赖：{', '.join(sorted(required))}")

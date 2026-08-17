"""事件类型定义（禁止使用裸字符串）。"""

AGENT_STARTED = "agent_started"
AGENT_COMPLETED = "agent_completed"
AGENT_FAILED = "agent_failed"

TASK_CREATED = "task_created"
TASK_STARTED = "task_started"
TASK_COMPLETED = "task_completed"
TASK_FAILED = "task_failed"
TASK_RETRYING = "task_retrying"
TASK_BLOCKED = "task_blocked"
TASK_CANCELLED = "task_cancelled"

FILE_CREATED = "file_created"
FILE_MODIFIED = "file_modified"

TEST_STARTED = "test_started"
TEST_PASSED = "test_passed"
TEST_FAILED = "test_failed"

DEBUG_STARTED = "debug_started"
REVIEW_STARTED = "review_started"
REVIEW_FAILED = "review_failed"
REVIEW_PASSED = "review_passed"

COMMIT_CREATED = "commit_created"

PROJECT_CREATED = "project_created"
PROJECT_STARTED = "project_started"
PROJECT_COMPLETED = "project_completed"
PROJECT_FAILED = "project_failed"
PROJECT_CANCELLED = "project_cancelled"

BUDGET_EXCEEDED = "budget_exceeded"

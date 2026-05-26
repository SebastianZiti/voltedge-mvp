from collections import defaultdict
from pathlib import Path
from threading import Lock


HTTP_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
DB_DURATION_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)

_lock = Lock()
_http_requests = defaultdict(int)
_http_duration_sum = defaultdict(float)
_http_duration_count = defaultdict(int)
_http_duration_buckets = defaultdict(lambda: defaultdict(int))
_db_queries = defaultdict(int)
_db_errors = defaultdict(int)
_db_duration_sum = defaultdict(float)
_db_duration_count = defaultdict(int)
_db_duration_buckets = defaultdict(lambda: defaultdict(int))


def reset_metrics():
    with _lock:
        _http_requests.clear()
        _http_duration_sum.clear()
        _http_duration_count.clear()
        _http_duration_buckets.clear()
        _db_queries.clear()
        _db_errors.clear()
        _db_duration_sum.clear()
        _db_duration_count.clear()
        _db_duration_buckets.clear()


def record_http_request(method, path, status, duration_seconds):
    labels = (method, path, str(status))
    duration = max(float(duration_seconds), 0.0)
    with _lock:
        _http_requests[labels] += 1
        _http_duration_sum[labels] += duration
        _http_duration_count[labels] += 1
        for bucket in HTTP_DURATION_BUCKETS:
            if duration <= bucket:
                _http_duration_buckets[labels][bucket] += 1
        _http_duration_buckets[labels][float("inf")] += 1


def record_db_query(operation, duration_seconds, error=False):
    op = operation.lower()
    duration = max(float(duration_seconds), 0.0)
    with _lock:
        _db_queries[op] += 1
        if error:
            _db_errors[op] += 1
        _db_duration_sum[op] += duration
        _db_duration_count[op] += 1
        for bucket in DB_DURATION_BUCKETS:
            if duration <= bucket:
                _db_duration_buckets[op][bucket] += 1
        _db_duration_buckets[op][float("inf")] += 1


def render_prometheus_metrics(db_path, db_ready):
    db_file = Path(db_path)
    db_size = db_file.stat().st_size if db_file.exists() else 0

    with _lock:
        http_requests = dict(_http_requests)
        http_duration_sum = dict(_http_duration_sum)
        http_duration_count = dict(_http_duration_count)
        http_duration_buckets = {labels: dict(buckets) for labels, buckets in _http_duration_buckets.items()}
        db_queries = dict(_db_queries)
        db_errors = dict(_db_errors)
        db_duration_sum = dict(_db_duration_sum)
        db_duration_count = dict(_db_duration_count)
        db_duration_buckets = {operation: dict(buckets) for operation, buckets in _db_duration_buckets.items()}

    lines = [
        "# HELP voltedge_app_info Static application info.",
        "# TYPE voltedge_app_info gauge",
        'voltedge_app_info{service="voltedge-mvp"} 1.0',
        "# HELP voltedge_db_ready Database readiness state. 1 means ready, 0 means not ready.",
        "# TYPE voltedge_db_ready gauge",
        _metric_line("voltedge_db_ready", 1 if db_ready else 0),
        "# HELP voltedge_db_file_size_bytes SQLite database file size in bytes.",
        "# TYPE voltedge_db_file_size_bytes gauge",
        _metric_line("voltedge_db_file_size_bytes", db_size),
        "# HELP flask_http_request_total Total HTTP requests by method, path and status.",
        "# TYPE flask_http_request_total counter",
    ]

    for labels, value in sorted(http_requests.items()):
        method, path, status = labels
        lines.append(
            _metric_line(
                "flask_http_request_total",
                value,
                {"method": method, "path": path, "status": status},
            )
        )

    lines.extend(
        [
            "# HELP flask_http_request_duration_seconds HTTP request latency in seconds.",
            "# TYPE flask_http_request_duration_seconds histogram",
        ]
    )
    for labels in sorted(http_duration_count):
        method, path, status = labels
        base_labels = {"method": method, "path": path, "status": status}
        for bucket in (*HTTP_DURATION_BUCKETS, float("inf")):
            lines.append(
                _metric_line(
                    "flask_http_request_duration_seconds_bucket",
                    http_duration_buckets.get(labels, {}).get(bucket, 0),
                    {**base_labels, "le": _bucket_label(bucket)},
                )
            )
        lines.append(_metric_line("flask_http_request_duration_seconds_sum", http_duration_sum[labels], base_labels))
        lines.append(_metric_line("flask_http_request_duration_seconds_count", http_duration_count[labels], base_labels))

    lines.extend(
        [
            "# HELP voltedge_db_queries_total Total database operations by operation type.",
            "# TYPE voltedge_db_queries_total counter",
        ]
    )
    for operation, value in sorted(db_queries.items()):
        lines.append(_metric_line("voltedge_db_queries_total", value, {"operation": operation}))

    lines.extend(
        [
            "# HELP voltedge_db_errors_total Total database operation errors by operation type.",
            "# TYPE voltedge_db_errors_total counter",
        ]
    )
    for operation in sorted(set(db_queries) | set(db_errors)):
        lines.append(_metric_line("voltedge_db_errors_total", db_errors.get(operation, 0), {"operation": operation}))

    lines.extend(
        [
            "# HELP voltedge_db_query_duration_seconds Database operation duration in seconds.",
            "# TYPE voltedge_db_query_duration_seconds histogram",
        ]
    )
    for operation in sorted(db_duration_count):
        labels = {"operation": operation}
        for bucket in (*DB_DURATION_BUCKETS, float("inf")):
            lines.append(
                _metric_line(
                    "voltedge_db_query_duration_seconds_bucket",
                    db_duration_buckets.get(operation, {}).get(bucket, 0),
                    {**labels, "le": _bucket_label(bucket)},
                )
            )
        lines.append(_metric_line("voltedge_db_query_duration_seconds_sum", db_duration_sum[operation], labels))
        lines.append(_metric_line("voltedge_db_query_duration_seconds_count", db_duration_count[operation], labels))

    return "\n".join(lines) + "\n"


def _metric_line(name, value, labels=None):
    label_text = ""
    if labels:
        label_text = "{" + ",".join(f'{key}="{_escape_label_value(str(val))}"' for key, val in labels.items()) + "}"
    return f"{name}{label_text} {float(value)}"


def _bucket_label(bucket):
    return "+Inf" if bucket == float("inf") else str(bucket)


def _escape_label_value(value):
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')

#!/usr/bin/env python3
"""
OpenClaw JSONL → Pandas DataFrame loader.

Parses cron run logs and session transcripts into analysis-ready DataFrames.
Designed for use in Jupyter notebooks or standalone scripts.

Usage:
    from openclaw_loader import load_cron_runs, load_sessions, load_session_transcript

    # Load all cron job run logs
    df = load_cron_runs()

    # Load session cost summaries
    sessions = load_sessions()

    # Load a single session transcript
    transcript = load_session_transcript("session-id-here")
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

DEFAULT_OPENCLAW_DIR = Path.home() / ".openclaw"


def _resolve_openclaw_dir(base: Optional[str] = None) -> Path:
    if base:
        return Path(base)
    for env_name in ("OPENCLAW_STATE_DIR", "CLAWDBOT_STATE_DIR", "OPENCLAW_DIR"):
        env = os.environ.get(env_name)
        if env:
            return Path(env)
    return DEFAULT_OPENCLAW_DIR


def _iter_default_session_dirs(base: Path) -> List[Path]:
    dirs: List[Path] = []
    root_sessions = base / "sessions"
    dirs.append(root_sessions)

    agents_root = base / "agents"
    if agents_root.exists():
        for agent_sessions_dir in sorted(agents_root.glob("*/sessions")):
            dirs.append(agent_sessions_dir)

    return dirs


def _session_path_candidates(base: Path, session_id: str, agent_id: Optional[str]) -> List[Path]:
    candidates: List[Path] = []
    seen: set[str] = set()

    if agent_id:
        targeted = base / "agents" / agent_id / "sessions" / f"{session_id}.jsonl"
        candidates.append(targeted)
    candidates.append(base / "sessions" / f"{session_id}.jsonl")

    if not agent_id:
        for sessions_dir in _iter_default_session_dirs(base):
            candidates.append(sessions_dir / f"{session_id}.jsonl")

    uniq: List[Path] = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(path)
    return uniq


def _normalize_tool_names(tools: Any) -> List[str]:
    if not isinstance(tools, list):
        return []
    out: List[str] = []
    for item in tools:
        if isinstance(item, str):
            out.append(item)
            continue
        if not isinstance(item, dict):
            continue
        candidate = item.get("name") or item.get("toolName") or item.get("tool_name")
        if isinstance(candidate, str) and candidate:
            out.append(candidate)
    return out


def _extract_content_preview(content: Any) -> str:
    if isinstance(content, list):
        text_parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        joined = " ".join(part for part in text_parts if part)
        return joined[:200]
    if isinstance(content, str):
        return content[:200]
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text[:200]
    return str(content)[:200]


# ---------------------------------------------------------------------------
# JSONL parsing helpers
# ---------------------------------------------------------------------------


def _read_jsonl(filepath: Path) -> List[Dict[str, Any]]:
    """Read a JSONL file, skipping malformed lines."""
    entries: List[Dict[str, Any]] = []
    if not filepath.exists():
        return entries
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    entries.append(obj)
            except json.JSONDecodeError:
                continue
    return entries


def _ts_to_datetime(ts: Any) -> Optional[datetime]:
    """Convert epoch-ms timestamp to UTC datetime."""
    if not isinstance(ts, (int, float)) or not ts:
        return None
    try:
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    except (OSError, ValueError, OverflowError):
        return None


# ---------------------------------------------------------------------------
# 1. Cron Run Logs → DataFrame
# ---------------------------------------------------------------------------


def load_cron_runs(
    openclaw_dir: Optional[str] = None,
    job_id: Optional[str] = None,
) -> pd.DataFrame:
    """
    Load cron job execution logs into a DataFrame.

    Each row = one finished job execution with columns:
        timestamp, job_id, run_id, status, error, summary,
        duration_ms, model, provider,
        input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, total_tokens,
        delivery_status, delivery_error, session_id

    Args:
        openclaw_dir: Override ~/.openclaw base directory.
        job_id: Filter to a specific job ID.

    Returns:
        pd.DataFrame sorted by timestamp ascending.
    """
    base = _resolve_openclaw_dir(openclaw_dir)
    runs_dir = base / "cron" / "runs"

    if not runs_dir.exists():
        return _empty_cron_df()

    jsonl_files = sorted(runs_dir.glob("*.jsonl"))
    if job_id:
        target = runs_dir / f"{job_id}.jsonl"
        jsonl_files = [target] if target.exists() else []

    all_rows: List[Dict[str, Any]] = []

    for filepath in jsonl_files:
        source_job_id = filepath.stem
        entries = _read_jsonl(filepath)
        for entry in entries:
            if entry.get("action") != "finished":
                continue
            if not isinstance(entry.get("ts"), (int, float)):
                continue

            usage = entry.get("usage") or {}

            row = {
                "timestamp": _ts_to_datetime(entry["ts"]),
                "ts_epoch_ms": entry["ts"],
                "job_id": entry.get("jobId", source_job_id),
                "run_id": entry.get("runId"),
                "status": entry.get("status"),
                "error": entry.get("error"),
                "summary": entry.get("summary"),
                "duration_ms": entry.get("durationMs"),
                "model": entry.get("model"),
                "provider": entry.get("provider"),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "cache_read_tokens": usage.get("cache_read_tokens"),
                "cache_write_tokens": usage.get("cache_write_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "delivery_status": entry.get("deliveryStatus"),
                "delivery_error": entry.get("deliveryError"),
                "session_id": entry.get("sessionId"),
            }
            all_rows.append(row)

    if not all_rows:
        return _empty_cron_df()

    df = pd.DataFrame(all_rows)
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Type coercion
    for col in [
        "input_tokens", "output_tokens", "cache_read_tokens",
        "cache_write_tokens", "total_tokens", "duration_ms",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["status"] = df["status"].astype("category")
    df["delivery_status"] = df["delivery_status"].astype("category")

    return df


def _empty_cron_df() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "timestamp", "ts_epoch_ms", "job_id", "run_id", "status", "error",
        "summary", "duration_ms", "model", "provider",
        "input_tokens", "output_tokens", "cache_read_tokens",
        "cache_write_tokens", "total_tokens",
        "delivery_status", "delivery_error", "session_id",
    ])


# ---------------------------------------------------------------------------
# 2. Session Transcripts → DataFrame
# ---------------------------------------------------------------------------


def load_session_transcript(
    session_id: str,
    openclaw_dir: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> pd.DataFrame:
    """
    Load a single session transcript JSONL into a DataFrame.

    Each row = one message/turn with columns:
        timestamp, role, content_preview, tokens_input, tokens_output,
        tokens_cache_read, tokens_cache_write,
        model, provider, cost_total, tool_names, duration_ms, stop_reason

    Args:
        session_id: Session ID (filename stem without .jsonl).
        openclaw_dir: Override ~/.openclaw base directory.
        agent_id: Agent ID subdirectory (if using agent sessions).

    Returns:
        pd.DataFrame sorted by timestamp ascending.
    """
    base = _resolve_openclaw_dir(openclaw_dir)

    # Try all known locations (agent-specific first if explicitly requested).
    candidates = _session_path_candidates(base, session_id, agent_id)

    entries: List[Dict[str, Any]] = []
    for path in candidates:
        if path.exists():
            entries = _read_jsonl(path)
            break

    if not entries:
        return _empty_transcript_df()

    rows: List[Dict[str, Any]] = []
    for entry in entries:
        msg = entry.get("message") if isinstance(entry.get("message"), dict) else entry
        if not isinstance(msg, dict):
            continue

        usage = msg.get("usage") or entry.get("usage") or {}
        cost = (
            msg.get("cost")
            or msg.get("costBreakdown")
            or entry.get("cost")
            or entry.get("costBreakdown")
            or {}
        )
        tools = (
            msg.get("toolCalls")
            or msg.get("toolNames")
            or entry.get("toolCalls")
            or entry.get("toolNames")
            or []
        )

        content_preview = _extract_content_preview(msg.get("content", ""))
        ts = msg.get("timestamp") or entry.get("timestamp") or msg.get("ts") or entry.get("ts")

        row = {
            "timestamp": _ts_to_datetime(ts) if isinstance(ts, (int, float)) else None,
            "ts_epoch_ms": ts if isinstance(ts, (int, float)) else None,
            "role": msg.get("role"),
            "content_preview": content_preview,
            "tokens_input": usage.get("input") or usage.get("inputTokens") or usage.get("input_tokens"),
            "tokens_output": usage.get("output") or usage.get("outputTokens") or usage.get("output_tokens"),
            "tokens_cache_read": usage.get("cacheRead") or usage.get("cache_read_input_tokens"),
            "tokens_cache_write": usage.get("cacheWrite") or usage.get("cache_creation_input_tokens"),
            "model": msg.get("model") or entry.get("model"),
            "provider": msg.get("provider") or entry.get("provider"),
            "cost_total": cost.get("total") if isinstance(cost, dict) else cost,
            "tool_names": _normalize_tool_names(tools),
            "duration_ms": (
                msg.get("durationMs")
                or msg.get("duration_ms")
                or entry.get("durationMs")
                or entry.get("duration_ms")
            ),
            "stop_reason": (
                msg.get("stopReason")
                or msg.get("stop_reason")
                or entry.get("stopReason")
                or entry.get("stop_reason")
            ),
        }
        rows.append(row)

    if not rows:
        return _empty_transcript_df()

    df = pd.DataFrame(rows)
    df = df.sort_values("timestamp", na_position="first").reset_index(drop=True)

    for col in [
        "tokens_input", "tokens_output", "tokens_cache_read",
        "tokens_cache_write", "duration_ms", "cost_total",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def _empty_transcript_df() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "timestamp", "ts_epoch_ms", "role", "content_preview",
        "tokens_input", "tokens_output", "tokens_cache_read", "tokens_cache_write",
        "model", "provider", "cost_total", "tool_names", "duration_ms", "stop_reason",
    ])


# ---------------------------------------------------------------------------
# 3. Session Discovery → DataFrame
# ---------------------------------------------------------------------------


def load_sessions(
    openclaw_dir: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 100,
) -> pd.DataFrame:
    """
    Discover available session files and return metadata.

    Columns:
        session_id, file_path, size_bytes, modified_at, line_count

    Args:
        openclaw_dir: Override ~/.openclaw base directory.
        agent_id: Agent ID to scope session discovery.
        limit: Max sessions to return (most recent first).

    Returns:
        pd.DataFrame sorted by modified_at descending.
    """
    base = _resolve_openclaw_dir(openclaw_dir)

    search_dirs: List[Path] = []
    if agent_id:
        search_dirs.append(base / "agents" / agent_id / "sessions")
        search_dirs.append(base / "sessions")
    else:
        search_dirs.extend(_iter_default_session_dirs(base))

    rows: List[Dict[str, Any]] = []
    seen_paths: set[str] = set()

    for sessions_dir in search_dirs:
        if not sessions_dir.exists():
            continue
        for filepath in sessions_dir.glob("*.jsonl"):
            key = str(filepath.resolve())
            if key in seen_paths:
                continue
            seen_paths.add(key)

            sid = filepath.stem
            resolved_parts = filepath.parts
            detected_agent_id: Optional[str] = None
            if "agents" in resolved_parts and "sessions" in resolved_parts:
                try:
                    agents_idx = resolved_parts.index("agents")
                    detected_agent_id = resolved_parts[agents_idx + 1]
                except (ValueError, IndexError):
                    detected_agent_id = None

            stat = filepath.stat()
            # Quick line count
            line_count = 0
            try:
                with open(filepath, "rb") as f:
                    line_count = sum(1 for _ in f)
            except OSError:
                pass

            rows.append({
                "session_id": sid,
                "file_path": str(filepath),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                "line_count": line_count,
                "agent_id": detected_agent_id,
            })

    if not rows:
        return pd.DataFrame(columns=[
            "session_id", "file_path", "size_bytes", "modified_at", "line_count", "agent_id",
        ])

    df = pd.DataFrame(rows)
    df = df.sort_values("modified_at", ascending=False).reset_index(drop=True)
    return df.head(limit)


# ---------------------------------------------------------------------------
# 4. Convenience aggregation helpers
# ---------------------------------------------------------------------------


def cron_daily_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate cron run logs by date.

    Returns DataFrame with columns:
        date, total_runs, ok_count, error_count, skipped_count,
        avg_duration_ms, total_input_tokens, total_output_tokens, total_tokens
    """
    if df.empty or "timestamp" not in df.columns:
        return pd.DataFrame()

    df = df.copy()
    df["date"] = df["timestamp"].dt.date

    agg = df.groupby("date").agg(
        total_runs=("status", "count"),
        ok_count=("status", lambda x: (x == "ok").sum()),
        error_count=("status", lambda x: (x == "error").sum()),
        skipped_count=("status", lambda x: (x == "skipped").sum()),
        avg_duration_ms=("duration_ms", "mean"),
        total_input_tokens=("input_tokens", "sum"),
        total_output_tokens=("output_tokens", "sum"),
        total_tokens=("total_tokens", "sum"),
    ).reset_index()

    agg["success_rate"] = (agg["ok_count"] / agg["total_runs"]).round(4)
    return agg.sort_values("date")


def cron_model_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate cron run logs by model/provider.

    Returns DataFrame with columns:
        provider, model, run_count, avg_duration_ms, total_tokens,
        total_input_tokens, total_output_tokens, error_rate
    """
    if df.empty or "model" not in df.columns:
        return pd.DataFrame()

    df = df.copy()
    df["provider"] = df["provider"].fillna("unknown")
    df["model"] = df["model"].fillna("unknown")

    agg = df.groupby(["provider", "model"]).agg(
        run_count=("status", "count"),
        ok_count=("status", lambda x: (x == "ok").sum()),
        error_count=("status", lambda x: (x == "error").sum()),
        avg_duration_ms=("duration_ms", "mean"),
        total_tokens=("total_tokens", "sum"),
        total_input_tokens=("input_tokens", "sum"),
        total_output_tokens=("output_tokens", "sum"),
    ).reset_index()

    agg["error_rate"] = (agg["error_count"] / agg["run_count"]).round(4)
    return agg.sort_values("run_count", ascending=False)


def cron_job_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate cron run logs by job_id.

    Returns DataFrame with columns:
        job_id, run_count, ok_count, error_count, success_rate,
        avg_duration_ms, last_run, last_status
    """
    if df.empty or "job_id" not in df.columns:
        return pd.DataFrame()

    agg = df.groupby("job_id").agg(
        run_count=("status", "count"),
        ok_count=("status", lambda x: (x == "ok").sum()),
        error_count=("status", lambda x: (x == "error").sum()),
        avg_duration_ms=("duration_ms", "mean"),
        total_tokens=("total_tokens", "sum"),
        last_run=("timestamp", "max"),
        last_status=("status", "last"),
    ).reset_index()

    agg["success_rate"] = (agg["ok_count"] / agg["run_count"]).round(4)
    return agg.sort_values("run_count", ascending=False)


# ---------------------------------------------------------------------------
# 5. Export helpers
# ---------------------------------------------------------------------------


def export_to_csv(df: pd.DataFrame, path: str) -> None:
    """Export DataFrame to CSV."""
    df.to_csv(path, index=False)
    print(f"Exported {len(df)} rows to {path}")


def export_to_parquet(df: pd.DataFrame, path: str) -> None:
    """Export DataFrame to Parquet (requires pyarrow or fastparquet)."""
    df.to_parquet(path, index=False)
    print(f"Exported {len(df)} rows to {path}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="OpenClaw JSONL → DataFrame loader. Quick summary of available data."
    )
    parser.add_argument(
        "--dir", help="Override ~/.openclaw base directory."
    )
    parser.add_argument(
        "--source",
        choices=["cron", "sessions", "all"],
        default="all",
        help="Which data source to summarize.",
    )
    parser.add_argument(
        "--export-csv", help="Export cron runs to CSV at this path."
    )
    parser.add_argument(
        "--export-parquet", help="Export cron runs to Parquet at this path."
    )
    args = parser.parse_args()

    if args.source in ("cron", "all"):
        print("=== Cron Run Logs ===")
        df = load_cron_runs(openclaw_dir=args.dir)
        if df.empty:
            print("  No cron run logs found.")
        else:
            print(f"  Total runs: {len(df)}")
            print(f"  Date range: {df['timestamp'].min()} → {df['timestamp'].max()}")
            print(f"  Jobs: {df['job_id'].nunique()}")
            print(f"  Models: {df['model'].dropna().nunique()}")
            if "status" in df.columns:
                counts = df["status"].value_counts()
                for status, count in counts.items():
                    print(f"    {status}: {count}")

            if args.export_csv:
                export_to_csv(df, args.export_csv)
            if args.export_parquet:
                export_to_parquet(df, args.export_parquet)

        print()

    if args.source in ("sessions", "all"):
        print("=== Sessions ===")
        sessions = load_sessions(openclaw_dir=args.dir)
        if sessions.empty:
            print("  No sessions found.")
        else:
            print(f"  Total sessions: {len(sessions)}")
            total_size = sessions["size_bytes"].sum()
            print(f"  Total size: {total_size / 1024 / 1024:.1f} MB")
            print(f"  Most recent: {sessions['modified_at'].iloc[0]}")
            print(f"  Oldest: {sessions['modified_at'].iloc[-1]}")


if __name__ == "__main__":
    main()

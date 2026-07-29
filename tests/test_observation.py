import json
from pathlib import Path

import pandas as pd
import pytest

from feedback_triage_agent.observation import (
    STATE_FILENAME,
    add_import,
    append_audit_event,
    apply_cluster_action,
    build_workspace,
    create_task,
    list_tasks,
    load_task,
    render_owner_summary,
)


def create_observation(tmp_path: Path, **overrides):
    values = {
        "name": "智能回复 v2.4 发版观察",
        "product_name": "Acme Copilot",
        "baseline_version": "v2.3",
        "current_version": "v2.4",
        "baseline_window_start": "2026-07-01T10:00",
        "baseline_window_end": "2026-07-04T10:00",
        "current_window_start": "2026-07-10T10:00",
        "current_window_end": "2026-07-13T10:00",
        "comparison_basis": "equivalent_window",
        "comparison_note": "",
        "change_summary": "灰度发布新的生成链路。",
    }
    values.update(overrides)
    return create_task(tmp_path / "tasks", **values)


def write_feedback(tmp_path: Path, name: str, rows):
    path = tmp_path / name
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def import_rows(
    task,
    tmp_path: Path,
    name: str,
    rows,
    *,
    window_kind: str,
    hours: int = 24,
    source: str = "App Store",
    mode: str = "cumulative",
):
    path = write_feedback(tmp_path, name, rows)
    return add_import(
        task,
        source_path=path,
        filename=name,
        window_kind=window_kind,
        observation_hours=hours,
        source=source,
        import_mode=mode,
    )


def test_create_task_validates_comparison_basis_and_persists(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="同等窗口要求"):
        create_observation(
            tmp_path,
            current_window_end="2026-07-12T10:00",
        )

    with pytest.raises(ValueError, match="必须填写口径说明"):
        create_observation(
            tmp_path,
            comparison_basis="other",
            current_window_end="2026-07-12T10:00",
        )

    task = create_observation(tmp_path)

    state_path = Path(task["task_dir"]) / STATE_FILENAME
    assert state_path.exists()
    loaded = load_task(tmp_path / "tasks", task["task_id"])
    assert loaded["comparison_basis"] == "equivalent_window"
    assert loaded["baseline_window_hours"] == 72
    assert loaded["current_window_hours"] == 72
    assert loaded["audit_events"][0]["action"] == "创建观察任务"
    assert list_tasks(tmp_path / "tasks")[0]["task_id"] == task["task_id"]


def test_other_comparison_basis_is_explicitly_stored(tmp_path: Path) -> None:
    task = create_observation(
        tmp_path,
        comparison_basis="other",
        comparison_note="当前窗口只有 48 小时，结论同时看占比。",
        current_window_end="2026-07-12T10:00",
    )

    assert task["comparison_basis"] == "other"
    assert task["comparison_note"] == "当前窗口只有 48 小时，结论同时看占比。"


def test_import_accepts_aliases_and_missing_rating_without_fabrication(
    tmp_path: Path,
) -> None:
    task = create_observation(tmp_path)
    result = import_rows(
        task,
        tmp_path,
        "baseline.csv",
        [
            {"reviewId": "b1", "content": "生成时崩溃，草稿全部丢失", "extra": "保留"},
            {"reviewId": "b2", "content": "整体很好用"},
        ],
        window_kind="baseline",
    )

    workspace = build_workspace(task, selected_window=24)

    assert result["accepted_count"] == 2
    assert result["missing_rating_count"] == 2
    assert result["column_mapping"]["review_text"] == "content"
    assert workspace["metrics"]["baseline_feedback_count"] == 2
    cluster = next(item for item in workspace["clusters"] if "崩溃" in item["title"])
    assert cluster["members"][0]["rating"] is None
    assert cluster["members"][0]["metadata"]["extra"] == "保留"
    assert "评分 None" not in json.dumps(workspace, ensure_ascii=False)


def test_cumulative_snapshot_replaces_previous_snapshot_for_same_scope(
    tmp_path: Path,
) -> None:
    task = create_observation(tmp_path)
    import_rows(
        task,
        tmp_path,
        "current-first.csv",
        [
            {"id": "a", "review_text": "页面很慢"},
            {"id": "b", "review_text": "复制按钮失效"},
        ],
        window_kind="current",
    )
    import_rows(
        task,
        tmp_path,
        "current-latest.csv",
        [
            {"id": "a", "review_text": "页面很慢"},
            {"id": "c", "review_text": "登录一直失败"},
        ],
        window_kind="current",
    )

    workspace = build_workspace(task, selected_window=24)
    member_ids = {
        member["feedback_id"]
        for cluster in workspace["clusters"]
        for member in cluster["members"]
    }

    assert workspace["metrics"]["current_feedback_count"] == 2
    assert member_ids == {"a", "c"}
    assert workspace["imports"][0]["import_mode"] == "cumulative"


def test_incremental_import_appends_only_new_feedback(tmp_path: Path) -> None:
    task = create_observation(tmp_path)
    import_rows(
        task,
        tmp_path,
        "current-base.csv",
        [
            {"id": "a", "review_text": "页面很慢"},
            {"id": "b", "review_text": "复制按钮失效"},
        ],
        window_kind="current",
    )
    result = import_rows(
        task,
        tmp_path,
        "current-increment.csv",
        [
            {"id": "b", "review_text": "复制按钮失效"},
            {"id": "c", "review_text": "登录一直失败"},
        ],
        window_kind="current",
        mode="incremental",
    )

    workspace = build_workspace(task, selected_window=24)

    assert result["accepted_count"] == 1
    assert result["duplicate_count"] == 1
    assert workspace["metrics"]["current_feedback_count"] == 3


def test_similar_feedback_forms_one_evidence_backed_cluster_and_change_status(
    tmp_path: Path,
) -> None:
    task = create_observation(tmp_path)
    import_rows(
        task,
        tmp_path,
        "baseline.csv",
        [
            {"id": "b1", "review_text": "生成时崩溃，草稿丢失", "rating": 1},
            {"id": "b2", "review_text": "很好用", "rating": 5},
        ],
        window_kind="baseline",
    )
    import_rows(
        task,
        tmp_path,
        "current.csv",
        [
            {"id": "c1", "review_text": "更新后生成一半闪退，内容丢失", "rating": 1},
            {"id": "c2", "review_text": "连续两次崩溃，草稿都没了", "rating": 1},
            {"id": "c3", "review_text": "整体很好用", "rating": 5},
        ],
        window_kind="current",
    )

    workspace = build_workspace(task, selected_window=24)
    cluster = next(item for item in workspace["clusters"] if "崩溃" in item["title"])

    assert cluster["baseline_count"] == 1
    assert cluster["current_count"] == 2
    assert cluster["change_status"] == "加重"
    assert cluster["risk_level"] == "P0"
    assert len(cluster["members"]) == 3
    assert {item["feedback_id"] for item in cluster["members"]} == {"b1", "c1", "c2"}
    assert cluster["risk_reasons"]
    assert all("由该版本导致" not in reason for reason in cluster["risk_reasons"])
    assert workspace["comparison_boundary"].startswith("仅说明")


def test_source_filter_recomputes_metrics_and_cluster_counts(tmp_path: Path) -> None:
    task = create_observation(tmp_path)
    for source, feedback_id in (("App Store", "a1"), ("客服", "s1")):
        import_rows(
            task,
            tmp_path,
            f"{feedback_id}.csv",
            [{"id": feedback_id, "review_text": "页面很慢"}],
            window_kind="current",
            source=source,
        )

    all_sources = build_workspace(task, selected_window=24)
    app_store = build_workspace(
        task,
        selected_window=24,
        selected_source="App Store",
    )
    unknown_source = build_workspace(
        task,
        selected_window=24,
        selected_source="不存在的来源",
    )

    assert all_sources["metrics"]["current_feedback_count"] == 2
    assert app_store["metrics"]["current_feedback_count"] == 1
    assert app_store["sources"] == ["App Store", "客服"]
    assert unknown_source["selected_source"] == "all"
    assert unknown_source["metrics"] == all_sources["metrics"]
    assert {
        member["source"]
        for cluster in app_store["clusters"]
        for member in cluster["members"]
    } == {"App Store"}


def test_split_uses_source_scoped_evidence_id_when_feedback_ids_collide(
    tmp_path: Path,
) -> None:
    task = create_observation(tmp_path)
    import_rows(
        task,
        tmp_path,
        "app-store.csv",
        [{"id": "same-1", "review_text": "页面很慢"}],
        window_kind="current",
        source="App Store",
    )
    import_rows(
        task,
        tmp_path,
        "support.csv",
        [
            {"id": "same-1", "review_text": "加载太慢"},
            {"id": "support-2", "review_text": "响应很慢"},
        ],
        window_kind="current",
        source="客服",
    )
    cluster = next(
        item
        for item in build_workspace(task, selected_window=24)["clusters"]
        if item["current_count"] == 3
    )

    with pytest.raises(ValueError, match="多个来源中重复"):
        apply_cluster_action(
            task,
            cluster["cluster_id"],
            "split",
            changes={"feedback_ids": ["same-1"]},
            reason="验证重名反馈边界。",
            selected_window=24,
        )

    split = apply_cluster_action(
        task,
        cluster["cluster_id"],
        "split",
        changes={"feedback_ids": ["App Store:same-1"]},
        reason="只拆出 App Store 的一条反馈。",
        selected_window=24,
    )
    workspace = build_workspace(task, selected_window=24)
    new_cluster = next(
        item
        for item in workspace["clusters"]
        if item["cluster_id"] == split["changes"]["new_cluster_id"]
    )
    assert [item["evidence_id"] for item in new_cluster["members"]] == [
        "App Store:same-1"
    ]


def test_human_confirmation_updates_owner_summary_without_overwriting_evidence(
    tmp_path: Path,
) -> None:
    task = create_observation(tmp_path)
    import_rows(
        task,
        tmp_path,
        "current.csv",
        [
            {"id": "c1", "review_text": "生成时崩溃，草稿丢失", "rating": 1},
            {"id": "c2", "review_text": "又闪退了，内容全部丢失", "rating": 1},
        ],
        window_kind="current",
    )
    before = build_workspace(task, selected_window=24)
    cluster = next(item for item in before["clusters"] if "崩溃" in item["title"])

    apply_cluster_action(
        task,
        cluster["cluster_id"],
        "confirm",
        changes={
            "risk_level": "P0",
            "owner": "客户端团队",
            "work_status": "处理中",
            "next_action": "核对崩溃堆栈并发布修复",
            "result": "等待 48h 窗口验证",
        },
        reason="两条原话指向同一崩溃链路。",
        selected_window=24,
    )
    after = build_workspace(task, selected_window=24)
    updated = next(item for item in after["clusters"] if item["cluster_id"] == cluster["cluster_id"])

    assert updated["review_status"] == "已确认"
    assert updated["owner"] == "客户端团队"
    assert updated["system_snapshot"] == cluster["system_snapshot"]
    assert len(updated["members"]) == len(cluster["members"])
    assert "客户端团队" in after["owner_summary"]
    assert "不代表版本因果" in after["owner_summary"]
    assert "客户端团队" in render_owner_summary(task, selected_window=24)
    assert after["audit_events"][0]["action"] == "确认问题簇"


def test_reject_removes_cluster_from_owner_summary_but_keeps_system_evidence(
    tmp_path: Path,
) -> None:
    task = create_observation(tmp_path)
    import_rows(
        task,
        tmp_path,
        "current.csv",
        [{"id": "c1", "review_text": "页面很慢", "rating": 2}],
        window_kind="current",
    )
    cluster = build_workspace(task, selected_window=24)["clusters"][0]
    apply_cluster_action(
        task,
        cluster["cluster_id"],
        "confirm",
        changes={"owner": "体验团队"},
        selected_window=24,
    )
    apply_cluster_action(
        task,
        cluster["cluster_id"],
        "reject",
        reason="原话实际描述的是网络环境，不作为产品问题确认。",
        selected_window=24,
    )

    workspace = build_workspace(task, selected_window=24)
    rejected = workspace["clusters"][0]
    assert rejected["review_status"] == "已驳回"
    assert rejected["members"]
    assert workspace["owner_summary"] == ""


def test_split_and_merge_are_persistent_and_invalid_action_is_atomic(
    tmp_path: Path,
) -> None:
    task = create_observation(tmp_path)
    import_rows(
        task,
        tmp_path,
        "current.csv",
        [
            {"id": "c1", "review_text": "页面很慢"},
            {"id": "c2", "review_text": "加载太慢"},
        ],
        window_kind="current",
    )
    workspace = build_workspace(task, selected_window=24)
    cluster = next(item for item in workspace["clusters"] if item["current_count"] == 2)
    audit_count = len(workspace["audit_events"])

    with pytest.raises(ValueError, match="目标问题簇不存在"):
        apply_cluster_action(
            task,
            cluster["cluster_id"],
            "merge",
            changes={"target_cluster_id": "cluster_missing"},
            reason="尝试错误目标",
            selected_window=24,
        )
    assert len(build_workspace(task, selected_window=24)["audit_events"]) == audit_count

    split = apply_cluster_action(
        task,
        cluster["cluster_id"],
        "split",
        changes={"feedback_ids": ["c2"]},
        reason="c2 只描述加载阶段，需要单独跟踪。",
        selected_window=24,
    )
    split_id = split["changes"]["new_cluster_id"]
    split_workspace = build_workspace(task, selected_window=24)
    assert {item["cluster_id"] for item in split_workspace["clusters"]} == {
        cluster["cluster_id"],
        split_id,
    }

    apply_cluster_action(
        task,
        split_id,
        "merge",
        changes={"target_cluster_id": cluster["cluster_id"]},
        reason="复核后确认仍属于同一性能链路。",
        selected_window=24,
    )
    merged = build_workspace(task, selected_window=24)
    assert len(merged["clusters"]) == 1
    assert merged["clusters"][0]["current_count"] == 2


def test_next_window_trajectory_uses_real_snapshots(tmp_path: Path) -> None:
    task = create_observation(tmp_path)
    import_rows(
        task,
        tmp_path,
        "current-24.csv",
        [
            {"id": "c1", "review_text": "页面很慢"},
            {"id": "p1", "review_text": "整体很好用", "rating": 5},
        ],
        window_kind="current",
        hours=24,
    )
    import_rows(
        task,
        tmp_path,
        "current-48.csv",
        [
            {"id": "c1", "review_text": "页面很慢"},
            {"id": "c2", "review_text": "加载太慢"},
            {"id": "p1", "review_text": "整体很好用", "rating": 5},
        ],
        window_kind="current",
        hours=48,
    )

    cluster = next(
        item
        for item in build_workspace(task, selected_window=48)["clusters"]
        if "慢" in item["title"] or "延迟" in item["title"]
    )
    assert cluster["trajectory"] == "较 24h 继续恶化"


def test_failed_import_and_external_failure_are_audited(tmp_path: Path) -> None:
    task = create_observation(tmp_path)
    bad_path = write_feedback(tmp_path, "bad.csv", [{"id": "x1", "note": "没有正文"}])

    with pytest.raises(ValueError, match="未识别到反馈正文字段"):
        add_import(
            task,
            source_path=bad_path,
            filename="bad.csv",
            window_kind="current",
            observation_hours=24,
            source="客服",
        )
    append_audit_event(
        task,
        "导入失败",
        "上传文件不是 CSV。",
        details={"filename": "notes.txt"},
    )

    loaded = load_task(tmp_path / "tasks", task["task_id"])
    assert loaded["imports"][0]["status"] == "failed"
    assert "records" not in loaded["imports"][0]
    assert [event["action"] for event in loaded["audit_events"][-2:]] == [
        "导入失败",
        "导入失败",
    ]


def test_followup_is_an_independent_window_and_keeps_both_comparisons(
    tmp_path: Path,
) -> None:
    task = create_observation(
        tmp_path,
        baseline_window_start="2026-07-01T00:00",
        baseline_window_end="2026-07-03T00:00",
        current_window_start="2026-07-03T00:00",
        current_window_end="2026-07-05T00:00",
        followup_window_start="2026-07-05T00:00",
        followup_window_end="2026-07-07T00:00",
    )
    import_rows(
        task,
        tmp_path,
        "baseline.csv",
        [{"id": "b1", "review_text": "登录失败", "created_at": "2026-07-02T01:00+08:00"}],
        window_kind="baseline",
        hours=48,
    )
    import_rows(
        task,
        tmp_path,
        "current.csv",
        [{"id": "c1", "review_text": "登录还是失败", "created_at": "2026-07-04T01:00+08:00"}],
        window_kind="current",
        hours=48,
    )
    import_rows(
        task,
        tmp_path,
        "followup.csv",
        [{"id": "f1", "review_text": "登录失败次数增加", "created_at": "2026-07-06T01:00+08:00"}],
        window_kind="followup",
        hours=48,
    )

    workspace = build_workspace(task, selected_window=48)

    assert workspace["metrics"]["baseline_feedback_count"] == 1
    assert workspace["metrics"]["current_feedback_count"] == 1
    assert workspace["metrics"]["followup_feedback_count"] == 1
    assert workspace["followup_comparison"]["left_label"] == "当前"
    assert workspace["followup_comparison"]["right_label"] == "后续"
    assert len(workspace["comparisons"]) == 2
    assert workspace["comparisons"][0]["metrics"]["right_feedback_count"] == 1
    assert workspace["comparisons"][1]["metrics"]["left_feedback_count"] == 1
    assert workspace["comparisons"][1]["metrics"]["right_feedback_count"] == 1


def test_import_validation_rejects_the_whole_batch_and_audits_reason(
    tmp_path: Path,
) -> None:
    task = create_observation(tmp_path)
    duplicate_path = write_feedback(
        tmp_path,
        "duplicate.csv",
        [
            {"id": "dup", "review_text": "第一次反馈", "created_at": "2026-07-11T01:00+08:00"},
            {"id": "dup", "review_text": "第二次反馈", "created_at": "2026-07-11T02:00+08:00"},
        ],
    )
    with pytest.raises(ValueError, match="文件内部存在重复反馈 ID"):
        add_import(
            task,
            source_path=duplicate_path,
            filename="duplicate.csv",
            window_kind="current",
            observation_hours=24,
            source="App Store",
        )

    out_of_window_path = write_feedback(
        tmp_path,
        "out.csv",
        [{"id": "out", "review_text": "窗口外", "created_at": "2026-07-14T01:00+08:00"}],
    )
    with pytest.raises(ValueError, match="存在窗口外时间"):
        add_import(
            task,
            source_path=out_of_window_path,
            filename="out.csv",
            window_kind="current",
            observation_hours=24,
            source="App Store",
        )

    loaded = load_task(tmp_path / "tasks", task["task_id"])
    assert all(item["status"] == "failed" for item in loaded["imports"])
    assert len(build_workspace(task, selected_window=24)["clusters"]) == 0
    assert any("未写入任何反馈" in event["message"] for event in loaded["audit_events"])


def test_existing_id_with_changed_content_is_rejected_without_partial_write(
    tmp_path: Path,
) -> None:
    task = create_observation(tmp_path)
    import_rows(
        task,
        tmp_path,
        "first.csv",
        [{"id": "same", "review_text": "页面很慢"}],
        window_kind="current",
    )
    changed_path = write_feedback(
        tmp_path,
        "changed.csv",
        [{"id": "same", "review_text": "登录失败"}],
    )
    with pytest.raises(ValueError, match="内容不同"):
        add_import(
            task,
            source_path=changed_path,
            filename="changed.csv",
            window_kind="current",
            observation_hours=24,
            source="App Store",
        )
    workspace = build_workspace(task, selected_window=24)
    assert workspace["metrics"]["current_feedback_count"] == 1
    assert workspace["clusters"][0]["members"][0]["review_text"] == "页面很慢"


def test_function_and_failure_boundary_handles_unseen_synonyms(tmp_path: Path) -> None:
    task = create_observation(tmp_path)
    import_rows(
        task,
        tmp_path,
        "synonyms.csv",
        [
            {"id": "u1", "review_text": "下载导出没有产出文件"},
            {"id": "u2", "review_text": "导出进度到99%后一直不动"},
            {"id": "u3", "review_text": "导出文件成功生成但列排列错乱"},
            {"id": "u4", "review_text": "导出完成后文字挤在一起"},
            {"id": "u5", "review_text": "答案写到中途就停了，后文没有显示"},
            {"id": "u6", "review_text": "长输出尾部被截掉"},
        ],
        window_kind="current",
    )

    clusters = build_workspace(task, selected_window=24)["clusters"]
    by_title = {cluster["title"]: cluster for cluster in clusters}
    assert by_title["导出文件失败"]["current_count"] == 2
    assert by_title["导出成功但格式错乱"]["current_count"] == 2
    assert by_title["回答被截断"]["current_count"] == 2
    assert len(clusters) == 3


def test_vague_candidate_does_not_get_a_determined_trend(tmp_path: Path) -> None:
    task = create_observation(tmp_path)
    import_rows(
        task,
        tmp_path,
        "vague.csv",
        [{"id": "v1", "review_text": "最近感觉不太好用但说不清具体哪里"}],
        window_kind="current",
    )

    cluster = build_workspace(task, selected_window=24)["clusters"][0]
    assert cluster["change_status"] == "待复核／趋势暂不判定"
    assert cluster["review_status"] == "待复核"
    assert "不自动输出" in "".join(cluster["risk_reasons"])


def test_evidence_exposes_version_and_full_window_boundary(tmp_path: Path) -> None:
    task = create_observation(
        tmp_path,
        baseline_window_start="2026-07-01T00:00",
        baseline_window_end="2026-07-04T00:00",
    )
    import_rows(
        task,
        tmp_path,
        "evidence.csv",
        [{
            "id": "e1",
            "created_at": "2026-07-02T01:00+08:00",
            "version": "v2.3",
            "review_text": "登录失败",
        }],
        window_kind="baseline",
    )
    member = build_workspace(task, selected_window=24)["clusters"][0]["members"][0]
    assert member["feedback_id"] == "e1"
    assert member["review_text"] == "登录失败"
    assert member["source"] == "App Store"
    assert member["version"] == "v2.3"
    assert member["window_label"] == "基线窗口"
    assert member["window_start"] == "2026-07-01T00:00"
    assert member["window_end"] == "2026-07-04T00:00"

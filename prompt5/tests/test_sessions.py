"""M5 · 在线会话：语义门控、事件序、四元组 CAS、fencing、幂等、事件 outbox/重试/DLQ。"""

from __future__ import annotations

import pytest

from prompt5.engine.iterate import propose_patch
from prompt5.ledger import Ledger
from prompt5.modules.m6_events import deliver_pending, emit, pull
from prompt5.modules.m6_sessions import SessionError, SessionStore, classify_turn
from prompt5.store.migrate import init_db
from prompt5.testing import add_op, make_ir, make_patch


@pytest.fixture()
def env():
    conn = init_db(":memory:")
    ledger = Ledger(conn)
    store = SessionStore(conn)
    ir = make_ir()
    stored = ledger.create_ir(ir.payload() | {"checksum": ir.checksum})
    try:
        yield conn, ledger, store, stored
    finally:
        conn.close()


class TestClassify:
    @pytest.mark.parametrize(
        "text,kind,invalidates",
        [
            ("好的，谢谢", "chitchat", False),
            ("收到了", "chitchat", False),
            ("进度：第 2 步已完成", "progress", False),
            ("我上传了一个新的 CSV", "material", True),
            ("改成表格输出吧", "goal", True),
            ("必须给出数据来源", "constraint", True),
            ("不对，我说的是按区域拆分", "correction", True),
            ("嗯这个再想想", "uncertain", True),
            ("", "uncertain", True),
        ],
    )
    def test_table(self, text: str, kind: str, invalidates: bool) -> None:
        signal = classify_turn(text)
        assert signal.kind == kind
        assert signal.invalidates is invalidates


class TestTurns:
    def test_seq_increments(self, env) -> None:
        _, _, store, ir = env
        session = store.open(ir.ir_id)
        assert store.record_turn(session["session_id"], "你好")["seq"] == 1
        assert store.record_turn(session["session_id"], "继续")["seq"] == 2
        assert [t["seq"] for t in store.turns(session["session_id"])] == [1, 2]

    def test_out_of_order_rejected(self, env) -> None:
        _, _, store, ir = env
        session = store.open(ir.ir_id)
        store.record_turn(session["session_id"], "你好")
        with pytest.raises(SessionError) as excinfo:
            store.record_turn(session["session_id"], "继续", seq=5)
        assert excinfo.value.code == "E_EVENT_ORDER"

    def test_context_hash_ignores_chitchat(self, env) -> None:
        _, _, store, ir = env
        session = store.open(ir.ir_id)
        baseline = store.context_hash(session["session_id"])
        store.record_turn(session["session_id"], "好的")
        store.record_turn(session["session_id"], "进度正常")
        assert store.context_hash(session["session_id"]) == baseline
        store.record_turn(session["session_id"], "我上传了新文件")
        assert store.context_hash(session["session_id"]) != baseline


class TestSuggestion:
    def _propose(self, env):
        _, ledger, store, ir = env
        session = store.open(ir.ir_id)
        patch = propose_patch(ir, "请用表格输出")
        assert patch is not None
        suggestion = store.propose(session["session_id"], patch, ledger)
        return session, suggestion

    def test_apply_bumps_epoch(self, env) -> None:
        _, ledger, store, ir = env
        session, suggestion = self._propose(env)
        result = store.apply(
            session["session_id"], suggestion["suggestion_id"],
            epoch=suggestion["epoch"], base_checksum=suggestion["base_checksum"],
            intent_hash=suggestion["intent_hash"], context_hash=suggestion["context_hash"],
            ledger=ledger,
        )
        assert result["status"] == "applied"
        assert result["new_epoch"] == 1
        assert ledger.history(ir.ir_id) == [1, 2]
        assert ledger.current(ir.ir_id).slots.output.format == "结构化表格"

    def test_idempotent_double_apply(self, env) -> None:
        _, ledger, store, _ = env
        session, suggestion = self._propose(env)
        kwargs = dict(
            epoch=suggestion["epoch"], base_checksum=suggestion["base_checksum"],
            intent_hash=suggestion["intent_hash"], context_hash=suggestion["context_hash"],
            ledger=ledger,
        )
        store.apply(session["session_id"], suggestion["suggestion_id"], **kwargs)
        again = store.apply(session["session_id"], suggestion["suggestion_id"], **kwargs)
        assert again["status"] == "idempotent"

    def test_stale_epoch_rejected(self, env) -> None:
        _, ledger, store, _ = env
        session, suggestion = self._propose(env)
        with pytest.raises(SessionError) as excinfo:
            store.apply(
                session["session_id"], suggestion["suggestion_id"],
                epoch=suggestion["epoch"] + 1, base_checksum=suggestion["base_checksum"],
                intent_hash=suggestion["intent_hash"], context_hash=suggestion["context_hash"],
                ledger=ledger,
            )
        assert excinfo.value.code == "E_FENCING_STALE"

    def test_base_drift_rejected(self, env) -> None:
        _, ledger, store, ir = env
        session, suggestion = self._propose(env)
        ledger.apply(make_patch(ir, [add_op("slots.workflow", "third")], intent="improve"))
        with pytest.raises(SessionError) as excinfo:
            store.apply(
                session["session_id"], suggestion["suggestion_id"],
                epoch=suggestion["epoch"], base_checksum=suggestion["base_checksum"],
                intent_hash=suggestion["intent_hash"], context_hash=suggestion["context_hash"],
                ledger=ledger,
            )
        assert excinfo.value.code == "E_BASE_DRIFT"

    def test_wrong_context_hash_rejected(self, env) -> None:
        _, ledger, store, _ = env
        session, suggestion = self._propose(env)
        with pytest.raises(SessionError) as excinfo:
            store.apply(
                session["session_id"], suggestion["suggestion_id"],
                epoch=suggestion["epoch"], base_checksum=suggestion["base_checksum"],
                intent_hash=suggestion["intent_hash"], context_hash="0" * 64,
                ledger=ledger,
            )
        assert excinfo.value.code == "E_FENCING_STALE"

    def test_wrong_intent_hash_rejected(self, env) -> None:
        _, ledger, store, _ = env
        session, suggestion = self._propose(env)
        with pytest.raises(SessionError) as excinfo:
            store.apply(
                session["session_id"], suggestion["suggestion_id"],
                epoch=suggestion["epoch"], base_checksum=suggestion["base_checksum"],
                intent_hash="f" * 64, context_hash=suggestion["context_hash"],
                ledger=ledger,
            )
        assert excinfo.value.code == "E_FENCING_STALE"

    def test_material_turn_invalidates_suggestion(self, env) -> None:
        _, ledger, store, _ = env
        session, suggestion = self._propose(env)
        result = store.record_turn(session["session_id"], "我上传了新的 CSV")
        assert result["invalidated_suggestions"] == 1
        with pytest.raises(SessionError) as excinfo:
            store.apply(
                session["session_id"], suggestion["suggestion_id"],
                epoch=suggestion["epoch"], base_checksum=suggestion["base_checksum"],
                intent_hash=suggestion["intent_hash"], context_hash=suggestion["context_hash"],
                ledger=ledger,
            )
        assert excinfo.value.code == "E_SUGGESTION_STALE"

    def test_chitchat_keeps_suggestion_alive(self, env) -> None:
        _, ledger, store, _ = env
        session, suggestion = self._propose(env)
        result = store.record_turn(session["session_id"], "好的，谢谢")
        assert result["invalidated_suggestions"] == 0
        applied = store.apply(
            session["session_id"], suggestion["suggestion_id"],
            epoch=suggestion["epoch"], base_checksum=suggestion["base_checksum"],
            intent_hash=suggestion["intent_hash"], context_hash=suggestion["context_hash"],
            ledger=ledger,
        )
        assert applied["status"] == "applied"

    def test_fencing_token_stale(self, env) -> None:
        _, ledger, store, _ = env
        session, suggestion = self._propose(env)
        with pytest.raises(SessionError) as excinfo:
            store.apply(
                session["session_id"], suggestion["suggestion_id"],
                epoch=suggestion["epoch"], base_checksum=suggestion["base_checksum"],
                intent_hash=suggestion["intent_hash"], context_hash=suggestion["context_hash"],
                ledger=ledger, fencing_token=99,
            )
        assert excinfo.value.code == "E_FENCING_STALE"


class TestEvents:
    def test_emit_and_pull_cursor(self, env) -> None:
        conn, _, store, ir = env
        session = store.open(ir.ir_id)
        emit(conn, session["session_id"], "custom.one", {"n": 1})
        emit(conn, session["session_id"], "custom.two", {"n": 2})
        all_events = pull(conn, session["session_id"], after_seq=0)
        assert [e["event_seq"] for e in all_events] >= [1, 2]
        last_seq = all_events[-1]["event_seq"]
        assert pull(conn, session["session_id"], after_seq=last_seq) == []

    def test_delivery_success(self, env) -> None:
        conn, _, store, ir = env
        session = store.open(ir.ir_id)
        seen: list[dict] = []
        stats = deliver_pending(conn, seen.append)
        assert stats["delivered"] >= 1
        assert seen and seen[0]["type"] == "session.opened"

    def test_retry_then_dead_letter(self, env) -> None:
        conn, _, store, ir = env
        session = store.open(ir.ir_id)

        def boom(_event):
            raise RuntimeError("callback down")

        for _ in range(5):
            deliver_pending(conn, boom, max_attempts=5)
        states = {row["state"] for row in conn.execute(
            "SELECT state FROM events WHERE session_id=?", (session["session_id"],)
        )}
        assert states == {"dead"}


class TestIdle:
    def test_expire_closes_session(self, env) -> None:
        conn, _, store, ir = env
        session = store.open(ir.ir_id)
        conn.execute(
            "UPDATE sessions SET idle_deadline='2000-01-01T00:00:00+00:00' WHERE session_id=?",
            (session["session_id"],),
        )
        assert store.expire_idle() == 1
        assert store.get(session["session_id"])["state"] == "closed"

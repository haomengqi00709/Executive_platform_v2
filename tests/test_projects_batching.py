"""Extraction used to batch conversations by RECENCY (fixed slices of 10), so a client's
threads scattered across batches and each batch coined its own project for that client —
the same engagement fragmented into near-duplicates (Vistergy ×4) that _merge_projects
(id-only dedup) never collapsed. Batching by client keeps a client's whole thread history
in one prompt. These guard: a client is never split below the cap; recency order preserved."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_batch_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import projects as pj  # noqa: E402

OWNER = {"daniel.zhang@imodel3d.com"}


def _conv(cid, *addrs):
    return (cid, [{
        "conversationId": cid,
        "from": {"emailAddress": {"address": addrs[0]}},
        "toRecipients": [{"emailAddress": {"address": a}} for a in addrs[1:]],
    }])


def _clients_of(batch):
    return {pj._conversation_client_key(msgs, OWNER) for _, msgs in batch}


def test_client_key_uses_company_domain_over_owner_and_freemail():
    # owner + a freemail cc must not win over the real company domain
    c = _conv("x", "davida@vistergy.com", "daniel.zhang@imodel3d.com", "someone@gmail.com")
    assert pj._conversation_client_key(c[1], OWNER) == "vistergy.com"


def test_freemail_person_keeps_distinct_keys():
    a = pj._conversation_client_key(_conv("a", "esteves@outlook.com")[1], OWNER)
    b = pj._conversation_client_key(_conv("b", "yusong@outlook.com")[1], OWNER)
    assert a != b  # two different people on the same freemail provider stay apart


def test_scattered_client_threads_land_in_one_batch():
    # 6 vistergy + 3 exxon + 3 dps, interleaved as recency would scatter them
    convs = (
        [_conv(f"v{i}", "davida@vistergy.com") for i in range(6)]
        + [_conv(f"e{i}", "keith.n.hoffman@exxonmobil.com") for i in range(3)]
        + [_conv(f"d{i}", "ra.bouman@dps.group") for i in range(3)]
    )
    interleaved = [convs[j] for j in [0, 6, 9, 1, 7, 10, 2, 8, 11, 3, 4, 5]]
    batches = pj._batch_by_client(interleaved, OWNER)
    for key in ("vistergy.com", "exxonmobil.com", "dps.group"):
        holding = [b for b in batches if any(pj._conversation_client_key(m, OWNER) == key for _, m in b)]
        assert len(holding) == 1, f"{key} must not be split across batches"


def test_no_conversation_dropped_and_client_grouped():
    convs = [_conv(f"c{i}", f"a@co{i % 4}.com") for i in range(40)]
    batches = pj._batch_by_client(convs, OWNER)
    seen = [cid for b in batches for cid, _ in b]
    assert sorted(seen) == sorted(c[0] for c in convs)  # nothing lost
    # each batch stays under the hard cap
    assert all(len(b) <= pj._CLIENT_BATCH_CAP for b in batches)


def test_single_oversized_client_splits_only_itself():
    convs = [_conv(f"big{i}", "a@huge.com") for i in range(pj._CLIENT_BATCH_CAP + 5)]
    batches = pj._batch_by_client(convs, OWNER)
    assert len(batches) == 2
    assert all(_clients_of(b) == {"huge.com"} for b in batches)


def test_extract_batches_split_retries_on_timeout_no_loss(monkeypatch):
    """A batch too big to extract in one call (simulated timeout → None) must be split and
    retried, not silently dropped — the bug that lost Diar/Vistergy/Exxon on the real run."""
    calls = {"n": 0}

    def fake_extract(batch, ai, display_name, today_str):
        calls["n"] += 1
        if len(batch) > 3:          # oversized call "times out"
            return None
        return [{"id": cid, "name": cid} for cid, _ in batch]  # one project per conv

    monkeypatch.setattr(pj, "_extract_projects_from_batch", fake_extract)
    big = [_conv(f"c{i}", "a@co.com") for i in range(10)]
    raw = pj._extract_batches([big], None, "exec", "2026-07-03")
    assert sorted(p["id"] for p in raw) == sorted(c[0] for c in big)  # every conv recovered
    assert calls["n"] > 1  # it actually retried


def test_extract_batches_empty_is_not_a_failure(monkeypatch):
    # [] (genuine no-project) must NOT trigger a split-retry
    calls = {"n": 0}

    def fake_extract(batch, ai, display_name, today_str):
        calls["n"] += 1
        return []

    monkeypatch.setattr(pj, "_extract_projects_from_batch", fake_extract)
    raw = pj._extract_batches([[_conv(f"c{i}", "a@co.com") for i in range(8)]], None, "x", "y")
    assert raw == []
    assert calls["n"] == 1  # no wasteful re-splitting on genuine empty

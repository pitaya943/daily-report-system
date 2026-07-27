"""故意失敗的測試 — 驗證 CI gate 會擋住 merge"""


def test_this_will_fail():
    assert 1 == 2, "CI gate 測試：這個 PR 不應該能 merge"
